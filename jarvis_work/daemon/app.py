"""The daemon. Binds 127.0.0.1 only — nothing here is meant to be reachable
from the network, including from the VM. Traffic to the VM is outbound only.

Run:  python -m jarvis_work.daemon.app
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..config import load_config, db_path
from ..llm.brain import Brain, Tier
from ..llm.triage import Action, route
from ..observers import get_observer
from ..observers.loop import ObserverLoop
from ..redact import Redactor
from .agent_client import AgentClient
from .briefing import build_briefing
from .store import Store

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("jarvis-work.daemon")

cfg = load_config()
store = Store(db_path(cfg))
redactor = Redactor(cfg["observer"].get("blind_apps"),
                    cfg["observer"].get("blind_title_patterns"))
observer = get_observer()
obs_loop = ObserverLoop(observer, store, redactor,
                        interval=cfg["observer"].get("interval_seconds", 5),
                        capture_titles=cfg["observer"].get("capture_titles", True))
agent = AgentClient(cfg["agent"].get("bridge_url", ""),
                    cfg["agent"].get("bridge_token", ""),
                    cfg["agent"].get("enabled", False))
brain = Brain(cfg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("observer: %s | db: %s | agent: %s | brain: %s",
                observer.name, store.path,
                agent.base_url if agent.enabled else "disabled",
                brain.models[Tier.DEFAULT] if brain.available else "no api key")
    obs_loop.start()
    try:
        yield
    finally:
        await obs_loop.stop()
        store.close()


app = FastAPI(title="Jarvis at Work — daemon", version="0.1.0", lifespan=lifespan)


# ── models ───────────────────────────────────────────────────────────────────
class ContextIn(BaseModel):
    app: str = ""
    title: str = ""
    idle_secs: float = 0.0
    locked: bool = False
    extra: dict = Field(default_factory=dict)


class WorkItemIn(BaseModel):
    title: str
    detail: str = ""
    project: str = ""
    source: str = "manual"
    context: dict = Field(default_factory=dict)


class WorkItemPatch(BaseModel):
    status: str | None = None
    note: str | None = None
    project: str | None = None


class MemoryIn(BaseModel):
    fact: str
    tags: str = ""
    source: str = "manual"


class CaptureIn(BaseModel):
    text: str
    dispatch: bool = True     # allow the router to send to Claude, if it decides to


class SendIn(BaseModel):
    text: str
    new_chat: bool = False
    project: str = ""


# ── health + context ─────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"ok": True, "observer": observer.name, "paused": obs_loop.paused,
            "agent_enabled": agent.enabled, "db": str(store.path)}


@app.post("/context")
async def post_context(ctx: ContextIn):
    """For an out-of-process observer. The in-process loop writes directly."""
    if redactor.app_is_blind(ctx.app):
        return {"ok": True, "stored": False, "reason": "blind app"}
    rid = store.add_snapshot(ctx.app, redactor.title(ctx.title), ctx.idle_secs,
                             ctx.locked, ctx.extra)
    return {"ok": True, "stored": True, "id": rid}


@app.get("/context/current")
async def current_context():
    return {"ok": True, "context": store.current_snapshot()}


@app.get("/timeline")
async def timeline(hours: float = 8.0, limit: int = 500):
    since = time.time() - max(0.1, hours) * 3600
    return {"ok": True, "hours": hours, "entries": store.timeline(since, limit)}


@app.post("/observer/pause")
async def pause(paused: bool = True):
    obs_loop.paused = paused
    store.add_event("observer_paused" if paused else "observer_resumed")
    return {"ok": True, "paused": obs_loop.paused}


# ── work items ───────────────────────────────────────────────────────────────
@app.post("/work_items")
async def create_work_item(item: WorkItemIn):
    ctx = dict(item.context)
    if "captured_during" not in ctx:
        snap = store.current_snapshot()
        if snap:
            ctx["captured_during"] = {"app": snap["app"], "title": snap["title"]}
    wid = store.add_work_item(item.title, item.detail, item.project, item.source, ctx)
    store.add_event("work_item_created", {"id": wid, "title": item.title})
    return {"ok": True, "id": wid}


@app.get("/work_items")
async def list_work_items(status: str = "open", limit: int = 100):
    return {"ok": True, "items": store.list_work_items(status, limit)}


@app.patch("/work_items/{item_id}")
async def patch_work_item(item_id: int, patch: WorkItemPatch):
    updated = store.update_work_item(item_id, patch.status, patch.note, patch.project)
    if updated is None:
        raise HTTPException(404, f"no work item {item_id}")
    store.add_event("work_item_updated", {"id": item_id, "status": patch.status})
    return {"ok": True, "item": updated}


# ── memory ───────────────────────────────────────────────────────────────────
@app.post("/memory")
async def create_memory(m: MemoryIn):
    mid = store.add_memory(redactor.text(m.fact), m.tags, m.source)
    return {"ok": True, "id": mid}


@app.get("/memory")
async def get_memory(q: str = "", limit: int = 20):
    items = store.search_memory(q, limit) if q else store.recent_memory(limit)
    return {"ok": True, "query": q, "items": items}


# ── briefing ─────────────────────────────────────────────────────────────────
@app.get("/briefing")
async def briefing():
    return {"ok": True, **build_briefing(store)}


# ── agent bridge passthrough ─────────────────────────────────────────────────
@app.get("/agent/health")
async def agent_health():
    return await agent.health()


@app.get("/agent/state")
async def agent_state():
    return await agent.state()


@app.get("/agent/conversation")
async def agent_conversation(limit: int = 20):
    return await agent.read_conversation(limit)


@app.post("/agent/send")
async def agent_send(body: SendIn):
    # Audit before dispatch: the record must exist even if the VM never answers.
    store.add_event("agent_send", {"text": body.text[:500], "new_chat": body.new_chat,
                                   "project": body.project})
    result = await agent.send(body.text, body.new_chat, body.project)
    store.add_event("agent_send_result", {"ok": result.get("ok"),
                                          "error": result.get("error", "")})
    return result


# ── capture → route → act ────────────────────────────────────────────────────
@app.post("/capture")
async def capture(body: CaptureIn):
    """The one box. Say what you want; Jarvis decides where it goes.

    Always files a work item, whatever the routing says — a capture that
    produced only a chat and no record is how things get lost, which is the
    problem this project exists to solve.
    """
    if not body.text.strip():
        raise HTTPException(400, "Empty capture")
    if not brain.available:
        wid = store.add_work_item(body.text[:120], body.text, source="capture")
        return {"ok": True, "routed": False, "work_item": wid,
                "note": "No Claude API key configured — filed without routing."}

    briefing = build_briefing(store)
    open_items = store.list_work_items(status="open", limit=50)
    try:
        routing, escalated = await run_in_threadpool(
            route, brain, body.text, briefing, open_items)
    except Exception as e:
        wid = store.add_work_item(body.text[:120], body.text, source="capture")
        logger.warning("routing failed, filed anyway: %s", e)
        return {"ok": True, "routed": False, "work_item": wid, "error": str(e)}

    wid = store.add_work_item(routing.title, body.text, routing.project, "capture",
                              {"routing": routing.model_dump(mode="json"),
                               "escalated": escalated})
    store.add_event("capture_routed", {"work_item": wid, "action": routing.action.value,
                                       "escalated": escalated,
                                       "confidence": routing.confidence,
                                       "usage": brain.last_usage})

    result = {"ok": True, "routed": True, "work_item": wid,
              "action": routing.action.value, "title": routing.title,
              "project": routing.project, "reason": routing.reason,
              "confidence": routing.confidence, "escalated": escalated,
              "usage": brain.last_usage}

    if routing.action is Action.DISPATCH and body.dispatch and agent.enabled:
        store.add_event("agent_send", {"text": routing.prompt[:500],
                                       "work_item": wid})
        sent = await agent.send(routing.prompt, routing.new_chat, routing.project)
        store.add_event("agent_send_result", {"ok": sent.get("ok"),
                                              "error": sent.get("error", "")})
        result["dispatched"] = sent
    elif routing.action is Action.DISPATCH:
        result["dispatched"] = {"ok": False,
                                "error": "agent bridge disabled — prompt filed, not sent"}
        result["prompt"] = routing.prompt

    return result


@app.get("/events")
async def events(limit: int = 50):
    return {"ok": True, "events": store.recent_events(limit)}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=cfg["daemon"]["host"], port=int(cfg["daemon"]["port"]),
                log_level="info")


if __name__ == "__main__":
    main()
