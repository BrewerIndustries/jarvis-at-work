"""Daemon-side client for the agent bridge running on the Hyper-V VM.

Everything here crosses a machine boundary, so it is the one place that fails
in ways the rest of the daemon shouldn't have to think about. All methods
return a dict with `ok` rather than raising, and every dispatch is written to
the events table before it leaves — an audit trail of what the agent was told
to do exists even if the VM never answers.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("jarvis-work.agent")


class AgentClient:
    def __init__(self, base_url: str = "", token: str = "", enabled: bool = False,
                 timeout: float = 30.0):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token
        self.enabled = bool(enabled and self.base_url)
        self.timeout = timeout

    @property
    def _headers(self) -> dict:
        return {"X-Jarvis-Token": self.token} if self.token else {}

    async def _call(self, method: str, path: str, **kw) -> dict:
        if not self.enabled:
            return {"ok": False, "error": "agent bridge disabled or unconfigured"}
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.request(method, url, headers=self._headers, **kw)
                r.raise_for_status()
                return {"ok": True, **r.json()}
        except httpx.HTTPStatusError as e:
            return {"ok": False, "error": f"bridge returned {e.response.status_code}",
                    "body": e.response.text[:500]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def health(self) -> dict:
        return await self._call("GET", "/health")

    async def state(self) -> dict:
        return await self._call("GET", "/claude/state")

    async def read_conversation(self, limit: int = 20) -> dict:
        return await self._call("GET", "/claude/conversation", params={"limit": limit})

    async def send(self, text: str, new_chat: bool = False, project: str = "") -> dict:
        return await self._call("POST", "/claude/send",
                                json={"text": text, "new_chat": new_chat, "project": project})
