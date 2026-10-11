"""Tests for the adversary model, the hunt plan and the 60 Hz reflex."""

from __future__ import annotations

import dataclasses
import math
from types import SimpleNamespace

from jev_duum import adversary, reflex
from jev_duum.hunt import HuntTracker, compute_hunt, target_by_id
from jev_duum.snapshot import (
    DuumSnapshot,
    EpisodeSnapshot,
    MonsterSnapshot,
    MovementOptionSnapshot,
    PlayerSnapshot,
    ProjectileSnapshot,
)
from jev_duum.types import DuumControls


def fake_engine(*, damage_mult=1):
    return SimpleNamespace(
        MONST={
            3004: (20, 90, 20, 200, 1),    # zombieman, hitscan
            3001: (60, 90, 20, 200, 3),    # imp, fireball
            3002: (150, 145, 30, 180, 0),  # demon, melee
        },
        WEAP={
            1: (b"Fist", b"PUNG", None, 0.55, 0, 0),
            2: (b"Pistol", b"PISG", b"PISF", 0.42, 1, 1),
            3: (b"Shotgun", b"SHTG", b"SHTF", 1.05, 2, 1),
        },
        DAMAGE_MULT=damage_mult,
    )


def monster(
    monster_id=1,
    *,
    bearing_degrees=0.0,
    distance=200.0,
    awake=False,
    aligned=False,
    direct_path=True,
    kps=0.5,
):
    bearing = math.radians(bearing_degrees)
    return MonsterSnapshot(
        id=monster_id,
        kind=3001,
        category="projectile-enemy",
        x=0.0,
        y=0.0,
        bearing=bearing,
        bearing_word="aligned",
        distance=distance,
        distance_word="near",
        hp=60,
        hp_fraction=1.0,
        awake=awake,
        attacking=False,
        has_los=aligned,
        direct_path=direct_path,
        aligned=aligned,
        shots_to_kill=1,
        kill_seconds=0.42,
        arrival_seconds=round(distance / adversary.PLAYER_SPEED, 3),
        kills_per_second=kps,
    )


def snapshot(*, monsters=(), projectiles=(), forward_safe=True, interactions=()):
    return DuumSnapshot(
        tick=10,
        map_name="E1M1",
        rng=1,
        player=PlayerSnapshot(
            x=0.0,
            y=0.0,
            angle=0.0,
            health=1000,
            armor=0,
            weapon=2,
            weapon_name="pistol",
            ammo=50,
            weapon_ready=True,
            keys=0,
            damage_since_last=0,
            max_health=1000,
        ),
        visible_enemies=(),
        incoming_projectiles=tuple(projectiles),
        visible_pickups=(),
        nearby_interactions=tuple(interactions),
        movement_options=(
            MovementOptionSnapshot("forward", 96.0 if forward_safe else 0.0, forward_safe),
            MovementOptionSnapshot("back", 96.0, True),
            MovementOptionSnapshot("strafe_left", 96.0, True),
            MovementOptionSnapshot("strafe_right", 96.0, True),
        ),
        navigation=None,
        omitted_enemies=0,
        episode=EpisodeSnapshot(
            game_time=1.0,
            kills=0,
            items=0,
            damage_received=0,
            live_enemies=len(monsters),
            projectiles=0,
            unique_sectors=1,
            stuck_ticks=0,
            idle_ticks=0,
            dead=False,
            finished=False,
            monsters_remaining=len(monsters),
            monsters_awake=sum(1 for item in monsters if item.awake),
        ),
        hidden_enemies=tuple(monsters),
    )


def test_adversary_derives_shots_and_multipliers_from_the_engine_table():
    engine = fake_engine()
    assert adversary.monster_category(engine, 3001) == "projectile-enemy"
    assert adversary.monster_category(engine, 3002) == "melee-enemy"
    # Pistol averages 10 a shot, so an imp needs 6 and a zombieman 2.
    assert adversary.shots_to_kill(engine, 3001, 2, effective=False) == 6
    assert adversary.shots_to_kill(engine, 3004, 2, effective=False) == 2
    # The balance mod multiplies the player's damage, not the incoming one.
    modded = fake_engine(damage_mult=10)
    assert adversary.shots_to_kill(modded, 3001, 2) == 1
    # The 150 hp demon still needs two 10x pistol shots (100 expected damage).
    assert adversary.shots_to_kill(modded, 3002, 2) == 2
    assert adversary.incoming_dps(modded, 3001, 200.0) == adversary.incoming_dps(
        engine, 3001, 200.0
    )


def test_hunt_picks_the_best_projected_kill_rate_and_respects_the_blacklist():
    tracker = HuntTracker()
    state = snapshot(
        monsters=(
            monster(1, distance=800.0, kps=0.10),
            monster(2, distance=120.0, awake=True, aligned=True, kps=0.90),
        )
    )
    plan = compute_hunt(state, tracker)
    assert plan.target_id == 2
    assert plan.objective == "hunt"
    assert plan.candidates[0].id == 2
    assert "projected kills/s" in plan.rationale
    tracker.target_id = 1
    tracker.failures[1] = 3
    assert compute_hunt(state, tracker).target_id == 2
    assert target_by_id(state, 2).id == 2
    assert target_by_id(state, 99) is None


def test_hunt_falls_back_to_the_exit_when_every_monster_is_gone():
    plan = compute_hunt(snapshot(), HuntTracker())
    assert plan.objective == "exit"
    assert plan.has_target is False
    assert plan.to_dict()["target_id"] is None


