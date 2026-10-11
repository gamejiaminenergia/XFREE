"""Code-owned strategy: mission, plan, rules of engagement and no-freeze guarantee.

Jev is a System One model: it judges, it does not plan.  This module makes the
plan in code — mission, priority, focus, progress geometry and an explicit
permission to stand still — and serializes it into the request, so the model
only has to pick the tactical step that executes it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .geometry import best_clear_movement, best_progress_movement, progress_scores
from .snapshot import DuumSnapshot
from .types import AssistanceEvent, DuumControls

MISSION = "advance"
MISSION_STATEMENT = "Reach the exit and keep the player moving."
ADVANCE_TOLERANCE_DEGREES = 45.0
MAX_HOLD_STREAK = 5  # 0.5 s at the tuned 10 Hz decision rate
RELEVANT_THREAT_DISTANCE = 240.0  # contact or near
# Below this health the plan breaks contact instead of trading hits; above it
# the mission keeps closing distance.  Measured on E1M1 the low-health ticks
# were already dodge/resupply, so this is the caution dial rather than a fix.
RETREAT_HEALTH = 40
# An impact this close is unavoidable damage; anything later waits while the
# player solves the more important problem (a critical pickup, for example).
IMMINENT_IMPACT_SECONDS = 0.4

RULES_OF_ENGAGEMENT = (
    "Fire whenever a shot reaches a threat; ammunition is plentiful.",
    "Only react to threats that attack, come within 240 units, are melee-reachable or are already in the firing corridor.",
    "Never stand still while a safe direction makes progress toward the mission.",
    "Keep closing distance toward the objective instead of trading shots at range.",
    "With health below 40 under fire, break contact by moving away while still shooting.",
)


def threat_is_relevant(enemy) -> bool:
    """A threat worth turning for; anything else is scenery."""

    return bool(
        enemy.attacking
        or enemy.distance < RELEVANT_THREAT_DISTANCE
        or enemy.melee_reachable
        or enemy.aligned
    )


@dataclass(frozen=True, slots=True)
class Strategy:
    mission: str
    mission_statement: str
    priority: str
    status: str
    plan: tuple[str, ...]
    rules_of_engagement: tuple[str, ...]
    focus: dict
    relevant_threat_ids: tuple[int, ...]
    hold_streak: int
    max_hold_streak: int
    must_move: bool
    hold_reason: str | None
    advance_tolerance_degrees: float
    guide_bearing_degrees: float | None
    progress: dict[str, float]
    recommended_movement: str | None

    def to_dict(self) -> dict:
        return {
            "mission": self.mission,
            "mission_statement": self.mission_statement,
            "priority": self.priority,
            "status": self.status,
            "plan": list(self.plan),
            "rules_of_engagement": list(self.rules_of_engagement),
            "focus": self.focus,
            "relevant_threat_ids": list(self.relevant_threat_ids),
            "hold_streak": self.hold_streak,
            "max_hold_streak": self.max_hold_streak,
            "must_move": self.must_move,
            "hold_reason": self.hold_reason,
            "advance_tolerance_degrees": self.advance_tolerance_degrees,
            "guide_bearing_degrees": self.guide_bearing_degrees,
            "progress": self.progress,
            "recommended_movement": self.recommended_movement,
        }


class StrategyTracker:
    """Per-run history the strategy needs: how long has the player been still."""

    def __init__(self) -> None:
        self.hold_streak = 0
        self._last_tick = -1

    def observe(self, snapshot: DuumSnapshot, controls: DuumControls) -> None:
        if snapshot.tick < self._last_tick or snapshot.episode.dead or snapshot.episode.finished:
            self.hold_streak = 0
        self._last_tick = snapshot.tick
        self.hold_streak = self.hold_streak + 1 if controls.movement == "hold" else 0

    def reset(self) -> None:
        self.hold_streak = 0
        self._last_tick = -1


def _degrees(radians: float) -> float:
    return round(math.degrees(radians), 1)


def _focus_dict(kind: str, bearing: float, **extra) -> dict:
    focus = {"kind": kind, "bearing_degrees": _degrees(bearing)}
    focus.update(extra)
    return focus


def _escape_bearing(bearing: float) -> float:
    """The direction that moves away from ``bearing``, wrapped to (-pi, pi]."""

    return (bearing + math.pi + math.pi) % math.tau - math.pi


def guide_bearing(snapshot: DuumSnapshot) -> float | None:
    """The direction the plan wants to move toward, in snapshot bearing radians.

    A dodge and a low-health retreat aim the plan *away* from the danger; every
    other priority aims it at the pickup, the route or the focus threat.
    """

    route = (
        snapshot.navigation
        if snapshot.navigation and snapshot.navigation.reachable
        else None
    )
    projectile = next((item for item in snapshot.incoming_projectiles if item.impact), None)
    critical_pickup = next(
        (pickup for pickup in snapshot.visible_pickups if pickup.need == "critical"), None
    )
    if projectile is not None and (
        critical_pickup is None or projectile.impact_time < IMMINENT_IMPACT_SECONDS
    ):
        return _escape_bearing(projectile.bearing)
    if critical_pickup is not None:
        return critical_pickup.bearing
    focus = min(
        (enemy for enemy in snapshot.visible_enemies if threat_is_relevant(enemy)),
        key=lambda enemy: (abs(enemy.bearing), enemy.distance, enemy.id),
        default=None,
    )
    if (
        focus is not None
        and snapshot.player.health < RETREAT_HEALTH
        and (focus.attacking or focus.distance < RELEVANT_THREAT_DISTANCE)
    ):
        return _escape_bearing(focus.bearing)
    if route is not None:
        return route.bearing
    return focus.bearing if focus is not None else None


def compute_strategy(snapshot: DuumSnapshot, tracker: StrategyTracker) -> Strategy:
    """Derive this decision's mission, plan, focus and movement guarantee."""

    route = snapshot.navigation if snapshot.navigation and snapshot.navigation.reachable else None
    projectile = next((item for item in snapshot.incoming_projectiles if item.impact), None)
    critical_pickup = next(
        (pickup for pickup in snapshot.visible_pickups if pickup.need == "critical"), None
    )
    relevant = tuple(enemy for enemy in snapshot.visible_enemies if threat_is_relevant(enemy))
    focus_threat = min(
        relevant, key=lambda enemy: (abs(enemy.bearing), enemy.distance, enemy.id), default=None
    )
    usable_geometry = next(
        (item for item in snapshot.nearby_interactions if not item.locked), None
    )
    guide = guide_bearing(snapshot)

    # An imminent impact beats everything; otherwise a critical pickup is the
    # survival move and takes precedence over a projectile that is still far,
    # so the plan does not oscillate between dodging and collecting.
    imminent_impact = projectile is not None and (
        critical_pickup is None or projectile.impact_time < IMMINENT_IMPACT_SECONDS
    )
    if imminent_impact:
        priority = "dodge"
        focus = _focus_dict(
            "projectile",
            projectile.bearing,
            dodge=projectile.dodge,
            impact_in_seconds=round(float(projectile.impact_time), 2),
        )
        status = (
            f"An incoming projectile lands in {projectile.impact_time:.2f}s to the "
            f"{projectile.bearing_word}; dodge."
        )
        plan = (
            f"Dodge now: move {projectile.dodge} if that direction is safe.",
            "Keep the weapon on the threat while the player moves.",
        )
    elif critical_pickup is not None:
        priority = "resupply"
        focus = _focus_dict(
            "pickup",
            critical_pickup.bearing,
            category=critical_pickup.category,
            need=critical_pickup.need,
        )
        status = (
            f"A {critical_pickup.category} pickup is critical and "
            f"{critical_pickup.bearing_word} at {critical_pickup.distance_word} range."
        )
        plan = (
            f"Collect the critical {critical_pickup.category}.",
            "Keep moving toward it instead of stopping.",
        )
    elif (
        focus_threat is not None
        and snapshot.player.health < RETREAT_HEALTH
        and (focus_threat.attacking or focus_threat.distance < RELEVANT_THREAT_DISTANCE)
    ):
        priority = "retreat"
        focus = _focus_dict(
            "threat",
            focus_threat.bearing,
            id=focus_threat.id,
            kind_detail=focus_threat.category,
            attacking=bool(focus_threat.attacking),
            shot_would_hit=bool(focus_threat.aligned),
            distance_units=round(float(focus_threat.distance), 1),
        )
        status = (
            f"Health {snapshot.player.health} is critical and {focus_threat.category} is "
            f"{focus_threat.distance_word} ({focus_threat.bearing_word}); break contact "
            "while keeping it in the sights."
        )
        plan = (
            "Move away from the threat: use the option with the highest progress toward escape.",
            "Keep the weapon on it and fire whenever a shot reaches.",
            "Retreat is still movement: never stand still to trade hits.",
        )
    elif focus_threat is not None:
        priority = "fight"
        focus = _focus_dict(
            "threat",
            focus_threat.bearing,
            id=focus_threat.id,
            kind_detail=focus_threat.category,
            attacking=bool(focus_threat.attacking),
            shot_would_hit=bool(focus_threat.aligned),
            distance_units=round(float(focus_threat.distance), 1),
        )
        status = (
            f"{focus_threat.category} is {focus_threat.bearing_word} and "
            f"{focus_threat.distance_word}"
            + (" while attacking" if focus_threat.attacking else "")
            + "; fight it without stopping."
        )
        plan = (
            f"Face the {focus_threat.category} and fire when the shot reaches it.",
            "Keep making progress toward the objective while fighting.",
        )
    else:
        priority = "advance"
        focus = (
            _focus_dict("objective", route.bearing, objective=route.objective)
            if route is not None
            else {"kind": "none"}
        )
        status = (
            f"No relevant threat. The {route.objective.replace('-', ' ')} is "
            f"{route.bearing_word} at {route.distance_word} range."
            if route is not None
            else "No relevant threat and no reachable route; keep moving and turn to look for the way on."
        )
        plan = (
            "Turn toward the objective and advance along the route.",
            "Move while turning; never idle in place.",
        )

    progress = progress_scores(guide)
    recommended = best_progress_movement(snapshot, guide)
    hold_reason: str | None = None
    if recommended is None:
        hold_reason = "no-progress" if guide is not None else "no-guide"
    elif usable_geometry is not None:
        hold_reason = "use-geometry"
    must_move = recommended is not None and hold_reason is None
    if not must_move and tracker.hold_streak >= MAX_HOLD_STREAK:
        crawl = best_clear_movement(snapshot)
        if crawl is not None:
            must_move = True
            hold_reason = None
            if recommended is None:
                recommended = crawl
                plan = (*plan, f"Stuck for {tracker.hold_streak} decisions: break the deadlock by moving {crawl}.")

    if must_move:
        plan = (*plan, "Standing still is not allowed this decision: pick a safe direction that makes progress.")
        hold_reason = None

    return Strategy(
        mission=MISSION,
        mission_statement=MISSION_STATEMENT,
        priority=priority,
        status=status,
        plan=plan,
        rules_of_engagement=RULES_OF_ENGAGEMENT,
        focus=focus,
        relevant_threat_ids=tuple(enemy.id for enemy in relevant),
        hold_streak=tracker.hold_streak,
        max_hold_streak=MAX_HOLD_STREAK,
        must_move=must_move,
        hold_reason=hold_reason,
        advance_tolerance_degrees=ADVANCE_TOLERANCE_DEGREES,
        guide_bearing_degrees=_degrees(guide) if guide is not None else None,
        progress=progress,
        recommended_movement=recommended,
    )


def enforce_strategy(
    snapshot: DuumSnapshot, strategy: Strategy, controls: DuumControls
) -> tuple[DuumControls, tuple[AssistanceEvent, ...]]:
    """Guarantee the plan: replace an unjustified freeze with real movement."""

    if not strategy.must_move or controls.movement != "hold":
        return controls, ()
    replacement = strategy.recommended_movement or best_clear_movement(snapshot)
    if replacement is None or replacement == "hold":
        return controls, ()
    return (
        replace(controls, movement=replacement),
        (
            AssistanceEvent(
                "strategy-progress",
                strategy.status,
                "hold",
                replacement,
            ),
        ),
    )
