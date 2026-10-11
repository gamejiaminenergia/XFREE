"""Keep the test suite out of the audit database.

Every ``JevClient`` writes its request/response to the jev-log API unless
logging is disabled, and unit tests answer with fake openers.  Set
``JEV_NO_LOG`` for the whole suite; tests that exercise the logger build their
own ``JevCallLogger(enabled=True)`` with an injected opener.

This module also builds the one deterministic synthetic snapshot the contract
tests freeze: the refactor must not change a byte of what travels to Jev, so
``test_jev_prompt_contract.py`` and ``test_jev_snapshot_contract.py`` hash the
output of ``build_state`` / ``state_hash`` over exactly this state.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("JEV_NO_LOG", "1")

from jev_duum.snapshot import (  # noqa: E402  (after the env guard on purpose)
    DuumSnapshot,
    EnemySnapshot,
    EpisodeSnapshot,
    InteractionSnapshot,
    MonsterSnapshot,
    MovementOptionSnapshot,
    NavigationSnapshot,
    PickupSnapshot,
    PlayerSnapshot,
    ProjectileSnapshot,
)


def synthetic_snapshot() -> DuumSnapshot:
    """One frozen snapshot touching every field the prompt builds read."""

    return DuumSnapshot(
        tick=750,
        map_name="E1M1",
        rng=12345,
        player=PlayerSnapshot(
            x=100.0, y=100.0, angle=0.5, health=100, armor=25, weapon=3,
            weapon_name="shotgun", ammo=24, weapon_ready=True, keys=1,
            damage_since_last=0, max_health=100,
        ),
        visible_enemies=(
            EnemySnapshot(
                id=1, category="imp", bearing=0.3, bearing_word="left-small",
                distance=140.0, distance_word="near", visible=True, attacking=False,
                active=True, melee_reachable=False, aligned=True, motion="closing",
                threat=800.0,
            ),
        ),
        incoming_projectiles=(
            ProjectileSnapshot(
                id=1, bearing=-0.2, bearing_word="right-small", distance=90.0,
                distance_word="contact", impact_time=0.4, impact=True,
                dodge="strafe_right", threat=1200.0,
            ),
        ),
        visible_pickups=(
            PickupSnapshot(
                id=3, category="health", bearing=0.1, bearing_word="aligned",
                distance=200.0, distance_word="near", need="useful",
            ),
        ),
        nearby_interactions=(
            InteractionSnapshot(kind="door", distance=40.0, locked=False, required_key=None),
        ),
        movement_options=(
            MovementOptionSnapshot(name="forward", clear_distance=64.0, safe=True),
            MovementOptionSnapshot(name="strafe_left", clear_distance=32.0, safe=True),
            MovementOptionSnapshot(name="strafe_right", clear_distance=24.0, safe=False),
        ),
        navigation=NavigationSnapshot(
            objective="exit", bearing=0.0, bearing_word="aligned", distance=500.0,
            distance_word="medium", next_sector=5, route_length=4, reachable=True,
            use_when_near=False,
        ),
        omitted_enemies=1,
        episode=EpisodeSnapshot(
            game_time=12.5, kills=3, items=2, damage_received=18, live_enemies=4,
            projectiles=1, unique_sectors=6, stuck_ticks=0, idle_ticks=0, dead=False,
            finished=False, monsters_remaining=5, monsters_awake=2,
        ),
        hidden_enemies=(
            MonsterSnapshot(
                id=2, kind=3001, category="imp", x=110.0, y=104.0, bearing=0.2,
                bearing_word="aligned", distance=120.0, distance_word="near", hp=60,
                hp_fraction=1.0, awake=True, attacking=True, has_los=True,
                direct_path=True, aligned=True, shots_to_kill=2, kill_seconds=1.2,
                arrival_seconds=0.6, kills_per_second=0.55,
            ),
        ),
        hunt_route=None,
        hunt_route_target_id=None,
    )


def synthetic_strategy() -> dict:
    """A recorded strategy block, as ``StrategyTracker`` would publish it."""

    return {
        "mission": "advance",
        "priority": "fight",
        "must_move": True,
        "hold_streak": 0,
        "max_hold_streak": 5,
        "status": "engaging",
        "plan": ["face the imp", "fire", "advance to the exit"],
        "relevant_threat_ids": [1],
        "progress": {"forward": 0.8, "strafe_left": 0.2, "hold": 0.0},
    }


def synthetic_world_model() -> dict:
    """A minimal schematic block; only its presence and shape matter here."""

    return {
        "rooms": [{"name": "START", "kind": "normal"}],
        "route": {"steps": 3, "rooms": ["START", "NUKAGE"]},
        "hazards": {"nukage": False},
        "sector_risk": {"values": [0.1, 0.2, 0.3], "worst_risk": 0.3},
        "hidden_foes": 2,
        "hidden_items": {"top_aspirations": []},
    }


def synthetic_hunt() -> dict:
    """A recorded hunt block, as ``HuntPlan.to_dict()`` would publish it."""

    return {
        "mission": "clear",
        "target_id": 2,
        "candidates": [
            {"id": 2, "choice": "target_1", "kills_per_second": 0.55, "awake": True},
        ],
    }


@pytest.fixture
def synthetic():
    return synthetic_snapshot()
