"""Jarvis's own reasoning — the Claude API, tiered.

Sonnet handles the steady state; Opus is called in when a decision is actually
hard. Two things make that split work rather than just being a cost knob:

  Escalation is decided by the cheap tier, not by us. Every structured decision
  carries a `confidence`, and the router re-runs on the deep tier when that
  comes back low. A model that knows it is guessing is a better escalation
  signal than any heuristic we could write here.

  The system prompt is frozen. Prompt caching is a prefix match — one changing
  byte anywhere in the prefix invalidates the rest — so the stable instructions
  live in `system` behind a cache breakpoint with a 1h TTL, and everything
  volatile (the current snapshot, timestamps, the timeline) goes in the user
  turn *after* it. Putting a clock in the system prompt is the classic way to
  pay full price on every single call while believing caching is on.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel

logger = logging.getLogger("jarvis-work.brain")

T = TypeVar("T", bound=BaseModel)


class Tier(str, Enum):
    FAST = "fast"       # cheap classification: is this even worth acting on
    DEFAULT = "default" # the steady state
    DEEP = "deep"       # hard routing, drafting, anything irreversible


# Verified against the Claude API model table, 2026-06-24.
#   claude-haiku-4-5  $1 / $5   per MTok, 200K context
#   claude-sonnet-5   $3 / $15  per MTok, 1M context  (intro $2/$10 to 2026-08-31)
#   claude-opus-5     $5 / $25  per MTok, 1M context
DEFAULT_MODELS: dict[str, str] = {
    Tier.FAST: "claude-haiku-4-5",
    Tier.DEFAULT: "claude-sonnet-5",
    Tier.DEEP: "claude-opus-5",
}

# Effort controls thinking depth and total spend. Routine triage does not need
# to think hard; the escalated pass does.
DEFAULT_EFFORT: dict[str, str] = {
    Tier.FAST: "low",
    Tier.DEFAULT: "medium",
    Tier.DEEP: "high",
}


class Brain:
    def __init__(self, cfg: dict):
        c = cfg.get("llm", {}) or {}
        self.api_key = c.get("api_key", "")
        self.models = {**DEFAULT_MODELS, **(c.get("models") or {})}
        self.effort = {**DEFAULT_EFFORT, **(c.get("effort") or {})}
        self.escalate_below = float(c.get("escalate_below_confidence", 0.7))
        self.max_tokens = int(c.get("max_tokens", 16000))
        self.cache_ttl = c.get("cache_ttl", "1h")
        self._client = None
        self.last_usage: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _system_blocks(self, system: str) -> list[dict]:
        """The cached prefix. Must be byte-identical across calls to hit."""
        return [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral", "ttl": self.cache_ttl},
        }]

    def _record_usage(self, response) -> None:
        u = getattr(response, "usage", None)
        if u is None:
            return
        self.last_usage = {
            "input": getattr(u, "input_tokens", 0),
            "output": getattr(u, "output_tokens", 0),
            "cache_read": getattr(u, "cache_read_input_tokens", 0),
            "cache_write": getattr(u, "cache_creation_input_tokens", 0),
        }
        # A cache_read of zero on a repeated prefix means something volatile
        # crept into `system`. Worth noticing early — it is a ~10x cost bug
        # that otherwise shows up only on the invoice.
        if self.last_usage["cache_read"] == 0 and self.last_usage["input"] > 1024:
            logger.debug("no cache hit (%s input tokens) — check prefix stability",
                         self.last_usage["input"])

    # ── plain text ───────────────────────────────────────────────────────────
    def think(self, system: str, user: str, tier: Tier = Tier.DEFAULT,
              effort: str | None = None) -> str:
        if not self.available:
            raise RuntimeError("No Claude API key configured (llm.api_key)")
        resp = self.client.messages.create(
            model=self.models[tier],
            max_tokens=self.max_tokens,
            system=self._system_blocks(system),
            output_config={"effort": effort or self.effort[tier]},
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": user}],
        )
        self._record_usage(resp)
        if resp.stop_reason == "refusal":
            cat = getattr(getattr(resp, "stop_details", None), "category", None)
            raise RuntimeError(f"Claude declined this request (category: {cat})")
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    # ── structured ───────────────────────────────────────────────────────────
    def structured(self, system: str, user: str, schema: type[T],
                   tier: Tier = Tier.DEFAULT, effort: str | None = None) -> T:
        if not self.available:
            raise RuntimeError("No Claude API key configured (llm.api_key)")
        resp = self.client.messages.parse(
            model=self.models[tier],
            max_tokens=self.max_tokens,
            system=self._system_blocks(system),
            output_config={"effort": effort or self.effort[tier]},
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        self._record_usage(resp)
        return resp.parsed_output

    def decide(self, system: str, user: str, schema: type[T],
               tier: Tier = Tier.DEFAULT) -> tuple[T, bool]:
        """Structured decision with automatic escalation.

        Returns (decision, escalated). If the schema carries a `confidence`
        field and the cheap tier comes back under the threshold, the same
        question is put to the deep tier and that answer wins.
        """
        first = self.structured(system, user, schema, tier=tier)
        conf = getattr(first, "confidence", None)
        if tier is Tier.DEEP or conf is None or conf >= self.escalate_below:
            return first, False
        logger.info("escalating to %s (confidence %.2f < %.2f)",
                    self.models[Tier.DEEP], conf, self.escalate_below)
        return self.structured(system, user, schema, tier=Tier.DEEP), True
