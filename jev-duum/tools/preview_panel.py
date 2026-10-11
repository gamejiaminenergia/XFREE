"""Render the live Tk inspector offline so UI work costs $0.

This is a developer tool, not part of the pilot: it boots the pinned Duum
engine locally and answers every "Jev decision" with a constant fake client, so
the real ``Dashboard`` paints real pixels without a single network call.  Use it
to review, screenshot and iterate on the interface (``panel/`` / ``overlays/``)
without spending on the TypeSafe API.

    uv run --no-sync python tools/preview_panel.py --out artifacts/ui-audit

The engine is the sibling ``../duum`` checkout by default; pass
``--allow-any-commit`` when that checkout is not at the pinned commit (the UI
does not depend on engine behaviour, only on the snapshot fields).  Screenshots
need Pillow; without it the window still opens for a manual look.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("JEV_NO_LOG", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_duum.controller import JevDuumController  # noqa: E402
from jev_duum.fake import FakeJevClient  # noqa: E402
from jev_duum.integration import default_duum_checkout, load_duum  # noqa: E402
from jev_duum.panel import Dashboard, run_jev_window  # noqa: E402
from jev_duum.snapshot import SnapshotBuilder  # noqa: E402
from jev_duum.types import DuumControls  # noqa: E402
from jev_duum.wad import default_wad_path, resolve_wad  # noqa: E402


class _Stats:
    def __init__(self, *, completed: int = 42, replaced: int = 3):
        self.completed = completed
        self.replaced = replaced


class FakeWorker:
    """Only the two attributes ``Dashboard.update`` reads."""

    def __init__(self, *, busy: bool = False):
        self.busy = busy
        self.stats = _Stats()


def _grab(root, out: Path, name: str) -> bool:
    try:
        from PIL import ImageGrab
    except ImportError:
        return False
    for _ in range(4):  # let X11 composite the freshly mapped tab
        root.update_idletasks()
        root.update()
        time.sleep(0.06)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    path = out / f"{name}.png"
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
    print(f"saved {path}")
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="preview_panel", description=__doc__)
    parser.add_argument("--duum-path", type=Path, default=default_duum_checkout())
    parser.add_argument("--wad", type=Path, default=default_wad_path())
    parser.add_argument("--map", dest="map_name", default="E1M1")
    parser.add_argument("--prompt-version", default="v3w")
    parser.add_argument("--raw", action="store_true", help="Preview the uv-unassisted pilot.")
    parser.add_argument("--size", default="1600x900")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "ui-audit")
    parser.add_argument(
        "--allow-any-commit",
        action="store_true",
        help="Skip the Duum commit-pin check (the UI only needs snapshot fields).",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Open the real window and run the real 60 Hz loop with the model "
            "answered locally: full-speed review of the interface at no API cost."
        ),
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="With --watch, fill the screen instead of opening a window (F11 toggles).",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        width, height = (int(part) for part in args.size.lower().split("x"))
    except ValueError:
        parser.error("--size wants WIDTHxHEIGHT")

    try:
        wad = resolve_wad(args.wad)
        modules = load_duum(
            args.duum_path,
            frontend=True,
            require_pinned=not args.allow_any_commit,
        )
    except Exception as error:  # integration errors are already descriptive
        parser.error(str(error))

    if args.watch:
        # The real window, the real loop, the real panel: only the model is
        # answered locally.  This is the pass a screenshot cannot replace —
        # cadence, flicker and resizing only exist in a running window.
        controller = JevDuumController(
            client=FakeJevClient(),
            assisted=not args.raw,
            prompt_version=args.prompt_version,
            world_model=True,
            pilot="jev-raw" if args.raw else "jev-assisted",
        )
        run_jev_window(
            modules,
            str(wad.path),
            controller,
            map_name=args.map_name,
            fullscreen=args.fullscreen,
        )
        return 0

    modules.desktop.use_clock(None)
    modules.desktop.set_keys(0)
    modules.desktop.mount(str(wad.path))
    app = modules.engine.Duum()
    window = modules.frontend.Window(
        app, width=320, height=200, scale=2, title="Duum · UI preview (offline)"
    )
    app.build(window.cv)
    if app.err:
        parser.error(f"Duum could not start: {app.err}")
    if app.level != args.map_name:
        app.load_level(args.map_name)
    for _ in range(3):  # a few offline frames so the game canvas has pixels
        window._frame_once()

    controller = JevDuumController(
        client=FakeJevClient(),
        assisted=not args.raw,
        prompt_version=args.prompt_version,
        world_model=True,
        pilot="jev-raw" if args.raw else "jev-assisted",
    )
    builder = SnapshotBuilder(app, modules.engine)
    snapshot = builder.build(0)
    decision = controller.decide(snapshot).with_application_tick(1)

    args.out.mkdir(parents=True, exist_ok=True)
    panel = Dashboard(modules.frontend.tkinter, window, fullscreen=False)
    root = window.root
    stage_h = max(height, 1000)
    root.geometry(f"{width}x{stage_h}+0+0")
    root.update()
    panel._relayout(width, stage_h)

    def show(snapshot_now, decision_now, *, stale=0, error=None, log_stats=None, name=None):
        panel.update(
            pilot="jev-raw" if args.raw else "jev-assisted",
            snapshot=snapshot_now,
            decision=decision_now,
            controls=(
                decision_now.applied_controls if decision_now is not None else DuumControls()
            ),
            worker=FakeWorker(),
            stale=stale,
            error=error,
            log_stats=log_stats,
        )
        return _grab(root, args.out, name) if name else False

    # The window has no tabs: one screenshot per state the panel can be in.
    captured = show(snapshot, decision, log_stats={"sent": 42, "dropped": 0},
                    name="01-en-vivo")
    captured = show(snapshot, None, name="02-esperando") or captured

    low = replace(
        snapshot,
        player=replace(snapshot.player, health=22, armor=30, ammo=6),
        episode=replace(snapshot.episode, damage_received=140, kills=5,
                        stuck_ticks=18, projectiles=3),
    )
    captured = show(low, decision, log_stats={"sent": 42, "dropped": 0},
                    name="03-salud-critica") or captured
    captured = show(snapshot, decision, stale=17, name="04-obsoleta") or captured
    captured = show(
        snapshot, decision, error="ReadTimeout: api.typesafe.ai did not answer in 20s",
        name="05-sin-modelo",
    ) or captured

    if not captured:
        print(
            "Pillow is not installed; showing the window for a manual look. "
            "Install it (dev only) to save PNGs, or use the system Python.",
            file=sys.stderr,
        )
        root.after(1000, window._close)
        root.mainloop()
    else:
        window._close()
    print("offline preview: no network, model answered by a local fake client.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
