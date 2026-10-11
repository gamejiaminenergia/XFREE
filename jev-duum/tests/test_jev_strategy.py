import math

import pytest

from jev_duum.geometry import best_clear_movement, best_progress_movement, progress_scores
from jev_duum.snapshot import (
    DuumSnapshot,
    EnemySnapshot,
    EpisodeSnapshot,
    InteractionSnapshot,
    MovementOptionSnapshot,
    NavigationSnapshot,
    PickupSnapshot,
    PlayerSnapshot,
    ProjectileSnapshot,
)
from jev_duum.strategy import (
    MAX_HOLD_STREAK,
    StrategyTracker,
    compute_strategy,
    enforce_strategy,
    guide_bearing,
    threat_is_relevant,
)
from jev_duum.types import DuumControls


def enemy(bearing_degrees=20.0, distance=100.0, *, attacking=False, active=True, aligned=False, melee=True):
    bearing = math.radians(bearing_degrees)
    return EnemySnapshot(
        id=1,
        category="hitscan-enemy",
        bearing=bearing,
        bearing_word="left" if bearing > 0 else "right",
        distance=distance,
        distance_word="near",
        visible=True,
        attacking=attacking,
        active=active,
        melee_reachable=melee,
        aligned=aligned,
        motion="steady",
        threat=900.0,
    )


def make_snapshot(
    *,
    enemies=(),
    pickups=(),
    projectiles=(),
    interactions=(),
    route_degrees=30.0,
    reachable=True,
    forward_safe=True,
    health=100,
    tick=10,
):
    route = (
        NavigationSnapshot(
            objective="exit",
            bearing=math.radians(route_degrees),
            bearing_word="left",
            distance=120.0,
            distance_word="near",
            next_sector=17,
            route_length=16,
            reachable=reachable,
            use_when_near=False,
        )
        if route_degrees is not None
        else None
    )
    return DuumSnapshot(
        tick=tick,
        map_name="E1M1",
        rng=1,
        player=PlayerSnapshot(
            x=0.0,
            y=0.0,
            angle=0.0,
            health=health,
            armor=0,
            weapon=2,
            weapon_name="pistol",
            ammo=50,
            weapon_ready=True,
            keys=0,
            damage_since_last=0,
        ),
        visible_enemies=tuple(enemies),
        incoming_projectiles=tuple(projectiles),
        visible_pickups=tuple(pickups),
        nearby_interactions=tuple(interactions),
        movement_options=(
            MovementOptionSnapshot("forward", 200.0 if forward_safe else 0.0, forward_safe),
            MovementOptionSnapshot("back", 96.0, True),
            MovementOptionSnapshot("strafe_left", 48.0, True),
            MovementOptionSnapshot("strafe_right", 48.0, True),
        ),
        navigation=route,
        omitted_enemies=0,
        episode=EpisodeSnapshot(
            game_time=2.0,
            kills=0,
            items=0,
            damage_received=0,
            live_enemies=len(enemies),
            projectiles=len(projectiles),
            unique_sectors=1,
            stuck_ticks=0,
            idle_ticks=0,
            dead=False,
            finished=False,
        ),
    )


def projectile(bearing_degrees=45.0, dodge="strafe_right", impact_time=0.3):
    return ProjectileSnapshot(
        id=7,
        bearing=math.radians(bearing_degrees),
        bearing_word="left",
        distance=50.0,
        distance_word="contact",
        impact_time=impact_time,
        impact=True,
        dodge=dodge,
        threat=1000.0,
    )


def pickup(bearing_degrees=10.0, need="critical"):
    return PickupSnapshot(
        id=9,
        category="health",
        bearing=math.radians(bearing_degrees),
        bearing_word="left",
        distance=80.0,
        distance_word="contact",
        need=need,
    )


def test_progress_geometry_matches_the_bearing_convention():
    straight = progress_scores(0.0)
    assert straight["forward"] == 1.0
    assert straight["back"] == -1.0
    assert progress_scores(math.radians(90))["strafe_left"] == 1.0
    assert progress_scores(math.radians(-90))["strafe_right"] == 1.0
    assert progress_scores(math.radians(180))["back"] == 1.0
    assert progress_scores(math.radians(45))["forward"] == pytest.approx(0.707, abs=0.01)
    assert progress_scores(None) == {}


def test_best_progress_respects_safety_and_returns_none_without_progress():
    state = make_snapshot(route_degrees=30.0, forward_safe=True)
    assert best_progress_movement(state, math.radians(30)) == "forward"
    blocked = make_snapshot(route_degrees=30.0, forward_safe=False)
    # forward is blocked, strafe_left still closes part of the distance
    assert best_progress_movement(blocked, math.radians(30)) == "strafe_left"
    behind = make_snapshot(route_degrees=180.0)
    assert best_progress_movement(behind, math.pi) == "back"
    assert best_progress_movement(state, None) is None


def test_threat_relevance_ignores_distant_idle_enemies():
    assert not threat_is_relevant(
        enemy(distance=900.0, attacking=False, active=True, melee=False, aligned=False)
    )
    assert threat_is_relevant(enemy(distance=900.0, attacking=True, melee=False))
    assert threat_is_relevant(enemy(distance=200.0, active=False, melee=False))
    assert threat_is_relevant(enemy(distance=900.0, melee=True))
    assert threat_is_relevant(enemy(distance=900.0, melee=False, aligned=True))


