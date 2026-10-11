"""The tick policy of a real-time Jev session, as pure functions.

``run_jev_window`` used to keep these decisions inline: when to ask the model,
whether a finished decision is still worth applying, when the intermission ends
and the level advances, and how often the screen is repainted.  They live here
so the Tk window, the terminal UI and the HTTP service all pace a session the
same way — one source of truth, testable without an engine, a window or a clock.

Nothing here imports Tk, the engine or the network: the caller owns the clock
and passes ``now`` in.
"""

from __future__ import annotations

from dataclasses import replace

from ..types import DuumControls

# The screen is repainted every N engine ticks (~15 Hz at 60 fps).  The telemetry
# inside the panel has its own, slower throttle; this is the panel's own cadence.
REFRESH_TICKS = 4
# How long the end-of-level screen is held before the next level is requested.
LEVEL_GRACE_SECONDS = 1.0
# ``app.now`` is a float clock; comparing with a hair of slack keeps a decision
# scheduled for exactly this instant from being pushed a whole tick.
SCHEDULE_EPSILON = 1e-9


def accept_result(
    *, tick: int, observation_tick: int, minimum_observation_tick: int, max_stale_ticks: int
) -> bool:
    """Is a finished decision still worth applying?

    It is not when it took longer than ``max_stale_ticks`` to come back, nor when
    it was observed in the *previous* level — a decision from before the level
    change would drive the new level with the old one's state.
    """

    return (
        tick - observation_tick <= max_stale_ticks
        and observation_tick >= minimum_observation_tick
    )


def ready_to_submit(
    *,
    now: float,
    next_decision_time: float,
    model_error: str | None,
    dead: bool,
    finished: bool,
    menu_open: bool,
) -> bool:
    """Should another snapshot go to the model on this tick?

    Never after a failure (a broken link would just pile up requests), never into
    a dead or finished episode, never over an open engine menu, and only when the
    decision rate says it is due.
    """

    return (
        model_error is None
        and not dead
        and not finished
        and not menu_open
        and now + SCHEDULE_EPSILON >= next_decision_time
    )


def reschedule(now: float, decision_rate: float, *, previous: float) -> float:
    """The next decision instant after a submission at ``now``.

    Normally one decision interval later.  If the session fell behind (a slow
    model, a paused window), it resynchronises from now instead of trying to
    catch up with a backlog of past instants.
    """

    following = previous + 1.0 / decision_rate
    if following < now:
        return now + 1.0 / decision_rate
    return following


def observe_intermission(
    *, finished: bool, since: float | None, now: float, grace: float = LEVEL_GRACE_SECONDS
) -> tuple[float | None, bool, bool]:
    """Track the end-of-level pause.

    Returns ``(since, just_finished, due)``: the new marker (``None`` while the
    level is running), whether this is the first tick of the intermission, and
    whether the pause has lasted long enough to ask for the next level.
    """

    if not finished:
        return None, False, False
    if since is None:
        return now, True, False
    return since, False, (now - since) >= grace


def should_refresh(*, tick: int, latest, model_error: str | None) -> bool:
    """Should the screen be repainted on this tick?

    Every ``REFRESH_TICKS``, plus always while there is no decision yet or the
    link is down, so the operator never watches a stale screen during a failure.
    """

    return tick % REFRESH_TICKS == 0 or latest is None or model_error is not None


def release_one_shot(controls: DuumControls) -> DuumControls:
    """Drop a ``use`` after its application tick: it is a semantic one-shot."""

    if controls.interaction == "use":
        return replace(controls, interaction="neither")
    return controls
