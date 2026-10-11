"""The panel's display readout mirrors the schematic model but stays optional."""

import json

from jev_duum.snapshot import DuumSnapshot, EpisodeSnapshot, PlayerSnapshot
from jev_duum.world_readout import read_world


def _snapshot(x=-416.0, y=256.0, angle=0.0):
    return DuumSnapshot(
        tick=0,
        map_name="E1M1",
        rng=0,
        player=PlayerSnapshot(
            x=x, y=y, angle=angle, health=100, armor=0, weapon=2, weapon_name="pistol",
            ammo=50, weapon_ready=True, keys=0, damage_since_last=0,
        ),
        visible_enemies=(),
        incoming_projectiles=(),
        visible_pickups=(),
        nearby_interactions=(),
        movement_options=(),
        navigation=None,
        omitted_enemies=0,
        episode=EpisodeSnapshot(
            game_time=0.0, kills=0, items=0, damage_received=0, live_enemies=0,
            projectiles=0, unique_sectors=1, stuck_ticks=0, idle_ticks=0,
            dead=False, finished=False,
        ),
    )


def test_readout_exposes_the_panel_fields_and_is_json_safe():
    readout = read_world(_snapshot())
    assert readout.available is True
    assert readout.room == "START"
    assert readout.standing_on in ("floor", "nukage", "water", "teleporter")
    assert readout.route_steps is not None and readout.route_steps >= 1
    assert len(readout.sector_values) == 16
    payload = readout.to_dict()
    assert payload["room"] == "START"
    assert json.loads(json.dumps(payload))["available"] is True


def test_readout_is_fail_soft_when_the_schematic_is_unavailable(monkeypatch):
    import jev_duum.world_readout as world_readout

    monkeypatch.setattr(world_readout, "build_world_model", lambda snapshot: None)
    readout = world_readout.read_world(_snapshot())
    assert readout.available is False
    assert readout.room is None
    assert readout.sector_values == ()
