"""The session core: one engine, one builder, one decision worker, one thread.

This is the backend.  It owns the engine and publishes one :class:`Frame` per
tick to whoever subscribed — the terminal UI, the HTTP service, a test.  It
imports no Tk and no web framework, so it runs headless: no display, no X, no
window, and the pixels come from the engine's own RGB buffer.

One process, one ``Session``: the engine is a single-threaded Python object, so
nothing else may advance it.  Frontends read frames; they never touch it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..actions import ensure_usable_weapon, settle_assisted_controls
from ..snapshot import SnapshotBuilder
from ..types import DuumControls
from ..worker import DecisionWorker
from . import policy

# The panel refreshes at ~15 Hz; a headless consumer usually wants less.  This is
# how often a *frame* is produced, independent of how often the engine ticks.
DEFAULT_FRAME_EVERY = 2


def advance_completed_level(app) -> bool:
    """Advance Duum's intermission through the same public Space key as a player."""

    if app.finish is None:
        return False
    app.key(32, 0, False)
    return True


@dataclass(frozen=True, slots=True)
class Frame:
    """One refresh of the session: everything a frontend is allowed to see."""

    tick: int
    snapshot: Any
    decision: Any
    controls: DuumControls
    stale: int
    error: str | None
    busy: bool
    submitted: int
    completed: int
    replaced: int
    failed: int
    applied: int
    log_stats: dict | None = None
    rgb: bytes | None = None

    @property
    def dead(self) -> bool:
        return bool(self.snapshot.episode.dead)

    @property
    def finished(self) -> bool:
        return bool(self.snapshot.episode.finished)


