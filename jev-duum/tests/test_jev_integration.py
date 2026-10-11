import math
import os
from pathlib import Path

import pytest

from jev_duum.actions import ensure_usable_weapon
from jev_duum.integration import DUUM_ACTION_COMPAT, DUUM_COMMIT, DuumRuntime, load_duum
from jev_duum.types import DuumControls

ROOT = Path(__file__).parents[1]
DUUM_ROOT = Path(os.environ.get("JEV_DUUM_PATH", ROOT.parent / "duum"))
WAD = ROOT / "freedoom1.wad"
if not WAD.is_file():
    WAD = ROOT.parent / "laya-duum" / "freedoom1.wad"
HAS_FIXTURE = (DUUM_ROOT / "duum" / "engine.py").is_file() and WAD.is_file()

pytestmark = pytest.mark.skipif(
    not HAS_FIXTURE,
    reason="needs the pinned sibling Duum checkout and a local freedoom1.wad",
)


def make_runtime():
    modules = load_duum(DUUM_ROOT)
    return DuumRuntime(modules, WAD, "E1M1", 96, 64)


def test_e1m2_blue_key_switch_compatibility_is_explicit_and_one_shot():
    modules = load_duum(DUUM_ROOT)
    assert DUUM_ACTION_COMPAT[23] == (3, 0)
    assert modules.engine.ACT[23] == (3, 0)
    assert 23 in modules.engine.ONE_SHOT
    with DuumRuntime(modules, WAD, "E1M2", 96, 64) as runtime:
        assert runtime.app.lvl.sectors[45][0] == 304
        runtime.app.activate(34, 1)
        assert runtime.app.lvl.lines[34][3] == 0
        assert {mover.si for mover in runtime.app.movers} >= {45, 201, 210}


def test_pinned_engine_advances_exactly_sixty_ticks_per_second():
    modules = load_duum(DUUM_ROOT)
    assert modules.commit == DUUM_COMMIT
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        for _ in range(60):
            state, mask, _ = runtime.step(DuumControls())
    assert state.tick == 60
    assert state.game_time == pytest.approx(1.0)
    assert mask == 0


def test_real_engine_turn_and_strafe_directions():
    with make_runtime() as runtime:
        initial_angle = runtime.app.pa
        runtime.step(DuumControls(aim="left"))
        assert runtime.app.pa > initial_angle
        runtime.app.pa = initial_angle
        runtime.step(DuumControls(aim="right"))
        assert runtime.app.pa < initial_angle

        runtime.app.pa = math.pi / 2
        start_x = runtime.app.px
        runtime.step(DuumControls("strafe_left"))
        assert runtime.app.px < start_x


def test_real_engine_forward_and_fire_controls():
    with make_runtime() as runtime:
        start = (runtime.app.px, runtime.app.py)
        for _ in range(4):
            runtime.step(DuumControls("forward"))
        assert (runtime.app.px, runtime.app.py) != start

        ammo = tuple(runtime.app.ammo)
        runtime.step(DuumControls(interaction="fire"))
        assert tuple(runtime.app.ammo) != ammo


def test_real_engine_restores_pistol_after_ammo_is_collected_on_fists():
    with make_runtime() as runtime:
        runtime.app.weapon = 1
        runtime.app.ammo[1] = 10
        assert ensure_usable_weapon(runtime.app, runtime.modules.engine)
        assert runtime.app.weapon == 2


def test_use_is_a_rising_edge_in_the_real_engine(monkeypatch):
    with make_runtime() as runtime:
        calls = []
        monkeypatch.setattr(runtime.app, "do_use", lambda: calls.append(runtime.ticks))
        runtime.step(DuumControls(interaction="use"))
        runtime.step(DuumControls(interaction="use"))
        runtime.step(DuumControls())
        runtime.step(DuumControls(interaction="use"))
    assert len(calls) == 2


def _deterministic_hashes():
    hashes = []
    with make_runtime() as runtime:
        controls = DuumControls("forward", "right", "fire")
        for tick in range(180):
            state, _, _ = runtime.step(controls)
            if (tick + 1) % 60 == 0:
                hashes.append(state.state_hash())
    return hashes


def test_identical_inputs_produce_identical_authoritative_checkpoints():
    assert _deterministic_hashes() == _deterministic_hashes()