def test_priority_precedence_dodge_over_resupply_over_fight_over_advance():
    tracker = StrategyTracker()
    assert compute_strategy(make_snapshot(), tracker).priority == "advance"
    fight = compute_strategy(make_snapshot(enemies=(enemy(distance=120.0),)), tracker)
    assert fight.priority == "fight" and fight.focus["kind"] == "threat"
    supply = compute_strategy(
        make_snapshot(enemies=(enemy(distance=120.0),), pickups=(pickup(),)), tracker
    )
    assert supply.priority == "resupply" and supply.focus["kind"] == "pickup"
    dodge = compute_strategy(
        make_snapshot(enemies=(enemy(distance=120.0),), pickups=(pickup(),), projectiles=(projectile(),)),
        tracker,
    )
    assert dodge.priority == "dodge" and dodge.focus["kind"] == "projectile"
    assert dodge.focus["dodge"] == "strafe_right"


def test_plan_forbids_holding_while_a_safe_direction_makes_progress():
    strategy = compute_strategy(make_snapshot(route_degrees=30.0), StrategyTracker())
    assert strategy.must_move is True
    assert strategy.hold_reason is None
    assert strategy.recommended_movement == "forward"
    assert strategy.guide_bearing_degrees == pytest.approx(30.0)
    assert strategy.progress["forward"] == pytest.approx(0.866, abs=0.01)
    assert any("Standing still is not allowed" in step for step in strategy.plan)


def test_holding_is_allowed_when_nothing_safe_makes_progress_or_at_use_geometry():
    behind = make_snapshot(route_degrees=None)
    assert compute_strategy(behind, StrategyTracker()).must_move is False
    door = make_snapshot(interactions=(InteractionSnapshot("door", 30.0, False, None),))
    strategy = compute_strategy(door, StrategyTracker())
    assert strategy.must_move is False and strategy.hold_reason == "use-geometry"


def test_tracker_counts_holds_and_resets_on_a_new_run():
    tracker = StrategyTracker()
    for tick in range(1, 4):
        tracker.observe(make_snapshot(route_degrees=170.0, tick=tick), DuumControls())
    assert tracker.hold_streak == 3
    tracker.observe(make_snapshot(tick=4), DuumControls("forward"))
    assert tracker.hold_streak == 0
    tracker.observe(make_snapshot(tick=2), DuumControls())
    assert tracker.hold_streak == 1  # tick went backwards: a new run started
    tracker.observe(make_snapshot(tick=3), DuumControls())
    tracker.observe(make_snapshot(tick=4), DuumControls())
    assert tracker.hold_streak == 3


def test_enforce_strategy_breaks_a_long_freeze_and_records_the_event():
    state = make_snapshot(route_degrees=None)
    tracker = StrategyTracker()
    tracker.hold_streak = MAX_HOLD_STREAK
    strategy = compute_strategy(state, tracker)
    assert strategy.must_move is True
    applied, events = enforce_strategy(state, strategy, DuumControls())
    assert applied.movement != "hold"
    assert applied.movement == best_clear_movement(state)
    assert [event.kind for event in events] == ["strategy-progress"]


def test_enforce_strategy_leaves_a_moving_proposal_alone():
    state = make_snapshot(route_degrees=30.0)
    strategy = compute_strategy(state, StrategyTracker())
    proposed = DuumControls("strafe_right", "straight", "neither")
    applied, events = enforce_strategy(state, strategy, proposed)
    assert applied == proposed and events == ()


def test_guide_bearing_prefers_projectile_then_pickup_then_route():
    assert guide_bearing(
        make_snapshot(projectiles=(projectile(bearing_degrees=45.0),))
    ) == pytest.approx(math.radians(-135.0))  # dodge away from the projectile
    assert guide_bearing(make_snapshot(pickups=(pickup(bearing_degrees=10.0),))) == pytest.approx(
        math.radians(10.0)
    )
    assert guide_bearing(make_snapshot(route_degrees=-20.0)) == pytest.approx(math.radians(-20.0))
    assert guide_bearing(make_snapshot(route_degrees=None)) is None


def test_dodge_recommends_the_escape_side():
    state = make_snapshot(projectiles=(projectile(bearing_degrees=45.0, dodge="strafe_right"),))
    strategy = compute_strategy(state, StrategyTracker())
    assert strategy.priority == "dodge"
    assert strategy.recommended_movement == "strafe_right"
    assert strategy.must_move is True


def test_critical_pickup_outranks_a_distant_projectile_but_not_an_imminent_one():
    distant = make_snapshot(
        pickups=(pickup(bearing_degrees=10.0),),
        projectiles=(projectile(bearing_degrees=45.0, impact_time=0.9),),
    )
    strategy = compute_strategy(distant, StrategyTracker())
    assert strategy.priority == "resupply"
    assert strategy.guide_bearing_degrees == pytest.approx(10.0)
    imminent = make_snapshot(
        pickups=(pickup(bearing_degrees=10.0),),
        projectiles=(projectile(bearing_degrees=45.0, impact_time=0.2),),
    )
    assert compute_strategy(imminent, StrategyTracker()).priority == "dodge"


def test_low_health_breaks_contact_instead_of_trading_hits():
    state = make_snapshot(
        enemies=(enemy(bearing_degrees=0.0, distance=150.0, attacking=True),),
        health=30,
    )
    strategy = compute_strategy(state, StrategyTracker())
    assert strategy.priority == "retreat"
    assert strategy.focus["kind"] == "threat"  # still aim at what is shooting
    assert abs(strategy.guide_bearing_degrees) == pytest.approx(180.0, abs=0.01)
    assert strategy.must_move is True
    assert strategy.recommended_movement == "back"
    assert "critical" in strategy.status


def test_healthy_player_keeps_advancing_under_fire():
    state = make_snapshot(
        enemies=(enemy(bearing_degrees=0.0, distance=150.0, attacking=True),),
        route_degrees=20.0,
        health=90,
    )
    strategy = compute_strategy(state, StrategyTracker())
    assert strategy.priority == "fight"
    assert strategy.guide_bearing_degrees == pytest.approx(20.0)  # the route, not the enemy