class Session:
    """Drive one Duum engine with one Jev controller, headless and pausable.

    ``runtime`` is a :class:`~jev_duum.integration.DuumRuntime` (a real engine on
    a fixed 60 Hz clock); ``controller`` is anything with ``.decide(snapshot)``.
    """

    def __init__(
        self,
        runtime,
        controller,
        *,
        decision_rate: float = 10.0,
        max_stale_ticks: int = 30,
        pixels: bool = True,
        frame_every: int = DEFAULT_FRAME_EVERY,
        pilot: str | None = None,
        on_decision: Callable[[Any], None] | None = None,
    ):
        self.runtime = runtime
        self.modules = runtime.modules
        self.app = runtime.app
        self.engine = runtime.modules.engine
        self.controller = controller
        self.assisted = bool(getattr(controller, "assisted", False))
        self.pilot = pilot or ("jev-assisted" if self.assisted else "jev-raw")
        self.decision_rate = float(decision_rate)
        self.max_stale_ticks = int(max_stale_ticks)
        self.pixels = bool(pixels)
        self.frame_every = max(1, int(frame_every))
        self.on_decision = on_decision
        self.logger = getattr(getattr(controller, "client", None), "logger", None)

        self.builder = SnapshotBuilder(self.app, self.engine)
        self.worker = DecisionWorker(controller)
        self.tick = 0
        self.frames = 0
        self.controls = DuumControls()
        self.latest = None
        self.snapshot = self.builder.build(0)
        self.stale = 0
        self.applied = 0
        self.error: str | None = None
        self.finish_since: float | None = None
        self.minimum_observation_tick = 0
        self.next_decision_time = 0.0
        self.paused = False
        self._lock = threading.Lock()
        self._last_frame: Frame | None = None

    # -- one tick ------------------------------------------------------------
    def step(self) -> Frame:
        """Advance the engine one tick and publish the frame.

        Paused means paused: the engine does not move and nothing is asked of the
        model, so resuming continues exactly where it stopped.
        """

        if self.paused:
            return self._last_frame or self._observe(make_frame=True)

        with self._lock:
            self._accept_result()
            self.builder.note_controls(self.controls)
            if self.assisted:
                ensure_usable_weapon(self.app, self.engine)
            self._advance_engine()
            frame = self._observe(make_frame=True)
            self._submit_if_due()
            return frame

    def _accept_result(self) -> None:
        try:
            result = self.worker.poll()
        except RuntimeError as error:
            self.error = str(error.__cause__ or error)
            self.controls = DuumControls()
            return
        if result is None:
            return
        if policy.accept_result(
            tick=self.tick,
            observation_tick=result.observation_tick,
            minimum_observation_tick=self.minimum_observation_tick,
            max_stale_ticks=self.max_stale_ticks,
        ):
            self.latest = result.with_application_tick(self.tick + 1)
            self.controls = self.latest.applied_controls
            self.applied += 1
            if self.latest.hunt is not None:
                self.builder.note_hunt_target(self.latest.hunt.get("target_id"))
            if self.on_decision:
                self.on_decision(self.latest)
        else:
            self.stale += 1

    def _advance_engine(self) -> None:
        want_frame = self.pixels and (self.tick % self.frame_every == 0)
        self.runtime.step(self.controls, draw=want_frame)
        self.tick = self.runtime.ticks
        self.snapshot = self.builder.build(self.tick)
        if self.assisted:
            self.controls = settle_assisted_controls(self.controls, self.snapshot)

    def _observe(self, *, make_frame: bool) -> Frame:
        controls = policy.release_one_shot(self.controls)
        self.controls = controls

        finished = bool(self.snapshot.episode.finished)
        self.finish_since, just_finished, advance_due = policy.observe_intermission(
            finished=finished, since=self.finish_since, now=self.app.now
        )
        if just_finished:
            self.controls = DuumControls()
            controls = self.controls
        elif advance_due and self._advance_level():
            controls = self.controls

        stats = self.worker.stats
        rgb = None
        if self.pixels and make_frame:
            rgb = bytes(self.runtime.canvas.buf)
        frame = Frame(
            tick=self.tick,
            snapshot=self.snapshot,
            decision=self.latest,
            controls=controls,
            stale=self.stale,
            error=self.error,
            busy=self.worker.busy,
            submitted=stats.submitted,
            completed=stats.completed,
            replaced=stats.replaced,
            failed=stats.failed,
            applied=self.applied,
            log_stats=self.logger.stats if self.logger is not None else None,
            rgb=rgb,
        )
        self._last_frame = frame
        if rgb is not None:
            self.frames += 1
        return frame

    def _advance_level(self) -> bool:
        if not advance_completed_level(self.app):
            return False
        self.controls = DuumControls()
        self.builder = SnapshotBuilder(self.app, self.engine)
        self.snapshot = self.builder.build(self.tick)
        self.latest = None
        self.finish_since = None
        self.minimum_observation_tick = self.tick
        self.next_decision_time = self.app.now
        return True

    def _submit_if_due(self) -> None:
        if not policy.ready_to_submit(
            now=self.app.now,
            next_decision_time=self.next_decision_time,
            model_error=self.error,
            dead=bool(self.snapshot.episode.dead),
            finished=bool(self.snapshot.episode.finished),
            menu_open=self.app.menu is not None,
        ):
            return
        self.worker.submit(self.snapshot)
        self.next_decision_time = policy.reschedule(
            self.app.now, self.decision_rate, previous=self.next_decision_time
        )

    # -- control -------------------------------------------------------------
    def frame_size(self) -> tuple[int, int]:
        """The engine buffer's size: a frontend paints cells from it."""

        return (self.runtime.canvas.w, self.runtime.canvas.h)

    def set_paused(self, paused: bool) -> bool:
        self.paused = bool(paused)
        return self.paused

    def set_pixels(self, enabled: bool) -> bool:
        """Turn frame production on or off.

        A frontend that is not drawing the game (a narrow terminal, a data-only
        consumer) should not pay for copying the engine's RGB buffer every
        frame: that copy is most of the per-step cost.
        """

        self.pixels = bool(enabled)
        return self.pixels

    def set_decision_rate(self, rate: float) -> float:
        rate = float(rate)
        if rate <= 0:
            raise ValueError("decision rate must be positive")
        self.decision_rate = rate
        return rate

    # -- loop ----------------------------------------------------------------
    def run(
        self,
        *,
        stop: threading.Event | None = None,
        realtime: bool = True,
        fps: float = 60.0,
        on_frame: Callable[[Frame], None] | None = None,
    ) -> dict:
        """Run until ``stop`` is set (or forever).  Returns the session summary."""

        period = 1.0 / float(fps)
        next_at = time.perf_counter()
        started = time.perf_counter()
        while not (stop is not None and stop.is_set()):
            frame = self.step()
            if on_frame is not None:
                on_frame(frame)
            if realtime:
                next_at += period
                delay = next_at - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_at = time.perf_counter()
        return self.summary(wall_seconds=time.perf_counter() - started)

    def summary(self, *, wall_seconds: float | None = None) -> dict:
        stats = self.worker.stats
        episode = self.snapshot.episode
        return {
            "pilot": self.pilot,
            "engine_ticks": self.tick,
            "frames": self.frames,
            "simulated_seconds": episode.game_time,
            "wall_seconds": wall_seconds,
            "applied_decisions": self.applied,
            "worker_completed": stats.completed,
            "worker_replaced": stats.replaced,
            "worker_failed": stats.failed,
            "stale_results": self.stale,
            "kills": episode.kills,
            "dead": bool(episode.dead),
            "finished": bool(episode.finished),
            "final_snapshot_hash": self.snapshot.state_hash(),
        }

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        self.worker.close()
        self.runtime.close()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *_) -> None:
        self.close()
