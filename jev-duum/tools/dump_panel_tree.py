"""Dump the whole panel widget tree, deterministically, for A/B refactor checks.

Screenshots are not a safe equivalence gate: the tiles print ``decision_ms``,
which is wall-clock, so two runs legitimately differ by a pixel or two.  This
tool pins the clock and prints one JSON map of ``widget path -> (class, text,
canvas item count)`` per screen state, so a "no behaviour change" refactor can
be verified with ``cmp``:

    uv run --no-sync python tools/dump_panel_tree.py --out /tmp/old.json       # before
    uv run --no-sync python tools/dump_panel_tree.py --out /tmp/new.json       # after
    cmp /tmp/old.json /tmp/new.json

It boots the pinned Duum engine with a local fake model, exactly like
``preview_panel.py``: no network, no API cost.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("JEV_NO_LOG", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jev_duum.controller as controller_module  # noqa: E402

# The latency tiles are wall-clock; pin it so the dump is reproducible.
controller_module.time.perf_counter = lambda: 0.0

from jev_duum.controller import JevDuumController  # noqa: E402
from jev_duum.integration import default_duum_checkout, load_duum  # noqa: E402
from jev_duum.panel import Dashboard  # noqa: E402
from jev_duum.snapshot import SnapshotBuilder  # noqa: E402
from jev_duum.types import DuumControls  # noqa: E402
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
                "type": "choice", "choice": "strafe_left", "confidence": 0.6,
                "probabilities": {
                    "forward": 0.10, "forward_left": 0.02, "forward_right": 0.02,
                    "strafe_left": 0.60, "strafe_right": 0.08, "back_left": 0.01,
                    "back_right": 0.01, "back": 0.06, "hold": 0.10,
                },
            },
            "aim": {
                "type": "choice", "choice": "right", "confidence": 0.7,
                "probabilities": {"left": 0.1, "straight": 0.2, "right": 0.7},
            },
            "interaction": {
                "type": "choice", "choice": "fire", "confidence": 0.8,
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


def dump(widget) -> dict:
    """Every descendant, by position, with its text and canvas item count."""

    out: dict = {}

    def walk(node, path):
        try:
            text = node.cget("text")
        except Exception:
            text = None
        entry = [node.winfo_class(), text if isinstance(text, str) else None]
        if node.winfo_class() == "Canvas":
            entry.append(len(node.find_all()))
        out[path] = entry
        for index, child in enumerate(node.winfo_children()):
            walk(child, f"{path}/{index}")

    walk(widget, "")
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dump_panel_tree", description=__doc__)
    parser.add_argument("--duum-path", type=Path, default=default_duum_checkout())
    parser.add_argument("--wad", type=Path, default=default_wad_path())
    parser.add_argument("--map", dest="map_name", default="E1M1")
    parser.add_argument("--prompt-version", default="v3w")
    parser.add_argument("--size", default="1600x1000")
    parser.add_argument("--out", type=Path, help="Write here instead of stdout.")
    parser.add_argument("--allow-any-commit", action="store_true")
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
            args.duum_path, frontend=True, require_pinned=not args.allow_any_commit
        )
    except Exception as error:  # integration errors are already descriptive
        parser.error(str(error))

    modules.desktop.use_clock(None)
    modules.desktop.set_keys(0)
    modules.desktop.mount(str(wad.path))
    app = modules.engine.Duum()
    window = modules.frontend.Window(
        app, width=320, height=200, scale=2, title="Duum · panel dump (offline)"
    )
    app.build(window.cv)
    if app.err:
        parser.error(f"Duum could not start: {app.err}")
    if app.level != args.map_name:
        app.load_level(args.map_name)
    for _ in range(3):
        window._frame_once()

    controller = JevDuumController(
        client=FakeJevClient(), assisted=True, prompt_version=args.prompt_version,
        world_model=True, pilot="jev-assisted",
    )
    builder = SnapshotBuilder(app, modules.engine)
    snapshot = builder.build(0)
    decision = controller.decide(snapshot).with_application_tick(1)

    panel = Dashboard(modules.frontend.tkinter, window, fullscreen=False)
    root = window.root
    root.geometry(f"{width}x{height}+0+0")
    root.update()
    panel._relayout(width, height)

    states: dict = {}

    def show(name, snapshot_now, decision_now, *, stale=0, error=None, log_stats=None):
        panel.update(
            pilot="jev-assisted", snapshot=snapshot_now, decision=decision_now,
            controls=(
                decision_now.applied_controls if decision_now is not None
                else DuumControls()
            ),
            worker=FakeWorker(), stale=stale, error=error, log_stats=log_stats,
        )
        root.update()
        states[name] = dump(root)

    low = replace(
        snapshot,
        player=replace(snapshot.player, health=22, armor=30, ammo=6),
        episode=replace(snapshot.episode, damage_received=140, kills=5,
                        stuck_ticks=18, projectiles=3),
    )
    show("01-en-vivo", snapshot, decision, log_stats={"sent": 42, "dropped": 0})
    show("02-esperando", snapshot, None)
    show("03-salud-critica", low, decision, log_stats={"sent": 42, "dropped": 0})
    show("04-obsoleta", snapshot, decision, stale=17)
    show(
        "05-sin-modelo", snapshot, decision,
        error="ReadTimeout: api.typesafe.ai did not answer in 20s",
    )
    window._close()

    payload = json.dumps(states, ensure_ascii=False, sort_keys=True, indent=1)
    if args.out:
        args.out.write_text(payload + "\n")
        print(f"wrote {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
