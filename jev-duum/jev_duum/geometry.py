"""Spatial policy helpers shared by the deterministic guard and the strategy.

``bearing`` uses the snapshot convention: positive angles are to the player's
LEFT.  ``progress`` answers one question for the code and for the prompt: how
much does moving in this direction close the distance to the goal (1 is
straight at it, 0 is pure sideways, negative walks away).
"""

from __future__ import annotations

import math

from .snapshot import DuumSnapshot

MOVEMENT_ANGLES = {
    "forward": 0.0,
    "strafe_left": math.pi / 2,
    "strafe_right": -math.pi / 2,
    "back": math.pi,
}

# When two directions close the same distance, prefer not to retreat.
_PREFERENCE = ("forward", "strafe_left", "strafe_right", "back")


def progress_scores(bearing: float | None) -> dict[str, float]:
    """Return how much each movement option closes the distance to ``bearing``."""

    if bearing is None:
        return {}
    return {
        name: round(math.cos(angle - bearing), 3)
        for name, angle in MOVEMENT_ANGLES.items()
    }


def best_progress_movement(
    snapshot: DuumSnapshot, bearing: float | None, *, minimum: float = 0.05
) -> str | None:
    """Safe movement with the highest progress above ``minimum``, or ``None``.

    ``hold`` is deliberately not a candidate: standing still never makes
    progress, so the caller decides when standing still is acceptable.
    """

    if bearing is None:
        return None
    scores = progress_scores(bearing)
    safe = {option.name for option in snapshot.movement_options if option.safe}
    candidates = [
        (scores[name], _PREFERENCE.index(name), name)
        for name in _PREFERENCE
        if name in safe and scores.get(name, -1.0) > minimum
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], -item[1]))[2]


def best_clear_movement(snapshot: DuumSnapshot) -> str | None:
    """Safest movement with real clearance, used when nothing makes progress."""

    options = [option for option in snapshot.movement_options if option.safe]
    if not options:
        return None
    best = max(options, key=lambda option: (option.clear_distance, -_PREFERENCE.index(option.name)))
    return best.name if best.clear_distance > 0 else None
