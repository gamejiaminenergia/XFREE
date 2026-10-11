"""Paired deterministic pilot experiments for tuning the Duum controller."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .benchmark import run_headless
from .controller import JevDuumController
from .env import load_local_env
from .integration import default_duum_checkout, load_duum
from .wad import default_wad_path, resolve_wad

load_local_env()


def _score(summary, tick_budget):
    episode = summary["final"]["episode"]
    player = summary["final"]["player"]
    time_score = (
        max(0.0, tick_budget / 60 - episode["game_time"]) * 20
        if episode["finished"]
        else episode["game_time"] * 10
    )
    return (
        (100_000 if episode["finished"] else 0)
        + time_score
        + episode["kills"] * 250
        + episode["items"] * 40
        + episode["unique_sectors"] * 100
        + player["health"] * 2
        - summary.get("assistance_interventions", 0) * 0.1
    )


def run_evaluation(
    modules,
    wad,
    model,
    *,
    map_name="E1M1",
    ticks=3600,
    width=96,
    height=64,
    endpoint=None,
):
    raw = JevDuumController(model, endpoint=endpoint, assisted=False, mission="clear")
    assisted = JevDuumController(client=raw.client, assisted=True, mission="clear")
    assisted.metadata = dict(raw.metadata)
    assisted.metadata["policy"] = raw.metadata["policy"] + "; deterministic assistance enabled"
    definitions = [
        ("scripted-12hz", "scripted", 12, None, 0),
        ("random-12hz", "random", 12, None, 101),
        ("heuristic-12hz", "heuristic", 12, None, 0),
        ("jev-raw-12hz", "jev-raw", 12, raw, 0),
        ("jev-assisted-5hz", "jev-assisted", 5, assisted, 0),
        ("jev-assisted-10hz", "jev-assisted", 10, assisted, 0),
        ("jev-assisted-12hz", "jev-assisted", 12, assisted, 0),
        ("jev-assisted-20hz", "jev-assisted", 20, assisted, 0),
    ]
    experiments = []
    started = time.perf_counter()
    for name, pilot, rate, controller, seed in definitions:
        result = run_headless(
            modules,
            wad,
            pilot=pilot,
            map_name=map_name,
            ticks=ticks,
            width=width,
            height=height,
            decision_rate=rate,
            seed=seed,
            controller=controller,
        )
        episode = result["final"]["episode"]
        player = result["final"]["player"]
        experiments.append(
            {
                "name": name,
                "pilot": pilot,
                "decision_rate": rate,
                "score": _score(result, ticks),
                "completed": episode["finished"],
                "dead": episode["dead"],
                "simulated_seconds": episode["game_time"],
                "health": player["health"],
                "kills": episode["kills"],
                "items": episode["items"],
                "unique_sectors": episode["unique_sectors"],
                "final_stuck_ticks": episode["stuck_ticks"],
                "decisions": result["complete_decisions"],
                "prediction_calls": result["prediction_calls"],
                "mean_decision_ms": result["mean_decision_ms"],
                "p95_decision_ms": result["p95_decision_ms"],
                "assistance_interventions": result["assistance_interventions"],
                "cost_usd": result.get("cost_usd"),
                "final_engine_hash": result["final_engine_hash"],
            }
        )
    assisted_rows = [row for row in experiments if row["pilot"] == "jev-assisted"]
    recommended = max(assisted_rows, key=lambda row: (row["score"], -row["decision_rate"]))
    return {
        "schema": "jev-duum-evaluation-v1",
        "network": "online: api.typesafe.ai",
        "map": map_name,
        "tick_budget": ticks,
        "duum": {"commit": modules.commit, "source": modules.source},
        "wad": wad.to_dict(),
        "model": raw.metadata,
        "wall_seconds": time.perf_counter() - started,
        "total_cost_usd": sum(
            row["cost_usd"] or 0.0 for row in experiments
        ),
        "experiments": experiments,
        "recommended_assisted_rate": recommended["decision_rate"],
        "recommended_experiment": recommended["name"],
        "scoring": (
            "completion dominates; completed runs reward time remaining, incomplete runs "
            "reward survival time, then kills, items, unique sectors, and health; assistance "
            "has a small transparency cost"
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="jev-duum-eval",
        description="Run eight paired Duum pilot experiments under Jev.",
    )
    parser.add_argument("--wad", type=Path, default=default_wad_path())
    parser.add_argument("--model", default="jev-latest")
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--duum-path", type=Path, default=default_duum_checkout())
    parser.add_argument("--map", dest="map_name", default="E1M1")
    parser.add_argument("--ticks", type=int, default=3600)
    parser.add_argument("--output", type=Path, default=Path("artifacts/duum-evaluation.json"))
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.ticks < 60:
        parser.error("--ticks must be at least 60")
    try:
        wad = resolve_wad(args.wad)
        modules = load_duum(args.duum_path)
        report = run_evaluation(
            modules,
            wad,
            args.model,
            map_name=args.map_name,
            ticks=args.ticks,
            endpoint=args.endpoint,
        )
    except (FileNotFoundError, RuntimeError, ValueError, FloatingPointError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
