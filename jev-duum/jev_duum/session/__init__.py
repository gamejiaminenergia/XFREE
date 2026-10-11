"""The session core: engine, snapshot and decisions, with no frontend attached.

``policy`` is the pacing rulebook; ``core`` (a later step) is the object that
owns the engine, the ``SnapshotBuilder`` and the decision worker and hands out
one ``Frame`` per tick.  The Tk window, the terminal UI and the HTTP service are
all frontends over this package; none of them is imported from here.
"""

from __future__ import annotations

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
