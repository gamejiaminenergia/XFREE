"""Dependency-free adapter value types. Duum is imported only by integration.py."""

from __future__ import annotations

from dataclasses import dataclass

MOVEMENTS = ("forward", "back", "strafe_left", "strafe_right", "hold")
AIMS = ("left", "straight", "right")
INTERACTIONS = ("fire", "use", "neither")


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
