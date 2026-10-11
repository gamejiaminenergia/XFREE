"""The schematic world model is informative, approximate, and never fatal."""

import json
import math

from jev_duum.snapshot import DuumSnapshot, EpisodeSnapshot, PlayerSnapshot
from jev_duum.world_model import (
    SVG_SPAWN,
    _relative_bearing_degrees,
    build_world_model,
    duum_to_svg,
)


def _snapshot(x=-416.0, y=256.0, angle=0.0, health=100, armor=0, tick=0):
    return DuumSnapshot(
        tick=tick,
        map_name="E1M1",
        rng=0,
        player=PlayerSnapshot(
            x=x,
            y=y,
            angle=angle,
            health=health,
            armor=armor,
            weapon=2,
            weapon_name="pistol",
            ammo=50,
            weapon_ready=True,
            keys=0,
            damage_since_last=0,
        ),
        visible_enemies=(),
        incoming_projectiles=(),
        visible_pickups=(),
        nearby_interactions=(),
        movement_options=(),
        navigation=None,
        omitted_enemies=0,
        episode=EpisodeSnapshot(
            game_time=0.0,
            kills=0,
            items=0,
            damage_received=0,
            live_enemies=0,
            projectiles=0,
            unique_sectors=1,
            stuck_ticks=0,
            idle_ticks=0,
            dead=False,
            finished=False,
        ),
    )


def test_spawn_maps_onto_the_svg_arrow_and_the_start_room():
    model = build_world_model(_snapshot())
    assert model is not None
    assert model["position_px"] == list(SVG_SPAWN)
    assert model["room"] == "START"
    assert model["hazards"]["nukage"] is False
    assert model["route"]["rooms"][0] == "START"
    assert model["route"]["rooms"][-1] == "EXIT"


def test_the_block_is_json_serializable_and_complete():
    model = build_world_model(_snapshot())
    assert model is not None
    for key in (
        "map",
        "position_px",
        "cell",
        "room",
        "nearest",
        "floor",
        "hazards",
        "route",
        "sector_risk",
        "hidden_foes",
        "hidden_items",
        "calibration",
    ):
        assert key in model
    assert model["calibration"]["src"] == "svg-approx"
    json.dumps(model)


def test_top_lists_are_truncated_to_three():
    model = build_world_model(_snapshot())
    assert model is not None
    assert len(model["hidden_foes"]["top_threats"]) <= 3
    assert len(model["hidden_items"]["top_aspirations"]) <= 3


def test_bearing_convention_positive_means_left():
    # Facing east (SVG heading 0) a point straight up-screen is to the left.
    left = _relative_bearing_degrees(0.0, 0.0, 0.0, -10.0, 0.0)
    right = _relative_bearing_degrees(0.0, 0.0, 0.0, 10.0, 0.0)
    ahead = _relative_bearing_degrees(0.0, 0.0, 10.0, 0.0, 0.0)
    assert left == 90.0
    assert right == -90.0
    assert ahead == 0.0


def test_the_calibration_is_anchored_at_the_spawn():
    assert duum_to_svg(-416.0, 256.0) == SVG_SPAWN
    # X grows east and Y is flipped (Doom north is up on the schematic).
    east = duum_to_svg(0.0, 256.0)[0]
    north = duum_to_svg(-416.0, 1256.0)[1]
    assert east > SVG_SPAWN[0]
    assert north < SVG_SPAWN[1]


def test_impossible_positions_fail_soft():
    assert build_world_model(_snapshot(x=math.nan)) is None


def test_a_broken_adapter_input_never_raises():
    class Broken:
        map_name = "E1M1"

        @property
        def player(self):
            raise RuntimeError("no player")

    assert build_world_model(Broken()) is None


def test_far_off_map_positions_still_return_a_block_or_none():
    # Off the schematic the adapter may still answer, but never with an
    # exception and never with a non-serializable value.
    result = build_world_model(_snapshot(x=100000.0, y=-100000.0))
    if result is not None:
        json.dumps(result)
