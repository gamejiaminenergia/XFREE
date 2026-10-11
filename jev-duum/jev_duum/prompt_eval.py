"""Offline paired comparison of prompt versions over recorded snapshots.

``jev-duum --record episode.json --record-snapshots`` stores the canonical
snapshot behind every decision.  This harness re-asks each prompt version over
those exact snapshots (no engine, no gameplay) and reports how close the model
gets to the deterministic reference, how many guard interventions its proposal
would trigger, and what it costs.  It is the offline half of the prompt A/B.
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import time
from pathlib import Path

from .assistance import apply_assistance, reference_controls, reference_fire_allowed
from .controller import argmax_controls, parse_answers
from .env import load_local_env
from .geometry import progress_scores
from .jev_client import DEFAULT_MODEL, JevClient, JevError, input_cost_usd
from .prompts import PROMPT_VERSIONS, build_questions, build_state, snapshot_from_dict
from .strategy import StrategyTracker, compute_strategy, enforce_strategy, guide_bearing

try:  # optional: only the *w prompt versions use the schematic world model
    from .world_model import build_world_model
except Exception:  # pragma: no cover - defensive import
    build_world_model = None

load_local_env()

SCHEMA = "jev-duum-prompt-eval-v1"


def load_corpus(path) -> list[dict]:
    """Read snapshots from a recording (v1/v2) or a bare list of snapshots."""

    path = Path(path).expanduser().resolve()
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        items = data.get("snapshots")
        if items is None:
            raise ValueError(f"{path} has no `snapshots` array; re-record with --record-snapshots")
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"Unsupported corpus in {path}")
    snapshots = []
    for item in items:
        payload = item.get("snapshot") if isinstance(item, dict) and "snapshot" in item else item
        if not isinstance(payload, dict) or "player" not in payload:
            raise ValueError(f"Malformed snapshot entry in {path}")
        snapshots.append(snapshot_from_dict(payload))
    return snapshots


def _reference(snapshot) -> dict:
    neutral = reference_controls(snapshot)
    ready = bool(snapshot.player.weapon_ready and snapshot.player.ammo > 0)
    progress = progress_scores(guide_bearing(snapshot))
    safe = {option.name for option in snapshot.movement_options if option.safe}
    return {
        "movement": neutral.movement,
        "aim": neutral.aim,
        "fire_allowed": reference_fire_allowed(snapshot),
        "fire_ready": ready,
        "fire_expected": reference_fire_allowed(snapshot) and ready,
        "progress": progress,
        "progress_available": any(
            progress.get(name, -1.0) > 0.05 for name in safe
        ),
        "unsafe": {
            option.name: not option.safe for option in snapshot.movement_options
        },
    }


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


def _decide(
    client,
    snapshot,
    version,
    *,
    strategy=None,
    world_model=None,
    reverse_order=False,
) -> dict:
    state, _ = build_state(snapshot, version, strategy, world_model)
    questions = build_questions(version, reverse_order=reverse_order)
    started = time.perf_counter()
    response = client.ask(
        state,
        questions,
        context={
            "prompt_version": version,
            "stage": "prompt-eval" + ("-reversed" if reverse_order else ""),
        },
    )
    request_ms = (time.perf_counter() - started) * 1000
    probabilities, confidence = parse_answers(response)
    controls = argmax_controls(probabilities)
    usage = response.get("usage") or {}
    try:
        tokens = int(usage.get("input_tokens") or 0)
    except (TypeError, ValueError):
        tokens = 0
    return {
        "version": version,
        "tick": snapshot.tick,
        "probabilities": probabilities,
        "confidence": confidence,
        "controls": {
            "movement": controls.movement,
            "aim": controls.aim,
            "interaction": controls.interaction,
        },
        "tokens": tokens,
        "cost_usd": input_cost_usd(tokens),
        "request_ms": request_ms,
        "model_id": str(response.get("model") or ""),
    }


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


def evaluate_corpus(
    client,
    snapshots,
    versions,
    *,
    order_probe=False,
    decisions_path=None,
    progress=None,
) -> dict:
    """Ask every version over every snapshot and aggregate the paired metrics."""

    if not snapshots:
        raise ValueError("the corpus has no snapshots")
    references = [_reference(snapshot) for snapshot in snapshots]
    metrics = {version: _empty_metrics(version) for version in versions}
    order_hits = {version: collections.Counter() for version in versions}
    order_calls = {version: 0 for version in versions}
    trackers = {version: StrategyTracker() for version in versions}
    streaks = {version: 0 for version in versions}
    streaks_seen = {version: [] for version in versions}
    rows = []
    for index, (snapshot, reference) in enumerate(zip(snapshots, references)):
        for version in versions:
            tracker = trackers[version]
            if version in ("v3", "v3w"):
                strategy = compute_strategy(snapshot, tracker)
            else:
                strategy = None
            world_model = None
            if version.endswith("w") and build_world_model is not None:
                try:
                    world_model = build_world_model(snapshot)
                except Exception:  # pragma: no cover - adapter is already fail-soft
                    world_model = None
            try:
                result = _decide(
                    client,
                    snapshot,
                    version,
                    strategy=strategy,
                    world_model=world_model,
                )
            except (JevError, ValueError, OSError) as error:
                metrics[version]["errors"] += 1
                rows.append({"tick": snapshot.tick, "version": version, "error": str(error)})
                continue
            proposed = argmax_controls(result["probabilities"])
            applied, events = apply_assistance(
                snapshot,
                proposed,
            )
            strategy_events = ()
            if strategy is not None:
                applied, strategy_events = enforce_strategy(snapshot, strategy, applied)
            tracker.observe(snapshot, applied)
            if applied.movement == "hold":
                streaks[version] += 1
            else:
                streaks_seen[version].append(streaks[version])
                streaks[version] = 0
            metrics[version]["predicted_interventions"] += len(events)
            metrics[version]["predicted_intervention_kinds"].update(
                event.kind for event in events
            )
            row = {
                **result,
                "reference": reference,
                "applied": {
                    "movement": applied.movement,
                    "aim": applied.aim,
                    "interaction": applied.interaction,
                },
                "strategy": strategy.to_dict() if strategy is not None else None,
                "guard_interventions": [event.kind for event in events],
                "strategy_interventions": [event.kind for event in strategy_events],
            }
            _score_decision(metrics[version], reference, row)
            if order_probe:
                try:
                    reversed_result = _decide(
                        client,
                        snapshot,
                        version,
                        strategy=strategy,
                        world_model=world_model,
                        reverse_order=True,
                    )
                except (JevError, ValueError, OSError):
                    metrics[version]["errors"] += 1
                else:
                    order_calls[version] += 1
                    for name in ("movement", "aim", "interaction"):
                        if result["controls"][name] == reversed_result["controls"][name]:
                            order_hits[version][name] += 1
                    row["reversed_controls"] = reversed_result["controls"]
            rows.append(row)
        if progress is not None:
            progress(index + 1, len(snapshots))
    report = {
        "schema": SCHEMA,
        "snapshots": len(snapshots),
        "order_probe": bool(order_probe),
        "total_cost_usd": round(sum(item["cost_usd"] for item in metrics.values()), 6),
        "versions": {
            version: _finalize(metrics[version]) for version in versions
        },
    }
    for version in versions:
        streaks_seen[version].append(streaks[version])
        report["versions"][version]["max_hold_streak"] = max(streaks_seen[version] or [0])
        report["versions"][version]["mean_hold_streak"] = round(
            statistics.fmean(streaks_seen[version]) if streaks_seen[version] else 0.0, 3
        )
    if order_probe:
        for version in versions:
            calls = order_calls[version] or 1
            report["versions"][version]["order_agreement"] = {
                name: round(order_hits[version][name] / calls, 3)
                for name in ("movement", "aim", "interaction")
            }
    if decisions_path is not None:
        path = Path(decisions_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        report["decisions_path"] = str(path)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="jev-duum-prompt-eval",
        description="Compare Jev prompt versions over recorded Duum snapshots.",
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--versions", default=",".join(PROMPT_VERSIONS))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--order-probe", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--decisions", type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    versions = tuple(item.strip() for item in args.versions.split(",") if item.strip())
    for version in versions:
        if version not in PROMPT_VERSIONS:
            parser.error(f"unknown prompt version: {version}")
    try:
        snapshots = load_corpus(args.corpus)
        if args.limit is not None:
            snapshots = snapshots[: args.limit]
        client = JevClient(model=args.model, endpoint=args.endpoint)
    except (OSError, ValueError, JevError) as error:
        parser.error(str(error))

    step = max(1, len(snapshots) // 20)

    def progress(done, total):
        if done % step == 0 or done == total:
            print(f"[prompt-eval] {done}/{total} snapshots", file=sys.stderr)

    try:
        report = evaluate_corpus(
            client,
            snapshots,
            versions,
            order_probe=args.order_probe,
            decisions_path=args.decisions,
            progress=progress,
        )
    except (ValueError, JevError) as error:
        parser.error(str(error))
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
