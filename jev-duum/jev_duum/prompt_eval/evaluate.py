"""The paired run: re-ask every prompt version over the same snapshots and
report agreement, guard interventions and cost."""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import time
from pathlib import Path

from ..assistance import apply_assistance
from ..controller import argmax_controls, parse_answers
from ..env import load_local_env
from ..jev_client import DEFAULT_MODEL, JevClient, JevError, input_cost_usd
from ..prompts import PROMPT_VERSIONS, build_questions, build_state
from ..strategy import StrategyTracker, compute_strategy, enforce_strategy
from .corpus import SCHEMA, _reference, load_corpus
from .metrics import _empty_metrics, _finalize, _score_decision

try:  # optional: only the *w prompt versions use the schematic world model
    from ..world_model import build_world_model
except Exception:  # pragma: no cover - defensive import
    build_world_model = None

load_local_env()


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
