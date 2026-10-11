"""Run the pilot as a service: the engine in its own thread, HTTP in front.

    uv run --project jev-service jev-service --fake          # local model, 0 $
    uv run --project jev-service jev-service                 # the real Jev

The engine is never touched by a request: ``Session`` runs in a thread and
publishes into a ``Hub``; the web layer only ever reads the latest value.
"""

from __future__ import annotations

import argparse
import threading
from pathlib import Path

from jev_duum.controller import JevDuumController
from jev_duum.env import load_local_env
from jev_duum.integration import DuumRuntime, default_duum_checkout, load_duum
from jev_duum.session.core import Session
from jev_duum.wad import default_wad_path, resolve_wad

from .app import create_app
from .hub import Hub


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jev-service", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--duum-path", type=Path, default=default_duum_checkout())
    parser.add_argument("--wad", type=Path, default=default_wad_path())
    parser.add_argument("--map", dest="map_name", default="E1M1")
    parser.add_argument("--pilot", default="jev-assisted", choices=("jev", "jev-assisted"))
    parser.add_argument("--prompt-version", default=None)
    parser.add_argument("--decision-rate", type=float, default=10.0)
    parser.add_argument("--max-stale-ticks", type=int, default=30)
    parser.add_argument("--size", default="320x200", help="engine canvas, WIDTHxHEIGHT")
    parser.add_argument(
        "--fake", action="store_true",
        help="answer with a local deterministic model instead of calling Jev (no key, 0 $)",
    )
    parser.add_argument(
        "--control-token", default=None,
        help="require this value in x-control-token for POST /api/control",
    )
    return parser


def build_session(args, wad):
    if args.fake:
        from jev_duum.fake import FakeJevClient as FakeClient

        controller = JevDuumController(
            client=FakeClient(), model="fake-local",
            assisted=args.pilot == "jev-assisted",
            prompt_version=args.prompt_version, pilot=args.pilot,
        )
    else:
        controller = JevDuumController(
            assisted=args.pilot == "jev-assisted",
            prompt_version=args.prompt_version, pilot=args.pilot,
        )
    modules = load_duum(args.duum_path, frontend=False)
    width, height = (int(part) for part in args.size.lower().split("x"))
    runtime = DuumRuntime(modules, wad.path, args.map_name, width, height)
    session = Session(
        runtime, controller,
        decision_rate=args.decision_rate,
        max_stale_ticks=args.max_stale_ticks,
        pixels=True, frame_every=2, pilot=args.pilot,
    )
    return session, modules, controller, (width, height)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # Same credential path as the CLI: an exported TYPESAFE_API_KEY wins, and
    # otherwise jev-duum/.env is read (the file the wrapper writes).
    load_local_env()
    wad = resolve_wad(args.wad)
    session, modules, controller, (width, height) = build_session(args, wad)

    hub = Hub()
    hub.set_frame_size(width, height)
    stop = threading.Event()
    engine = threading.Thread(
        target=session.run,
        kwargs={"stop": stop, "realtime": True, "fps": 60.0, "on_frame": hub.publish},
        name="jev-engine",
        daemon=True,
    )
    engine.start()

    app = create_app(
        hub,
        session,
        meta={
            "pilot": args.pilot,
            "model": controller.model,
            "prompt_version": controller.prompt_version,
            "mission": controller.mission,
            "map": args.map_name,
            "engine_commit": modules.commit,
            "wad": wad.to_dict(),
            "fake_model": bool(args.fake),
            "resolution": f"{width}x{height}",
        },
        control_token=args.control_token,
    )
    print(f"jev-service on http://{args.host}:{args.port}  (pilot={args.pilot}, "
          f"model={'fake-local' if args.fake else controller.model})")
    try:
        import uvicorn

        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        stop.set()
        engine.join(timeout=5)
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
