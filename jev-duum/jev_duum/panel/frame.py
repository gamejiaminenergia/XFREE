"""The one frozen value the 60 Hz loop hands the view each refresh.

The dashboard depends on these fields and nothing else: it never sees the
controller or the whole worker, only what a frame needs to be drawn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class WorkerLike(Protocol):
    busy: bool
    stats: Any


@dataclass(frozen=True, slots=True)
class HmiFrame:
    """One refresh of the screen: what to draw, never how it was produced."""

    pilot: str
    snapshot: Any
    decision: Any
    controls: Any
    worker: WorkerLike
    stale: int
    error: str | None
    log_stats: dict | None = None


