"""The conventions block and the tolerances the model is told to trust.

Signs, safe flags and distances travel in ``state.conventions``; the two
route tolerances are quoted in the objective rubric so the model never does
arithmetic that code already did."""

from __future__ import annotations

import math

from ..types import (
    ROUTE_AIM_TOLERANCE_RADIANS,
    ROUTE_FORWARD_TOLERANCE_RADIANS,
)

ROUTE_AIM_TOLERANCE_DEGREES = round(math.degrees(ROUTE_AIM_TOLERANCE_RADIANS), 2)
ROUTE_FORWARD_TOLERANCE_DEGREES = round(
    math.degrees(ROUTE_FORWARD_TOLERANCE_RADIANS), 2
)

CONVENTIONS = {
    "bearing_degrees": "Degrees to turn: positive means LEFT, negative means RIGHT.",
    "shot_would_hit": "Computed by code: an unobstructed shot reaches that target now.",
    "safe": "false means geometry blocks that direction; hold is always safe.",
    "distance_units": "contact under 96, near 96-240, medium 240-560, far over 560.",
    "pickup_need": {
        "critical": "take now",
        "urgent": "worth a detour",
        "useful": "only if on the way",
    },
}

_SEE = "Read `conventions` for signs, safe flags and distances."
