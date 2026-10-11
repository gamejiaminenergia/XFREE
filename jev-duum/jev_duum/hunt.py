"""Code-owned hunt plan: which monster to kill next and why.

The mission is to clear the level, so the objective is not the exit but the
next kill.  The engine already publishes every live monster (dormant included)
through the snapshot's hunt catalogue, each one carrying the adversary model's
extrapolation: shots to kill, kill seconds, arrival seconds and the projected
kill rate.  This module turns that table into one ranked decision and keeps it
stable across decisions so the player does not oscillate between two targets.

Numbers come from code; the model only judges.  A ``HuntPlan`` is what rides
into the request as ``state.hunt`` and what the strategy turns into a guide
bearing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .snapshot import DuumSnapshot, MonsterSnapshot

# Keeping the current target is worth a lot: swapping every decision would make
# the player walk in circles.  A challenger must beat the incumbent by this
# factor to take over.
TARGET_SWITCH_MARGIN = 1.5

# A target that has not been approached for this many simulated seconds is
# abandoned and only reconsidered once it is awake with a clear line of sight.
NO_PROGRESS_SECONDS = 2.0
NO_PROGRESS_LIMIT = 3
PROGRESS_EPSILON_UNITS = 24.0


@dataclass(frozen=True, slots=True)
class HuntPlan:
    """One decision's hunt order, shared by the prompt, the strategy and the panel."""

    objective: str
    target_id: int | None
    target_bearing: float | None
    target_distance: float | None
    route_bearing: float | None
    route_distance: float | None
    route_reachable: bool
    candidates: tuple[MonsterSnapshot, ...]
    monsters_remaining: int
    monsters_awake: int
    unique_sectors: int
    rationale: str
    abandoned_targets: tuple[int, ...] = ()

    @property
    def has_target(self) -> bool:
        return self.target_id is not None

    def to_dict(self) -> dict:
        return {
            "objective": self.objective,
            "target_id": self.target_id,
            "target_bearing_degrees": (
                None
                if self.target_bearing is None
                else round(self.target_bearing * 57.29577951308232, 1)
            ),
            "target_distance_units": (
                None if self.target_distance is None else round(self.target_distance, 1)
            ),
            "route_bearing_degrees": (
                None
                if self.route_bearing is None
                else round(self.route_bearing * 57.29577951308232, 1)
            ),
            "route_distance_units": (
                None if self.route_distance is None else round(self.route_distance, 1)
            ),
            "route_reachable": self.route_reachable,
            "monsters_remaining": self.monsters_remaining,
            "monsters_awake": self.monsters_awake,
            "unique_sectors": self.unique_sectors,
            "rationale": self.rationale,
            "candidate_ids": [monster.id for monster in self.candidates],
            "abandoned_targets": list(self.abandoned_targets),
        }


@dataclass(slots=True)
class HuntTracker:
    """Per-run hunt memory: sticky target, progress watchdog and blacklist."""

    target_id: int | None = None
    best_distance: float | None = None
    last_tick: int = -1
    no_progress: int = 0
    failures: dict[int, int] = field(default_factory=dict)

    def reset(self) -> None:
        self.target_id = None
        self.best_distance = None
        self.last_tick = -1
        self.no_progress = 0
        self.failures.clear()

    def observe(self, snapshot: DuumSnapshot) -> None:
        """Update the progress watchdog from the fresh catalogue."""

        if snapshot.tick < self.last_tick or snapshot.episode.dead or snapshot.episode.finished:
            self.reset()
        self.last_tick = int(snapshot.tick)
        by_id = {monster.id: monster for monster in snapshot.hidden_enemies}
        target = by_id.get(self.target_id) if self.target_id is not None else None
        if target is None:
            # The target died, or fell out of the truncated catalogue.
            if self.target_id is not None and self.target_id not in by_id:
                self.failures.pop(self.target_id, None)
            self.best_distance = None
            self.no_progress = 0
            return
        if self.best_distance is None or target.distance < self.best_distance - PROGRESS_EPSILON_UNITS:
            self.best_distance = target.distance
            self.no_progress = 0
            return
        self.no_progress += 1
        if self.no_progress * 0.1 >= NO_PROGRESS_SECONDS:
            self.failures[self.target_id] = self.failures.get(self.target_id, 0) + 1
            self.no_progress = 0
            if self.failures[self.target_id] >= NO_PROGRESS_LIMIT:
                self.target_id = None
                self.best_distance = None

    def abandoned(self) -> tuple[int, ...]:
        return tuple(
            sorted(
                target_id
                for target_id, count in self.failures.items()
                if count >= NO_PROGRESS_LIMIT
            )
        )

    def blacklisted(self, monster: MonsterSnapshot) -> bool:
        return (
            self.failures.get(monster.id, 0) >= NO_PROGRESS_LIMIT
            and not (monster.awake and monster.has_los)
        )


