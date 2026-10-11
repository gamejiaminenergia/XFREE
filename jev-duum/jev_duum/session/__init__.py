"""The session core: the backend, with no frontend attached.

``policy`` is the pacing rulebook; ``core`` is the object that owns the engine,
the snapshot builder and the decision worker and publishes one ``Frame`` per
tick.  The Tk window, the terminal UI and the HTTP service are all frontends
over this package; none of them is imported from here.
"""

from __future__ import annotations

from .core import DEFAULT_FRAME_EVERY, Frame, Session, advance_completed_level
from .policy import (
    LEVEL_GRACE_SECONDS,
    REFRESH_TICKS,
    SCHEDULE_EPSILON,
    accept_result,
    observe_intermission,
    ready_to_submit,
    release_one_shot,
    reschedule,
    should_refresh,
)

__all__ = [
    "Session",
    "Frame",
    "DEFAULT_FRAME_EVERY",
    "advance_completed_level",
    "REFRESH_TICKS",
    "LEVEL_GRACE_SECONDS",
    "SCHEDULE_EPSILON",
    "accept_result",
    "observe_intermission",
    "ready_to_submit",
    "release_one_shot",
    "reschedule",
    "should_refresh",
]
