"""The agent bridge. Runs ON THE VM, not on the work laptop.

The only thing on this machine that listens on the network. It is deliberately
tiny and does exactly four things, because it is the one component reachable
from another host.

    python -m jarvis_work.agent.uia_bridge

Security posture, such as it is: a shared token, and a bind address you set
yourself. This is not a hardened service — it is a private host-only network
between two machines you own. Do not expose it beyond the Hyper-V switch.
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .claude_driver import ClaudeDriver, ClaudeDriverError

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("jarvis-work.bridge")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_DEFAULTS = {
    "bridge": {"host": "0.0.0.0", "port": 8766, "token": ""},
    "claude": {"composer_automation_id": "", "composer_control_type": "EditControl",
               "composer_name": "", "new_chat_hotkey": "ctrl+n",
               "send_delay_seconds": 0.4, "search_depth": 12},
}


def _load() -> dict:
    for name in ("config.agent.yaml", "config.agent.example.yaml"):
        p = REPO_ROOT / name
        if p.exists():
            data = yaml.safe_load(p.read_text()) or {}
            merged = {k: {**v, **(data.get(k) or {})} for k, v in _DEFAULTS.items()}
            return merged
    return {k: dict(v) for k, v in _DEFAULTS.items()}


cfg = _load()
TOKEN = os.environ.get("JARVIS_BRIDGE_TOKEN") or cfg["bridge"].get("token") or ""
driver = ClaudeDriver(cfg)
app = FastAPI(title="Jarvis at Work — agent bridge", version="0.1.0")


def require_token(x_jarvis_token: str = Header(default="")) -> None:
    if not TOKEN:
        raise HTTPException(500, "Bridge has no token configured — refusing all requests. "
                                 "Set bridge.token in config.agent.yaml.")
    if not secrets.compare_digest(x_jarvis_token, TOKEN):
        raise HTTPException(401, "Bad or missing X-Jarvis-Token")


class SendIn(BaseModel):
    text: str
    new_chat: bool = False
    project: str = ""


@app.get("/health")
async def health():
    """Unauthenticated on purpose — it reports nothing but liveness, and being
    able to check reachability before auth is worth more than hiding it."""
    return {"ok": True, "service": "jarvis-at-work agent bridge",
            "token_configured": bool(TOKEN)}


@app.get("/claude/state", dependencies=[Depends(require_token)])
async def claude_state():
    try:
        return {"ok": True, **driver.state()}
    except ClaudeDriverError as e:
        raise HTTPException(503, str(e))


@app.get("/claude/conversation", dependencies=[Depends(require_token)])
async def claude_conversation(limit: int = 20):
    try:
        return {"ok": True, "blocks": driver.read_conversation(limit)}
    except ClaudeDriverError as e:
        raise HTTPException(503, str(e))


@app.post("/claude/send", dependencies=[Depends(require_token)])
async def claude_send(body: SendIn):
    logger.info("send: new_chat=%s project=%r text=%r", body.new_chat, body.project,
                body.text[:80])
    try:
        return {"ok": True, **driver.send(body.text, body.new_chat)}
    except ClaudeDriverError as e:
        raise HTTPException(503, str(e))


def main() -> None:
    import uvicorn
    if not TOKEN:
        logger.warning("No bridge token set — every request will be refused. "
                       "Set bridge.token in config.agent.yaml first.")
    uvicorn.run(app, host=cfg["bridge"]["host"], port=int(cfg["bridge"]["port"]),
                log_level="info")


if __name__ == "__main__":
    main()