def _rank(candidates: tuple[MonsterSnapshot, ...], tracker: HuntTracker) -> tuple[MonsterSnapshot, ...]:
    usable = tuple(monster for monster in candidates if not tracker.blacklisted(monster))
    return tuple(
        sorted(
            usable,
            key=lambda monster: (
                -monster.kills_per_second,
                not monster.awake,
                monster.distance,
                monster.id,
            ),
        )
    )


def choose_target(
    candidates: tuple[MonsterSnapshot, ...], tracker: HuntTracker
) -> MonsterSnapshot | None:
    """Pick the next kill, with hysteresis so the choice is stable."""

    ranked = _rank(candidates, tracker)
    if not ranked:
        tracker.target_id = None
        return None
    incumbent = next(
        (monster for monster in ranked if monster.id == tracker.target_id), None
    )
    best = ranked[0]
    if incumbent is not None and incumbent is not best:
        if incumbent.kills_per_second * TARGET_SWITCH_MARGIN >= best.kills_per_second:
            return incumbent
    return best


def compute_hunt(snapshot: DuumSnapshot, tracker: HuntTracker) -> HuntPlan:
    """Derive this decision's hunt order from the snapshot catalogue."""

    tracker.observe(snapshot)
    candidates = snapshot.hidden_enemies
    ranked = _rank(candidates, tracker)
    target = choose_target(candidates, tracker)
    if target is not None and target.id != tracker.target_id:
        # A fresh target starts its own progress watchdog.
        tracker.best_distance = target.distance
        tracker.no_progress = 0
    tracker.target_id = target.id if target is not None else None

    if target is None:
        rationale = (
            "No reachable monster left in the catalogue: head for the exit."
            if snapshot.episode.monsters_remaining == 0
            else "Every known monster is unreachable right now: keep moving and re-check."
        )
    else:
        rationale = (
            f"Kill monster {target.id} ({target.category}) at {target.distance:.0f} units: "
            f"{target.shots_to_kill} shot(s), {target.kill_seconds:.2f}s of trigger time, "
            f"{target.kills_per_second:.3f} projected kills/s"
            + (", already awake" if target.awake else ", still dormant")
            + (", clear line of fire" if target.has_los else ", no line of fire yet")
        )
    route = snapshot.hunt_route
    routed = (
        target is not None
        and route is not None
        and snapshot.hunt_route_target_id == target.id
    )
    return HuntPlan(
        objective="hunt" if target is not None else "exit",
        target_id=target.id if target is not None else None,
        target_bearing=(
            None if target is None else (route.bearing if routed else target.bearing)
        ),
        target_distance=(
            None if target is None else (route.distance if routed else target.distance)
        ),
        route_bearing=route.bearing if routed else None,
        route_distance=route.distance if routed else None,
        route_reachable=bool(routed and route.reachable),
        candidates=ranked[:3],
        monsters_remaining=int(snapshot.episode.monsters_remaining),
        monsters_awake=int(snapshot.episode.monsters_awake),
        unique_sectors=int(snapshot.episode.unique_sectors),
        rationale=rationale,
        abandoned_targets=tracker.abandoned(),
    )


def target_by_id(snapshot: DuumSnapshot, target_id: int | None) -> MonsterSnapshot | None:
    """Look one hunt target up by id, ignoring the top-3 truncation."""

    if target_id is None:
        return None
    return next(
        (monster for monster in snapshot.hidden_enemies if monster.id == target_id), None
    )


def with_target(
    plan: HuntPlan, monster: MonsterSnapshot | None, snapshot: DuumSnapshot | None = None
) -> HuntPlan:
    """Replace the plan's chosen target, keeping the rest of the order intact."""

    if monster is None:
        return replace(
            plan,
            objective="exit",
            target_id=None,
            target_bearing=None,
            target_distance=None,
            route_bearing=None,
            route_distance=None,
            route_reachable=False,
            rationale="The model asked to leave: head for the exit.",
        )
    route = snapshot.hunt_route if snapshot is not None else None
    routed = (
        route is not None
        and snapshot is not None
        and snapshot.hunt_route_target_id == monster.id
    )
    return replace(
        plan,
        objective="hunt",
        target_id=monster.id,
        target_bearing=route.bearing if routed else monster.bearing,
        target_distance=route.distance if routed else monster.distance,
        route_bearing=route.bearing if routed else None,
        route_distance=route.distance if routed else None,
        route_reachable=bool(routed and route.reachable),
        rationale=(
            f"The model chose monster {monster.id} ({monster.category}) at "
            f"{monster.distance:.0f} units: {monster.shots_to_kill} shot(s), "
            f"{monster.kills_per_second:.3f} projected kills/s"
        ),
    )


__all__ = [
    "HuntPlan",
    "HuntTracker",
    "NO_PROGRESS_LIMIT",
    "NO_PROGRESS_SECONDS",
    "TARGET_SWITCH_MARGIN",
    "choose_target",
    "compute_hunt",
    "target_by_id",
    "with_target",
]
