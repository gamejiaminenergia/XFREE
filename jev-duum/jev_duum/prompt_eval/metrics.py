"""The scoring side: the deterministic reference per snapshot and the counters
the report is built from."""

from __future__ import annotations

import collections
import statistics

PLAN_AIM_TOLERANCE_DEGREES = 2.29  # the guard's route aim tolerance

def _plan_aim(strategy: dict | None) -> str | None:
    """The aim the code's plan asks for, or ``None`` when it has no focus."""

    if not strategy:
        return None
    focus = strategy.get("focus") or {}
    kind = focus.get("kind")
    bearing = focus.get("bearing_degrees")
    if kind in (None, "none") or bearing is None:
        return None
    if kind == "threat" and focus.get("shot_would_hit"):
        return "straight"
    if kind != "threat" and abs(bearing) <= PLAN_AIM_TOLERANCE_DEGREES:
        return "straight"
    return "left" if bearing > 0 else "right"

def _empty_metrics(version: str) -> dict:
    return {
        "version": version,
        "decisions": 0,
        "errors": 0,
        "aim_reference_agreement": 0,
        "aim_direction_error": 0,
        "straight_outside_tolerance": 0,
        "fire_without_corridor": 0,
        "fire_without_ready": 0,
        "fire_reference_available": 0,
        "fire_expected": 0,
        "fire_missed": 0,
        "fire_recall": 0,
        "movement_reference_agreement": 0,
        "moving": 0,
        "progress_made": 0,
        "blocked_hold": 0,
        "hold_decisions": 0,
        "strategy_interventions": 0,
        "unsafe_movement": 0,
        "unsafe_proposal": 0,
        "hold_rate": 0,
        "straight_aim_rate": 0,
        "plan_aim_available": 0,
        "plan_aim_agreement": 0,
        "plan_aim_error": 0,
        "predicted_interventions": 0,
        "predicted_intervention_kinds": collections.Counter(),
        "tokens": [],
        "request_ms": [],
        "confidence": {"movement": [], "aim": [], "interaction": []},
        "cost_usd": 0.0,
        "model_ids": set(),
    }


def _score_decision(metrics: dict, reference: dict, result: dict) -> None:
    controls = result["controls"]
    applied = result["applied"]
    metrics["decisions"] += 1
    if controls["aim"] == reference["aim"]:
        metrics["aim_reference_agreement"] += 1
    elif {controls["aim"], reference["aim"]} == {"left", "right"}:
        metrics["aim_direction_error"] += 1
    if controls["aim"] == "straight" and reference["aim"] != "straight":
        metrics["straight_outside_tolerance"] += 1
    plan_aim = _plan_aim(result.get("strategy"))
    if plan_aim is not None:
        metrics["plan_aim_available"] += 1
        if controls["aim"] == plan_aim:
            metrics["plan_aim_agreement"] += 1
        elif {controls["aim"], plan_aim} == {"left", "right"}:
            metrics["plan_aim_error"] += 1
    if applied["movement"] == reference["movement"]:
        metrics["movement_reference_agreement"] += 1
    if reference["unsafe"].get(applied["movement"], False):
        metrics["unsafe_movement"] += 1
    if reference["unsafe"].get(controls["movement"], False):
        metrics["unsafe_proposal"] += 1
    if applied["movement"] == "hold":
        metrics["hold_rate"] += 1
        metrics["hold_decisions"] += 1
        if not reference["progress_available"]:
            metrics["blocked_hold"] += 1
    else:
        metrics["moving"] += 1
    if reference["progress"].get(applied["movement"], -1.0) > 0.05:
        metrics["progress_made"] += 1
    metrics["strategy_interventions"] += len(result.get("strategy_interventions", ()))
    if controls["aim"] == "straight":
        metrics["straight_aim_rate"] += 1
    if reference["fire_expected"]:
        metrics["fire_expected"] += 1
        if controls["interaction"] == "fire":
            metrics["fire_recall"] += 1
        else:
            metrics["fire_missed"] += 1
    elif reference["fire_allowed"]:
        metrics["fire_reference_available"] += 1
        if controls["interaction"] == "fire":
            metrics["fire_without_ready"] += 1
    elif controls["interaction"] == "fire":
        metrics["fire_without_corridor"] += 1
    metrics["tokens"].append(result["tokens"])
    metrics["cost_usd"] += result["cost_usd"]
    metrics["request_ms"].append(result["request_ms"])
    for name, value in result["confidence"].items():
        if value is not None:
            metrics["confidence"][name].append(value)
    if result["model_id"]:
        metrics["model_ids"].add(result["model_id"])


