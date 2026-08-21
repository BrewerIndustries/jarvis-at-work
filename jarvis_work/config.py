"""Config loading. Looks for config.yaml next to the repo root, falls back to
config.example.yaml so a fresh clone still starts."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

_DEFAULTS: dict[str, Any] = {
    "daemon": {"host": "127.0.0.1", "port": 8765, "db_path": "data/jarvis-work.db"},
    "observer": {
        "interval_seconds": 5,
        "capture_titles": True,
        "capture_clipboard": False,
        "blind_apps": [],
        "blind_title_patterns": [],
    },
    "agent": {"bridge_url": "", "bridge_token": "", "enabled": False},
    "mcp": {"daemon_url": "http://127.0.0.1:8765"},
    "llm": {"api_key": "", "models": {}, "effort": {},
            "escalate_below_confidence": 0.7, "max_tokens": 16000, "cache_ttl": "1h"},
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_config(path: str | os.PathLike | None = None) -> dict:
    if path:
        candidates = [Path(path)]
    else:
        candidates = [REPO_ROOT / "config.yaml", REPO_ROOT / "config.example.yaml"]
    for p in candidates:
        if p.exists():
            with open(p) as f:
                cfg = _merge(_DEFAULTS, yaml.safe_load(f) or {})
            return _apply_env(cfg)
    return _apply_env(dict(_DEFAULTS))


def _apply_env(cfg: dict) -> dict:
    """Environment wins over the file, so the API key can stay out of config.yaml."""
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        cfg.setdefault("llm", {})["api_key"] = key
    if tok := os.environ.get("JARVIS_BRIDGE_TOKEN"):
        cfg.setdefault("agent", {})["bridge_token"] = tok
    return cfg


def db_path(cfg: dict) -> Path:
    p = Path(cfg["daemon"]["db_path"])
    return p if p.is_absolute() else REPO_ROOT / p
