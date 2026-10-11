"""Render the live Tk inspector offline so UI work costs $0.

This is a developer tool, not part of the pilot: it boots the pinned Duum
engine locally and answers every "Jev decision" with a constant fake client, so
the real ``Dashboard`` paints real pixels without a single network call.  Use it
to review, screenshot and iterate on the interface (``panel.py`` / ``overlays``)
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
from jev_duum.integration import load_duum  # noqa: E402
from jev_duum.panel import Dashboard  # noqa: E402
from jev_duum.snapshot import SnapshotBuilder  # noqa: E402
from jev_duum.wad import default_wad_path, resolve_wad  # noqa: E402


class FakeJevClient:
    """Stand-in for ``JevClient`` that never touches the network."""

    def __init__(self, *, model: str = "jev-preview-1.0", tokens: int = 1180):
        self.endpoint = "fake://typesafe"
        self.model = model
        self.tokens = tokens
        self.calls = 0
        self.answers = {
            "movement": {
                "type": "choice",
                "choice": "strafe_left",
                "confidence": 0.6,
                "probabilities": {
                    "forward": 0.1,
                    "back": 0.1,
                    "strafe_left": 0.6,
                    "strafe_right": 0.1,
                    "hold": 0.1,
                },
            },
            "aim": {
                "type": "choice",
                "choice": "right",
                "confidence": 0.7,
                "probabilities": {"left": 0.1, "straight": 0.2, "right": 0.7},
            },
            "interaction": {
                "type": "choice",
                "choice": "fire",
                "confidence": 0.8,
                "probabilities": {"fire": 0.8, "use": 0.1, "neither": 0.1},
            },
        }

    def ask(self, state, questions, *, model=None, context=None):
        self.calls += 1
        return {
            "model": self.model,
            "answers": {name: self.answers[name] for name in questions},
            "usage": {"input_tokens": self.tokens, "output_tokens": 44},
        }


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
    parser.add_argument("--duum-path", type=Path, default=ROOT.parent / "duum")
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
    panel.update(
        pilot="jev-raw" if args.raw else "jev-assisted",
        snapshot=snapshot,
        decision=decision,
        controls=decision.applied_controls,
        worker=FakeWorker(),
        stale=0,
        error=None,
        log_stats={"sent": 42, "dropped": 0},
    )

    args.out.mkdir(parents=True, exist_ok=True)
    shots = [
        ("decision", "01-decision"),
        ("response", "02-response"),
        ("request", "03-request"),
        ("world", "04-world"),
        ("history", "05-history"),
    ]
    captured = False
    for tab, name in shots:
        panel._select_tab(tab)
        panel.scroll.canvas.yview_moveto(0)
        captured = _grab(root, args.out, name) or captured

    low = replace(
        snapshot,
        player=replace(snapshot.player, health=22, armor=30, ammo=6),
        episode=replace(snapshot.episode, damage_received=140, kills=5),
    )
    panel._select_tab("decision")
    panel.update(
        pilot="jev-assisted", snapshot=low, decision=decision,
        controls=decision.applied_controls, worker=FakeWorker(), stale=0,
        error=None, log_stats=None,
    )
    captured = _grab(root, args.out, "06-critical") or captured

    panel.update(
        pilot="jev-assisted", snapshot=snapshot, decision=decision,
        controls=decision.applied_controls, worker=FakeWorker(), stale=17,
        error=None, log_stats=None,
    )
    captured = _grab(root, args.out, "07-stale") or captured

    panel.update(
        pilot="jev-assisted", snapshot=snapshot, decision=decision,
        controls=decision.applied_controls, worker=FakeWorker(), stale=0,
        error="ReadTimeout: api.typesafe.ai did not answer in 20s", log_stats=None,
    )
    captured = _grab(root, args.out, "08-error") or captured

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