def _finalize(metrics: dict) -> dict:
    decisions = metrics["decisions"] or 1
    confidence = {
        name: round(statistics.fmean(values), 3) if values else None
        for name, values in metrics["confidence"].items()
    }
    return {
        "version": metrics["version"],
        "decisions": metrics["decisions"],
        "errors": metrics["errors"],
        "aim_reference_agreement": round(metrics["aim_reference_agreement"] / decisions, 3),
        "aim_direction_error": round(metrics["aim_direction_error"] / decisions, 3),
        "plan_aim_agreement": (
            round(metrics["plan_aim_agreement"] / metrics["plan_aim_available"], 3)
            if metrics["plan_aim_available"]
            else None
        ),
        "plan_aim_error": (
            round(metrics["plan_aim_error"] / metrics["plan_aim_available"], 3)
            if metrics["plan_aim_available"]
            else None
        ),
        "straight_outside_tolerance": round(
            metrics["straight_outside_tolerance"] / decisions, 3
        ),
        "fire_without_corridor": round(metrics["fire_without_corridor"] / decisions, 3),
        "fire_expected": metrics["fire_expected"],
        "fire_missed": metrics["fire_missed"],
        "fire_recall": (
            round(metrics["fire_recall"] / metrics["fire_expected"], 3)
            if metrics["fire_expected"]
            else None
        ),
        "fire_without_ready": metrics["fire_without_ready"],
        "fire_allowed_but_not_ready": metrics["fire_reference_available"],
        "movement_reference_agreement": round(
            metrics["movement_reference_agreement"] / decisions, 3
        ),
        "moving_rate": round(metrics["moving"] / decisions, 3),
        "progress_rate": round(metrics["progress_made"] / decisions, 3),
        "hold_decisions": metrics["hold_decisions"],
        "blocked_hold_rate": round(metrics["blocked_hold"] / decisions, 3),
        "strategy_interventions": metrics["strategy_interventions"],
        "unsafe_movement": round(metrics["unsafe_movement"] / decisions, 3),
        "unsafe_proposal_rate": round(metrics["unsafe_proposal"] / decisions, 3),
        "hold_rate": round(metrics["hold_rate"] / decisions, 3),
        "straight_aim_rate": round(metrics["straight_aim_rate"] / decisions, 3),
        "cumulative_guard_interventions": metrics["predicted_interventions"],
        "mean_guard_interventions": round(metrics["predicted_interventions"] / decisions, 3),
        "guard_intervention_kinds": dict(metrics["predicted_intervention_kinds"]),
        "mean_confidence": confidence,
        "mean_input_tokens": (
            round(statistics.fmean(metrics["tokens"]), 1) if metrics["tokens"] else None
        ),
        "mean_request_ms": (
            round(statistics.fmean(metrics["request_ms"]), 1)
            if metrics["request_ms"]
            else None
        ),
        "p95_request_ms": (
            round(sorted(metrics["request_ms"])[int((len(metrics["request_ms"]) - 1) * 0.95)], 1)
            if metrics["request_ms"]
            else None
        ),
        "cost_usd": round(metrics["cost_usd"], 6),
        "model_ids": sorted(metrics["model_ids"]),
    }
