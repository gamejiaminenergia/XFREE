"""Load pinned Duum and drive it only through its existing host contracts."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .actions import SyntheticInput
from .checkpoint import checkpoint
from .scheduler import FixedClock

DUUM_COMMIT = "87f4827f88b005515d92e6ed3c3756641ad2b0d0"

# Freedoom E1M2 uses Doom linedef special 23 to lower the blue-key platform,
# but the pinned Duum E1 action table omits it. Keep this compatibility
# addition at the adapter boundary rather than modifying Duum's source.
# Kind 3 is Duum's existing "floor to lowest neighbor" action; the switch is
# activated by use and fires once.
DUUM_ACTION_COMPAT = {23: (3, 0)}


class DuumIntegrationError(RuntimeError):
    pass


def default_duum_checkout() -> Path | None:
    """The pinned Duum checkout, resolved the same way the wrapper does.

    ``./main.sh`` either uses the sibling ``duum/`` (when it is already at the
    pin) or a ``duum-<short-sha>`` worktree next to the repository.  Tools that
    must work with no arguments look for both, so "just run it" does not need a
    ``--duum-path``.
    """

    here = Path(__file__).resolve()
    inside = here.parents[2] / "duum"  # <repo>/duum
    beside = here.parents[3] / f"duum-{DUUM_COMMIT[:7]}"  # <parent>/duum-<sha7>
    if _checkout_commit(inside) == DUUM_COMMIT:
        return inside
    if (beside / "duum" / "engine.py").is_file():
        return beside
    return inside if (inside / "duum" / "engine.py").is_file() else None


@dataclass(frozen=True, slots=True)
class DuumModules:
    package: object
    engine: object
    desktop: object
    canvas_type: type
    frontend: object | None
    commit: str
    source: str


def _checkout_commit(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _installed_commit() -> str | None:
    try:
        direct = importlib.metadata.distribution("duum").read_text("direct_url.json")
        if direct:
            return json.loads(direct).get("vcs_info", {}).get("commit_id")
    except (importlib.metadata.PackageNotFoundError, ValueError, json.JSONDecodeError):
        pass
    return None


def load_duum(checkout=None, *, require_pinned=True, frontend=False) -> DuumModules:
    source = "installed pinned dependency"
    commit = None
    if checkout is not None:
        root = Path(checkout).expanduser().resolve()
        if not (root / "duum" / "engine.py").is_file():
            raise DuumIntegrationError(f"Not a Duum source checkout: {root}")
        commit = _checkout_commit(root)
        source = str(root)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
    try:
        package = importlib.import_module("duum")
        engine = importlib.import_module("duum.engine")
        desktop = importlib.import_module("duum.hosts.desktop")
        canvas_type = importlib.import_module("duum.raster").Canvas
        frontend_module = importlib.import_module("duum.frontends.tkwin") if frontend else None
    except ImportError as error:
        if frontend and error.name == "_tkinter":
            raise DuumIntegrationError(
                "The manual pilot needs a Python build with Tk support. "
                "Use a Tk-enabled Python 3.11-3.13 (for this Homebrew Python, run "
                "`brew install python-tk@3.13`), or use the scripted headless pilot."
            ) from error
        raise DuumIntegrationError(
            "Duum is not available. Run `uv sync` or pass "
            "--duum-path /path/to/the/pinned/duum/checkout."
        ) from error
    commit = commit or _installed_commit()
    if require_pinned and commit != DUUM_COMMIT:
        found = commit or "unknown/unrecorded"
        raise DuumIntegrationError(
            f"Duum commit mismatch: expected {DUUM_COMMIT}, found {found}. "
            "The demo never follows a moving branch silently."
        )
    for special, action in DUUM_ACTION_COMPAT.items():
        engine.ACT.setdefault(special, action)
        if special not in engine.ONE_SHOT:
            engine.ONE_SHOT += (special,)
    return DuumModules(package, engine, desktop, canvas_type, frontend_module, commit or "", source)


class DuumRuntime:
    """A synchronous headless runtime with one authoritative fixed tick."""

    def __init__(self, modules: DuumModules, wad, map_name="E1M1", width=160, height=100):
        self.modules = modules
        self.closed = False
        self.clock = FixedClock()
        modules.desktop.use_clock(self.clock)
        modules.desktop.set_keys(0)
        modules.desktop.mount(str(wad))
        self.canvas = modules.canvas_type(width, height)
        self.app = modules.engine.Duum()
        self.app.build(self.canvas)
        if self.app.err:
            self.close()
            raise DuumIntegrationError(f"Duum could not start: {self.app.err}")
        if map_name and self.app.level != map_name:
            self.app.load_level(map_name)
        # Duum's first ordinary tick uses a documented 0.008 s bootstrap.
        # Setting the sampled host tick here makes every adapter step exactly
        # one authoritative 1/60-second interval from the start.
        self.app.last_ticks = self.clock.tick
        self.input = SyntheticInput(modules.desktop)
        self.ticks = 0

    def step(self, controls, *, draw=False):
        if self.closed:
            raise DuumIntegrationError("Cannot advance a closed Duum runtime")
        mask = self.input.apply(controls)
        self.clock.advance()
        repaint = bool(self.app.tick())
        self.ticks += 1
        if draw and repaint:
            self.app.draw(self.canvas)
        return checkpoint(self.app, self.ticks), mask, repaint

    def close(self) -> None:
        if self.closed:
            return
        try:
            if hasattr(self, "input"):
                self.input.release()
            else:
                self.modules.desktop.set_keys(0)
            if hasattr(self, "app"):
                self.app.closed()
        finally:
            self.modules.desktop.use_clock(None)
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
