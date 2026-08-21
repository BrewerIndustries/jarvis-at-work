from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Protocol


@dataclass
class Snapshot:
    app: str = ""
    title: str = ""
    idle_secs: float = 0.0
    locked: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Observer(Protocol):
    name: str

    def snapshot(self) -> Snapshot:
        """One reading of what is happening on this machine right now."""
        ...


class NullObserver:
    """Used on unsupported platforms so the daemon still runs."""

    name = "null"

    def snapshot(self) -> Snapshot:
        return Snapshot(app="", title="", idle_secs=0.0, locked=False,
                        extra={"observer": "null"})
