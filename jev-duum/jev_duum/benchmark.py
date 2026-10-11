"""Synchronous headless pilots and complete-loop metrics."""

from __future__ import annotations

import statistics
import time
from dataclasses import replace

from .actions import controls_to_mask, ensure_usable_weapon, settle_assisted_controls
from .integration import DuumRuntime
from .pilots import RandomPilot, heuristic_controls, scripted_controls
from .prompts import DEFAULT_PROMPT_VERSION
from .scheduler import FractionalScheduler
from .snapshot import SnapshotBuilder
from .types import DuumControls


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def run_headless(
    modules,
    wad,
    *,
    pilot,
    map_name="E1M1",
    ticks=600,
    width=160,
    height=100,
    decision_rate=12,
    seed=0,
    controller=None,
    recorder=None,
    checkpoint_every=60,
):
    if pilot in ("jev-raw", "jev-assisted") and controller is None:
        raise ValueError("Jev pilot requires a controller")
    scheduler = FractionalScheduler(60, decision_rate)
    random_pilot = RandomPilot(seed)
    controls = DuumControls()
    decision_count = 0
    prediction_calls = 0
    decision_ms = []
    cost_usd = 0.0
    assistance = 0
    render_events = 0
    started = time.perf_counter()
    with DuumRuntime(modules, wad.path, map_name, width, height) as runtime:
        builder = SnapshotBuilder(runtime.app, modules.engine)
        snapshot = builder.build(0)
        for index in range(ticks):
            if scheduler.due():
                recorded = None
                if pilot in ("jev-raw", "jev-assisted"):
                    decision = controller.decide(snapshot).with_application_tick(runtime.ticks + 1)
                    controls = decision.applied_controls
                    decision_count += 1
                    prediction_calls += decision.prediction_calls
                    decision_ms.append(decision.decision_ms)
                    cost_usd += decision.cost_usd
                    assistance += len(decision.assistance_events)
                    recorded = decision
                elif pilot == "heuristic":
                    controls = heuristic_controls(snapshot)
                    decision_count += 1
                elif pilot == "random":
                    controls = random_pilot.decide(snapshot)
                    decision_count += 1
                elif pilot == "scripted":
                    controls = scripted_controls(index)
                    decision_count += 1
                else:
                    raise ValueError(f"Unsupported headless pilot: {pilot}")
                if recorder:
                    if recorded is not None:
                        recorder.decision(recorded, snapshot)
                    else:
                        recorder.capture(snapshot, DEFAULT_PROMPT_VERSION)
                    recorder.controls(runtime.ticks + 1, controls, controls_to_mask(controls))
            builder.note_controls(controls)
            if pilot == "jev-assisted":
                ensure_usable_weapon(runtime.app, modules.engine)
            state, _, repaint = runtime.step(controls)
            render_events += int(repaint)
            snapshot = builder.build(runtime.ticks)
            if recorder and (
                state.tick % checkpoint_every == 0
                or state.tick == ticks
                or snapshot.episode.dead
                or snapshot.episode.finished
            ):
                recorder.checkpoint(state)
            scheduler.advance()
            previous_controls = controls
            if pilot == "jev-assisted":
                controls = settle_assisted_controls(controls, snapshot)
            # Use is a semantic one-shot. Release it after its application tick.
            if controls.interaction == "use":
                controls = replace(controls, interaction="neither")
            if recorder and controls != previous_controls:
                recorder.controls(runtime.ticks + 1, controls, controls_to_mask(controls))
            if snapshot.episode.dead or snapshot.episode.finished:
                break
        final_state = state
        engine_ticks = runtime.ticks
    wall_seconds = time.perf_counter() - started
    summary = {
        "pilot": pilot,
        "mode": "synchronous",
        "model_inference": controller is not None,
        "network": "online: api.typesafe.ai" if controller is not None else "offline",
        "map": map_name,
        "engine_ticks": engine_ticks,
        "simulated_seconds": snapshot.episode.game_time,
        "wall_seconds": wall_seconds,
        "ticks_per_second": engine_ticks / wall_seconds if wall_seconds else None,
        "render_events": render_events,
        "complete_decisions": decision_count,
        "prediction_calls": prediction_calls,
        "requested_decision_rate": decision_rate,
        "observed_decision_rate": (
            decision_count / snapshot.episode.game_time if snapshot.episode.game_time else None
        ),
        "mean_decision_ms": statistics.fmean(decision_ms) if decision_ms else None,
        "p50_decision_ms": _percentile(decision_ms, 0.50),
        "p95_decision_ms": _percentile(decision_ms, 0.95),
        "p99_decision_ms": _percentile(decision_ms, 0.99),
        "max_decision_ms": max(decision_ms) if decision_ms else None,
        "assistance_interventions": assistance,
        "cost_usd": cost_usd if controller is not None else None,
        "final": snapshot.to_dict(),
        "final_snapshot_hash": snapshot.state_hash(),
        "final_engine_hash": final_state.state_hash(),
    }
    if recorder:
        summary["recording"] = str(recorder.finish(summary))
    return summary
