"""Dependency-free adapter value types. Duum is imported only by integration.py."""

from __future__ import annotations

from dataclasses import dataclass

MOVEMENTS = ("forward", "back", "strafe_left", "strafe_right", "hold")
AIMS = ("left", "straight", "right")
INTERACTIONS = ("fire", "use", "neither")

# Alignment tolerances shared by the deterministic guard and the prompt text.
# The guard turns toward a route until it is inside the aim tolerance and only
# advances along a route that is inside the forward tolerance.
ROUTE_AIM_TOLERANCE_RADIANS = 0.04
ROUTE_FORWARD_TOLERANCE_RADIANS = 0.08


@dataclass(frozen=True, slots=True)
class AssistanceEvent:
    """One deterministic override of a raw proposal, kept for the record."""

    kind: str
    reason: str
    proposed: str
    applied: str


@dataclass(frozen=True, slots=True)
class DuumControls:
    movement: str = "hold"
    aim: str = "straight"
    interaction: str = "neither"

    def __post_init__(self) -> None:
        if self.movement not in MOVEMENTS:
            raise ValueError(f"movement must be one of {MOVEMENTS}")
        if self.aim not in AIMS:
            raise ValueError(f"aim must be one of {AIMS}")
        if self.interaction not in INTERACTIONS:
            raise ValueError(f"interaction must be one of {INTERACTIONS}")
