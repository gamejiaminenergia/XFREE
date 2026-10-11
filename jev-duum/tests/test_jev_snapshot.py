import os
from pathlib import Path

import pytest

from jev_duum.integration import DuumRuntime, load_duum
from jev_duum.observation import build_observations
from jev_duum.snapshot import SnapshotBuilder
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


def test_canonical_snapshot_is_semantic_ranked_and_hashable():
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        builder = SnapshotBuilder(runtime.app, modules.engine)
        first = builder.build(0)
        second = builder.build(0)
    assert first == second
    assert first.state_hash() == second.state_hash()
    assert first.player.weapon_name == "pistol"
    assert first.episode.live_enemies > 0
    assert first.navigation is not None
    assert first.navigation.reachable
    assert first.navigation.objective == "exit"
    assert first.navigation.route_length > 0
    assert len(first.visible_enemies) <= 3
    assert list(first.visible_enemies) == sorted(
        first.visible_enemies, key=lambda enemy: (-enemy.threat, enemy.id)
    )


def test_all_question_observations_identify_one_snapshot():
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        snapshot = SnapshotBuilder(runtime.app, modules.engine).build(0)
    observations = build_observations(snapshot)
    assert observations.tick == snapshot.tick
    assert observations.snapshot_hash == snapshot.state_hash()
    assert all(getattr(observations, name) for name in ("movement", "aim", "interaction"))
    assert "enemy=" in observations.movement[-1][1]
    assert "target=" in observations.aim[-1][1] or "bearing=" in observations.aim[-1][1]


def test_locked_exit_routes_to_a_reachable_key_first():
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M2", 96, 64) as runtime:
        snapshot = SnapshotBuilder(runtime.app, modules.engine).build(0)
    assert snapshot.navigation is not None
    assert snapshot.navigation.reachable
    assert snapshot.navigation.objective in {
        "blue-key",
        "blue-key-switch",
        "red-key",
        "red-key-switch",
        "yellow-key",
        "yellow-key-switch",
    }
    assert snapshot.navigation.distance > 0
    observations = build_observations(snapshot)
    assert snapshot.navigation.objective in observations.movement[0][1]


def test_uncollectable_blue_key_routes_to_its_reachable_lowering_switch():
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M2", 96, 64) as runtime:
        runtime.app.px = 1491.0
        runtime.app.py = -1043.0
        runtime.app.psec_i = runtime.app.point_secidx(runtime.app.px, runtime.app.py)
        snapshot = SnapshotBuilder(runtime.app, modules.engine).build(0)
    assert runtime.app.psec_i == 51
    assert snapshot.navigation is not None
    assert snapshot.navigation.objective == "blue-key-switch"
    assert snapshot.navigation.reachable
    assert snapshot.navigation.next_sector != 45


def test_blue_key_becomes_the_objective_after_its_platform_lowers():
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M2", 96, 64) as runtime:
        runtime.app.px = 1491.0
        runtime.app.py = -1043.0
        runtime.app.psec_i = runtime.app.point_secidx(runtime.app.px, runtime.app.py)
        runtime.app.activate(34, 1)
        for _ in range(50):
            runtime.step(DuumControls())
        snapshot = SnapshotBuilder(runtime.app, modules.engine).build(50)
        assert runtime.app.lvl.sectors[45][0] == 240
    assert snapshot.navigation is not None
    assert snapshot.navigation.objective == "blue-key"
    assert snapshot.navigation.reachable


def test_e1m1_final_room_uses_internal_subsector_before_portal():
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        runtime.app.px, runtime.app.py = 225.76, 1488.03
        runtime.app.psec_i = runtime.app.point_secidx(runtime.app.px, runtime.app.py)
        builder = SnapshotBuilder(runtime.app, modules.engine)
        snapshot = builder.build(1)
        waypoint = builder._nav_points[0]
    assert snapshot.navigation is not None
    assert snapshot.navigation.objective == "exit"
    assert snapshot.navigation.next_sector == runtime.app.psec_i == 135
    assert waypoint != pytest.approx((-224.0, 1408.0))
    assert not builder._geometry_blocked(225.76, 1488.03, *waypoint)


def test_e1m1_thin_door_subsector_targets_portal_midpoint():
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        runtime.app.px, runtime.app.py = -198.85, 1435.32
        runtime.app.psec_i = runtime.app.point_secidx(runtime.app.px, runtime.app.py)
        builder = SnapshotBuilder(runtime.app, modules.engine)
        snapshot = builder.build(1)
    assert snapshot.navigation is not None
    assert snapshot.navigation.objective == "exit"
    assert builder._nav_points[0] == pytest.approx((-224.0, 1408.0))


def test_last_bullet_and_fist_with_empty_guns_make_ammo_critical():
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        ammo = next(
            thing
            for thing in runtime.app.things_live
            if (pickup := modules.engine.PICKUP.get(thing[3])) is not None
            and pickup[0] == 3
            and pickup[1] == 1
        )
        runtime.app.px, runtime.app.py = float(ammo[0]), float(ammo[1])
        runtime.app.psec_i = runtime.app.point_secidx(runtime.app.px, runtime.app.py)
        runtime.app.weapon = 2
        runtime.app.ammo[1] = 1
        last_bullet = SnapshotBuilder(runtime.app, modules.engine).build(0)
        runtime.app.weapon = 1
        runtime.app.ammo[1] = 0
        empty_fist = SnapshotBuilder(runtime.app, modules.engine).build(0)
    assert last_bullet.visible_pickups[0].category == "ammo"
    assert last_bullet.visible_pickups[0].need == "critical"
    assert empty_fist.visible_pickups[0].category == "ammo"
    assert empty_fist.visible_pickups[0].need == "critical"


def test_low_health_makes_reachable_health_critical():
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        health = next(
            thing
            for thing in runtime.app.things_live
            if (pickup := modules.engine.PICKUP.get(thing[3])) is not None
            and pickup[0] == 0
            and pickup[1] > 1
        )
        runtime.app.px, runtime.app.py = float(health[0]), float(health[1])
        runtime.app.psec_i = runtime.app.point_secidx(runtime.app.px, runtime.app.py)
        runtime.app.health = 19
        snapshot = SnapshotBuilder(runtime.app, modules.engine).build(0)
    assert snapshot.visible_pickups[0].category == "health"
    assert snapshot.visible_pickups[0].need == "critical"
