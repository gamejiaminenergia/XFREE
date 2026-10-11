"""The 60 Hz loop: snapshot to worker to dashboard, one screen, one thread here."""

from __future__ import annotations

import statistics
import time

from ..actions import (
    controls_to_mask,
    ensure_usable_weapon,
    settle_assisted_controls,
)
from ..session import policy
from ..snapshot import SnapshotBuilder
from ..types import DuumControls
from ..worker import DecisionWorker
from .dashboard import Dashboard


def advance_completed_level(app) -> bool:
    """Advance Duum's intermission through the same public Space key as a player."""

    if app.finish is None:
        return False
    app.key(32, 0, False)
    return True

def run_jev_window(
    modules,
    wad,
    controller,
    *,
    map_name="E1M1",
    width=320,
    height=200,
    scale=2,
    decision_rate=12.0,
    max_stale_ticks=30,
    fullscreen=True,
    on_decision=None,
):
    """Run normal Duum rendering while a one-in-flight worker chooses controls."""

    modules.desktop.use_clock(None)
    modules.desktop.set_keys(0)
    modules.desktop.mount(str(wad))
    app = modules.engine.Duum()
    pilot = "jev-assisted" if controller.assisted else "jev-raw"
    window = modules.frontend.Window(
        app,
        width=width,
        height=height,
        scale=scale,
        title=f"Duum · {pilot} · Jev",
    )
    app.build(window.cv)
    if app.err:
        window._close()
        raise RuntimeError(f"Duum could not start: {app.err}")
    if map_name and app.level != map_name:
        app.load_level(map_name)
    builder = SnapshotBuilder(app, modules.engine)
    panel = Dashboard(modules.frontend.tkinter, window, fullscreen=fullscreen)
    started = time.perf_counter()
    tick = 0
    frames = 0
    next_decision_time = 0.0
    controls = DuumControls()
    latest = None
    latest_snapshot = builder.build(0)
    stale = 0
    model_error = None
    finish_since = None
    minimum_observation_tick = 0
    latencies = []
    applied_decisions = 0
    worker = DecisionWorker(controller)
    logger = getattr(getattr(controller, "client", None), "logger", None)

    def frame():
        nonlocal tick, frames, next_decision_time, controls, latest, builder
        nonlocal latest_snapshot, stale, model_error, applied_decisions
        nonlocal finish_since, minimum_observation_tick
        if not window.running:
            return
        try:
            result = worker.poll()
        except RuntimeError as error:
            model_error = str(error.__cause__ or error)
            controls = DuumControls()
            result = None
        if result is not None:
            accepted = policy.accept_result(
                tick=tick,
                observation_tick=result.observation_tick,
                minimum_observation_tick=minimum_observation_tick,
                max_stale_ticks=max_stale_ticks,
            )
            stale = policy.stale_after(accepted=accepted, stale=stale)
            if accepted:
                latest = result.with_application_tick(tick + 1)
                controls = latest.applied_controls
                applied_decisions += 1
                latencies.append(latest.decision_ms)
                if latest.hunt is not None:
                    builder.note_hunt_target(latest.hunt.get("target_id"))
                if on_decision:
                    on_decision(latest)
            else:
                stale += 1
        builder.note_controls(controls)
        if controller.assisted:
            ensure_usable_weapon(app, modules.engine)
        modules.desktop.set_keys(controls_to_mask(controls))
        window._frame_once()
        tick += 1
        frames += 1
        latest_snapshot = builder.build(tick)
        if controller.assisted:
            controls = settle_assisted_controls(controls, latest_snapshot)
        controls = policy.release_one_shot(controls)
        finish_since, just_finished, advance_due = policy.observe_intermission(
            finished=latest_snapshot.episode.finished,
            since=finish_since,
            now=time.perf_counter(),
        )
        if just_finished:
            controls = DuumControls()
        elif advance_due and advance_completed_level(app):
            controls = DuumControls()
            builder = SnapshotBuilder(app, modules.engine)
            latest_snapshot = builder.build(tick)
            latest = None
            finish_since = None
            minimum_observation_tick = tick
            next_decision_time = app.now
        if policy.ready_to_submit(
            now=app.now,
            next_decision_time=next_decision_time,
            model_error=model_error,
            dead=latest_snapshot.episode.dead,
            finished=latest_snapshot.episode.finished,
            menu_open=app.menu is not None,
        ):
            worker.submit(latest_snapshot)
            next_decision_time = policy.reschedule(
                app.now, decision_rate, previous=next_decision_time
            )
        if policy.should_refresh(tick=tick, latest=latest, model_error=model_error):
            panel.update(
                pilot=pilot,
                snapshot=latest_snapshot,
                decision=latest,
                controls=controls,
                worker=worker,
                stale=stale,
                error=model_error,
                log_stats=logger.stats if logger is not None else None,
            )
        if getattr(app, "quit", False):
            window._close()
            return
        window.root.after(1, frame)

    try:
        window.root.after(1, frame)
        window.root.mainloop()
    finally:
        worker.close()
        modules.desktop.set_keys(0)
        app.closed()
    wall_seconds = time.perf_counter() - started
    stats = worker.stats
    ordered = sorted(latencies)

    def percentile(fraction):
        if not ordered:
            return None
        return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]

    return {
        "pilot": pilot,
        "model_inference": True,
        "network": "online: api.typesafe.ai",
        "engine_ticks": tick,
        "rendered_frames": frames,
        "wall_seconds": wall_seconds,
        "complete_decisions": applied_decisions,
        "prediction_calls": applied_decisions * 3,
        "worker_completed": stats.completed,
        "worker_replaced": stats.replaced,
        "stale_results": stale,
        "mean_decision_ms": statistics.fmean(latencies) if latencies else None,
        "p50_decision_ms": percentile(0.50),
        "p95_decision_ms": percentile(0.95),
        "p99_decision_ms": percentile(0.99),
        "max_decision_ms": max(latencies) if latencies else None,
        "final_snapshot": latest_snapshot.to_dict(),
        "final_snapshot_hash": latest_snapshot.state_hash(),
        "model_error": model_error,
    }