def test_reflex_dodges_an_impacting_projectile_even_when_the_model_says_hold():
    projectile = ProjectileSnapshot(
        id=7,
        bearing=math.radians(-40.0),
        bearing_word="right",
        distance=60.0,
        distance_word="contact",
        impact_time=0.3,
        impact=True,
        dodge="strafe_left",
        threat=1000.0,
    )
    controls, events = reflex.apply(DuumControls(), snapshot(projectiles=(projectile,)))
    assert controls.movement == "strafe_left"
    assert [event.kind for event in events] == ["projectile-dodge"]


def test_reflex_never_pushes_into_geometry():
    state = snapshot(forward_safe=False)
    controls, events = reflex.apply(DuumControls("forward"), state, bearing=0.0)
    assert controls.movement in ("back", "strafe_left", "strafe_right")
    assert events and events[0].kind == "blocked-movement"


def test_reflex_holds_still_and_centres_on_the_firing_tick():
    # The engine moves the player before it fires, so a shot fired while
    # strafing leaves from a pose the bearing was not measured from.
    state = snapshot(monsters=(monster(1, aligned=True),))
    controls, events = reflex.hunter_controls(state, 0.0)
    assert controls.interaction == "fire"
    assert controls.movement == "hold"
    assert controls.aim == "straight"
    assert any(event.kind == "steady-aim" for event in events)


def test_reflex_centres_an_off_axis_aim_before_pulling_the_trigger():
    state = snapshot(monsters=(monster(1, aligned=True),))
    controls, _ = reflex.apply(
        DuumControls("forward", "right", "fire"), state, bearing=0.0, auto_fire=True
    )
    assert controls.interaction == "fire"
    assert controls.aim == "straight"
    assert controls.movement == "hold"


def test_reflex_keeps_dodging_while_it_fires():
    projectile = ProjectileSnapshot(
        id=7,
        bearing=math.radians(-40.0),
        bearing_word="right",
        distance=60.0,
        distance_word="contact",
        impact_time=0.3,
        impact=True,
        dodge="strafe_left",
        threat=1000.0,
    )
    state = snapshot(
        monsters=(monster(1, aligned=True),), projectiles=(projectile,)
    )
    controls, _ = reflex.apply(
        DuumControls("forward", "straight", "fire"), state, bearing=0.0, auto_fire=True
    )
    assert controls.movement == "strafe_left"
    assert controls.interaction == "fire"


def test_reflex_does_not_fire_through_a_wall_at_a_hidden_monster():
    # Angularly aligned but with no line of sight: the catalogue lists every
    # monster, so the corridor check must require the engine's own sight test.
    blocked = dataclasses.replace(monster(1, aligned=True), has_los=False)
    state = snapshot(monsters=(blocked,))
    controls, _ = reflex.apply(
        DuumControls("hold", "straight", "fire"), state, bearing=0.0, auto_fire=True
    )
    assert controls.interaction == "neither"



def test_hunter_controls_uses_the_door_ahead():
    door = SimpleNamespace(kind="door", distance=23.0, locked=False, required_key=None)
    state = dataclasses.replace(snapshot(), nearby_interactions=(door,))
    controls, _ = reflex.hunter_controls(state, 0.0)
    assert controls.interaction == "use"


class FakeClient:
    """Minimal stand-in for JevClient: four answers, no network."""

    endpoint = "fake://typesafe"

    def __init__(self, target="target_2"):
        self.target = target
        self.last_state = None
        self.last_questions = None

    def ask(self, state, questions, *, model=None, context=None):
        self.last_state = state
        self.last_questions = questions
        return {
            "model": "jev-test",
            "usage": {"input_tokens": 100},
            "answers": {
                "movement": {
                    "type": "choice",
                    "choice": "forward",
                    "confidence": 0.6,
                    "probabilities": {
                        "forward": 0.6,
                        "back": 0.1,
                        "strafe_left": 0.1,
                        "strafe_right": 0.1,
                        "hold": 0.1,
                    },
                },
                "aim": {
                    "type": "choice",
                    "choice": "straight",
                    "confidence": 0.7,
                    "probabilities": {"left": 0.1, "straight": 0.7, "right": 0.2},
                },
                "interaction": {
                    "type": "choice",
                    "choice": "fire",
                    "confidence": 0.8,
                    "probabilities": {"fire": 0.8, "use": 0.1, "neither": 0.1},
                },
                "target": {
                    "type": "choice",
                    "choice": self.target,
                    "confidence": 0.5,
                    "probabilities": {
                        "target_1": 0.2,
                        "target_2": 0.4,
                        "target_3": 0.1,
                        "exit": 0.2,
                        "advance": 0.1,
                    },
                },
            },
        }


def test_v4_controller_asks_for_a_target_and_lets_the_model_pick_it():
    from jev_duum.controller import JevDuumController

    client = FakeClient(target="target_2")
    controller = JevDuumController(
        client=client, assisted=True, prompt_version="v4", mission="clear"
    )
    state = snapshot(
        monsters=(
            monster(1, distance=800.0, kps=0.10),
            monster(2, distance=120.0, kps=0.20),
        )
    )
    result = controller.decide(state)
    assert set(client.last_questions) == {"movement", "aim", "interaction", "target"}
    assert set(client.last_state["hunt"]["candidates"][0]) >= {
        "choice",
        "shots_to_kill",
        "kills_per_second",
    }
    assert client.last_state["adversary"] == []
    assert result.target_choice == "target_2"
    # The model overrode the code's ranking (monster 1 had a worse projection).
    assert result.hunt["target_id"] == result.hunt["candidate_ids"][1]
