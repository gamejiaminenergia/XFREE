"""Run pinned Duum under manual, baseline, replay, or remote Jev control."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

from .benchmark import run_headless
from .env import load_local_env
from .integration import DuumIntegrationError, default_duum_checkout, load_duum
from .panel import run_jev_window
from .prompts import PROMPT_VERSIONS
from .recording import EpisodeRecorder
from .replay import replay_recording
from .wad import default_wad_path, resolve_wad

load_local_env()

PILOTS = ("manual", "scripted", "random", "heuristic", "hunter", "jev", "jev-assisted")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jev-duum",
        description="Play Duum manually or under remote semantic Jev control.",
    )
    parser.add_argument(
        "--wad",
        type=Path,
        default=default_wad_path(),
        help="Local IWAD path (default: bundled ./freedoom1.wad)",
    )
    parser.add_argument("--map", dest="map_name", default="E1M1")
    parser.add_argument(
        "--duum-path",
        type=Path,
        default=default_duum_checkout(),
        help="Pinned Duum source checkout (defaults to sibling ../duum when present)",
    )
    parser.add_argument("--pilot", choices=PILOTS, default="manual")
    parser.add_argument(
        "--model",
        default="jev-latest",
        help="TypeSafe System One model id (default: jev-latest)",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="Override the System One endpoint (default: TYPESAFE_URL or the public API)",
    )
    parser.add_argument(
        "--prompt-version",
        choices=PROMPT_VERSIONS,
        default=None,
        help="Jev request shape (default: JEV_PROMPT_VERSION or the packaged default)",
    )
    parser.add_argument(
        "--decision-rate",
        type=float,
        default=10.0,
        help="Model decisions per simulated second (default: tuned 10 Hz)",
    )
    parser.add_argument("--max-stale-ticks", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--ticks", type=int, default=3600)
    parser.add_argument("--checkpoint-every", type=int, default=60)
    parser.add_argument("--record", type=Path)
    parser.add_argument(
        "--record-snapshots",
        action="store_true",
        help="Also store each decision's canonical snapshot and request state for offline prompt A/B",
    )
    parser.add_argument(
        "--no-world-model",
        action="store_true",
        help="Do not attach the schematic world model (map/sense.py + heuristics.py) to the request",
    )
    parser.add_argument(
        "--mission",
        choices=("clear", "advance"),
        default="clear",
        help=(
            "Code-owned mission: 'clear' hunts every monster with the adversary model "
            "(default), 'advance' keeps the original reach-the-exit plan"
        ),
    )
    parser.add_argument(
        "--damage-log",
        type=Path,
        default=None,
        help="Write one JSON line per damage event with its source (headless only)",
    )
    parser.add_argument("--replay", type=Path)
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Start in a normal window instead of filling the screen (F11 toggles).",
    )
    parser.add_argument(
        "--log-calls",
        action="store_true",
        help=(
            "Force the passive audit log on: POST every Jev request/response to the "
            "local API (:3000), overriding JEV_NO_LOG. Failures are silent."
        ),
    )
    parser.add_argument("--size", default="320x200")
    parser.add_argument("--scale", type=int, default=2)
    return parser


def _dimensions(parser, value):
    try:
        width, height = (int(part) for part in value.lower().split("x"))
    except ValueError:
        parser.error("--size wants WIDTHxHEIGHT, for example 320x200")
    if width < 64 or height < 40:
        parser.error("--size is too small")
    return width, height


def _validate(parser, args):
    if args.ticks < 1 or args.checkpoint_every < 1:
        parser.error("--ticks and --checkpoint-every must be positive")
    if args.scale < 1 or args.max_stale_ticks < 0:
        parser.error("--scale must be positive and --max-stale-ticks non-negative")
    if not math.isfinite(args.decision_rate) or not 5 <= args.decision_rate <= 20:
        parser.error("--decision-rate must be between 5 and 20")
    if args.replay:
        if not args.headless:
            parser.error("deterministic replay currently requires --headless")
        return
    if args.pilot == "manual" and args.headless:
        parser.error("the manual pilot needs Duum's normal window; omit --headless")
    if args.pilot in ("scripted", "random", "heuristic", "hunter") and not args.headless:
        parser.error(f"the {args.pilot} baseline is headless; add --headless")
    if args.record and not args.headless:
        parser.error("exact recording currently requires synchronous --headless mode")
    if args.record_snapshots and not args.record:
        parser.error("--record-snapshots requires --record")


def _controller(parser, args):
    if args.pilot not in ("jev", "jev-assisted"):
        return None
    if getattr(args, "log_calls", False):
        # The client only enables the audit log when JEV_NO_LOG is unset; this
        # flag is the explicit opt-in for a session that inherits the variable.
        os.environ.pop("JEV_NO_LOG", None)
    print("Connecting to TypeSafe System One (Jev)...", file=sys.stderr)
    try:
        from .controller import JevDuumController

        return JevDuumController(
            args.model,
            endpoint=args.endpoint,
            assisted=args.pilot == "jev-assisted",
            prompt_version=args.prompt_version,
            world_model=not args.no_world_model,
            pilot=args.pilot,
            mission=args.mission,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        parser.error(str(error))


def play(argv=None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    _validate(parser, args)
    width, height = _dimensions(parser, args.size)
    needs_window = args.pilot == "manual" or (
        args.pilot in ("jev", "jev-assisted") and not args.headless
    )
    try:
        wad = resolve_wad(args.wad)
        modules = load_duum(args.duum_path, frontend=needs_window)
    except (FileNotFoundError, ValueError, DuumIntegrationError) as error:
        parser.error(str(error))
    controller = _controller(parser, args)
    pilot_name = (
        "replay"
        if args.replay
        else "jev-raw"
        if args.pilot == "jev"
        else "jev-assisted"
        if controller
        else args.pilot
    )
    print(
        f"Duum {modules.commit[:12]} · {wad.filename} · "
        f"{'online: api.typesafe.ai' if controller else 'offline'} · pilot={pilot_name}",
        file=sys.stderr,
    )

    if args.replay:
        try:
            summary = replay_recording(modules, wad, args.replay, width=width, height=height)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        summary.update(
            pilot="replay",
            duum={"commit": modules.commit, "source": modules.source},
            wad=wad.to_dict(),
        )
    elif args.pilot == "manual":
        modules.desktop.mount(str(wad.path))
        app = modules.engine.Duum()
        started = time.perf_counter()
        frames = modules.frontend.play(
            app,
            level=args.map_name,
            width=width,
            height=height,
            scale=args.scale,
            title="Duum · manual pilot · offline",
        )
        summary = {
            "pilot": "manual",
            "mode": "interactive",
            "model_inference": False,
            "network": "offline",
            "duum": {"commit": modules.commit, "source": modules.source},
            "wad": wad.to_dict(),
            "map": app.level,
            "rendered_frames": frames,
            "wall_seconds": time.perf_counter() - started,
            "final": {
                "health": app.health,
                "armor": app.armor,
                "dead": app.dead,
                "finished": app.finish is not None,
            },
        }
    elif controller is not None and not args.headless:
        try:
            summary = run_jev_window(
                modules,
                wad.path,
                controller,
                map_name=args.map_name,
                width=width,
                height=height,
                scale=args.scale,
                decision_rate=args.decision_rate,
                max_stale_ticks=args.max_stale_ticks,
                fullscreen=not args.windowed,
            )
        except RuntimeError as error:
            parser.error(str(error))
        summary.update(
            duum={"commit": modules.commit, "source": modules.source},
            wad=wad.to_dict(),
            map=args.map_name,
            model=controller.metadata,
        )
    else:
        recorder = None
        if args.record:
            recorder = EpisodeRecorder(
                args.record,
                pilot=pilot_name,
                duum={"commit": modules.commit, "source": modules.source},
                wad=wad.to_dict(),
                map_name=args.map_name,
                tick_rate=60,
                decision_rate=args.decision_rate,
                model=controller.metadata if controller else None,
                network="online: api.typesafe.ai" if controller else "offline",
                capture_snapshots=args.record_snapshots,
            )
        try:
            summary = run_headless(
                modules,
                wad,
                pilot=pilot_name,
                map_name=args.map_name,
                ticks=args.ticks,
                width=width,
                height=height,
                decision_rate=args.decision_rate,
                seed=args.seed,
                controller=controller,
                recorder=recorder,
                checkpoint_every=args.checkpoint_every,
                damage_log=args.damage_log,
            )
        except (RuntimeError, ValueError, FloatingPointError) as error:
            parser.error(str(error))
        summary.update(
            duum={"commit": modules.commit, "source": modules.source},
            wad=wad.to_dict(),
            model=controller.metadata if controller else None,
            prompt_version=controller.prompt_version if controller else None,
        )
    print(json.dumps(summary, indent=2))
    return 1 if summary.get("model_error") else 0


def main(argv=None) -> int:
    return play(sys.argv[1:] if argv is None else argv)
