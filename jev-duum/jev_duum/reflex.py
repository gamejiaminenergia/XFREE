"""The 60 Hz reflex layer: what the code does between model decisions.

The model decides at 5--20 Hz; the engine runs at 60.  Everything that must be
true on every single tick -- projectile dodge, refusing to walk into geometry,
finishing a turn the moment the target is centred, firing only from a corridor
the round can actually leave, and standing still for the firing tick so the
round leaves from the pose the bearing was taken from -- lives here as one pure
function.

``guide_aim`` and ``auto_fire`` turn the reflex into a complete local pilot;
the assisted model pilots use the same function with those flags off, so the
guard and the hunter can never drift apart.
"""

from __future__ import annotations

import math
from dataclasses import replace

from .geometry import (
    DIRECTIONS,
    best_clear_movement,
    best_progress_movement,
    progress_scores,
)
from .snapshot import DuumSnapshot
from .types import AssistanceEvent, DuumControls

TARGET_AIM_TOLERANCE_RADIANS = 0.10
ROUTE_AIM_TOLERANCE_RADIANS = 0.04


def movement_is_safe(snapshot: DuumSnapshot, movement: str) -> bool:
    """Whether a movement token is in the snapshot's safe set (``hold`` is safe)."""

    if movement == "hold":
        return True
    return any(
        option.name == movement and option.safe for option in snapshot.movement_options
    )


def guide_bearing(snapshot: DuumSnapshot) -> tuple[float | None, float, str]:
    """The bearing the assisted layer turns toward, plus its tolerance and kind.

    Keeps the historical precedence: a visible enemy beats an urgent pickup,
    which beats the route waypoint.
    """

    target = min(
        snapshot.visible_enemies,
        key=lambda enemy: (abs(enemy.bearing), enemy.distance, enemy.id),
        default=None,
    )
    if target is not None:
        return target.bearing, TARGET_AIM_TOLERANCE_RADIANS, "target"
    urgent = next(
        (
            pickup
            for pickup in snapshot.visible_pickups
            if pickup.need in ("critical", "urgent")
        ),
        None,
    )
    if urgent is not None:
        return urgent.bearing, ROUTE_AIM_TOLERANCE_RADIANS, "pickup"
    route = snapshot.navigation
    if route is not None and route.reachable:
        return route.bearing, ROUTE_AIM_TOLERANCE_RADIANS, "route"
    return None, TARGET_AIM_TOLERANCE_RADIANS, "none"


def _aim_for(bearing: float, tolerance: float) -> str:
    if abs(bearing) <= tolerance:
        return "straight"
    return "left" if bearing > 0 else "right"


def apply(
    controls: DuumControls,
    snapshot: DuumSnapshot,
    *,
    bearing: float | None = None,
    tolerance: float = TARGET_AIM_TOLERANCE_RADIANS,
    guide_aim: bool = False,
    auto_fire: bool = False,
) -> tuple[DuumControls, tuple[AssistanceEvent, ...]]:
    """Return the per-tick controls and every override the reflex had to make."""

    applied = controls
    events: list[AssistanceEvent] = []
    dodging = False

    # 1. An incoming projectile is the only thing that outranks the plan.
    projectile = next(
        (item for item in snapshot.incoming_projectiles if item.impact), None
    )
    if projectile is not None and applied.movement != projectile.dodge:
        alternative = (
            "strafe_right" if projectile.dodge == "strafe_left" else "strafe_left"
        )
        replacement = (
            projectile.dodge
            if movement_is_safe(snapshot, projectile.dodge)
            else alternative
            if movement_is_safe(snapshot, alternative)
            else None
        )
        if replacement is not None:
            events.append(
                AssistanceEvent(
                    "projectile-dodge",
                    f"predicted impact in {projectile.impact_time:.2f}s",
                    applied.movement,
                    replacement,
                )
            )
            applied = replace(applied, movement=replacement)
            dodging = True

    # 2. Never push into geometry: fall back to the safest useful direction.
    if not movement_is_safe(snapshot, applied.movement):
        replacement = (
            best_progress_movement(snapshot, bearing)
            or best_clear_movement(snapshot)
            or "hold"
        )
        events.append(
            AssistanceEvent(
                "blocked-movement",
                f"{applied.movement} is not a safe direction",
                applied.movement,
                replacement,
            )
        )
        applied = replace(applied, movement=replacement)

    # 3. Aim: the hunter drives it, the assisted pilots only finish the turn.
    if bearing is not None:
        if guide_aim:
            aim = _aim_for(bearing, tolerance)
            if aim != applied.aim:
                applied = replace(applied, aim=aim)
        elif applied.aim != "straight":
            crossed = (applied.aim == "left" and bearing <= tolerance) or (
                applied.aim == "right" and bearing >= -tolerance
            )
            if crossed:
                applied = replace(applied, aim="straight")
            elif applied.movement == "hold":
                preferred = best_progress_movement(snapshot, bearing)
                if preferred is not None:
                    applied = replace(applied, movement=preferred)

    # 4. The trigger only moves with a corridor, a ready weapon and ammunition.
    visible_aligned = any(enemy.aligned for enemy in snapshot.visible_enemies)
    # The catalogue lists every monster, visible or not, so an angular match on
    # its own is not a corridor: a monster behind a wall is dead ahead on the
    # compass but the round stops at the wall.  A hidden shot needs line of
    # sight, the same condition the engine's own hitscan enforces.
    aligned = visible_aligned or any(
        monster.aligned and monster.has_los for monster in snapshot.hidden_enemies
    )
    ready = bool(snapshot.player.weapon_ready) and snapshot.player.ammo > 0
    if auto_fire:
        # An unlocked door directly ahead is the productive action: a closed
        # door blocks the shot anyway, and `use` is what opens the way on.
        wanted = (
            "use"
            if applied.interaction == "use"
            else "fire"
            if aligned and ready and bearing is not None
            else "neither"
        )
        if applied.interaction != wanted:
            applied = replace(applied, interaction=wanted)
    elif applied.interaction == "fire" and (not visible_aligned or not ready):
        if snapshot.nearby_interactions:
            return applied, tuple(events)
        events.append(
            AssistanceEvent(
                "fire-alignment",
                "no target intersects the firing corridor",
                "fire",
                "neither",
            )
        )
        applied = replace(applied, interaction="neither")

    # 5. The engine moves the player and *then* fires, so a round leaves from a
    #    pose the bearing was not taken from: strafing five units at three
    #    hundred units away shifts the target out of the corridor, and the
    #    error grows with the tick length.  When the shot is authorised, stand
    #    still for this one tick and centre the aim, so the round leaves from
    #    exactly the pose `bearing` describes.  A projectile dodge still wins:
    #    the body stays mobile, only the aim is settled.
    if applied.interaction == "fire":
        if applied.aim != "straight":
            applied = replace(applied, aim="straight")
        if not dodging and applied.movement != "hold":
            events.append(
                AssistanceEvent(
                    "steady-aim",
                    "hold for the firing tick so the round leaves from the aimed pose",
                    applied.movement,
                    "hold",
                )
            )
            applied = replace(applied, movement="hold")

    return applied, tuple(events)


def aim_tolerance_for(distance: float) -> float:
    """The engine's own alignment tolerance for a target at ``distance``."""

    return max(0.025, math.atan2(22.0, max(float(distance), 1.0)))


def _committed_movement(
    snapshot: DuumSnapshot, bearing: float, previous: str | None
) -> str:
    """Close on ``bearing`` without flip-flopping between two equal options.

    Two side directions can score within a hair of each other; switching every
    tick makes the player vibrate in place.  Keep the previous direction while
    it is safe and still nearly as good.
    """

    scores = progress_scores(bearing)
    safe = {option.name for option in snapshot.movement_options if option.safe}
    candidates = [
        (scores.get(name, -1.0), name)
        for name in DIRECTIONS
        if name in safe
    ]
    if not candidates:
        return "hold"
    best_score, best_name = max(candidates, key=lambda item: (item[0], item[1]))
    if (
        previous is not None
        and previous in safe
        and scores.get(previous, -1.0) >= best_score - 0.25
    ):
        return previous
    return best_name


def hunter_controls(
    snapshot: DuumSnapshot,
    move_bearing: float | None,
    *,
    aim_bearing: float | None = None,
    tolerance: float | None = None,
    previous_movement: str | None = None,
) -> tuple[DuumControls, tuple[AssistanceEvent, ...]]:
    """A complete local decision: close on the waypoint, shoot what is aligned.

    Movement follows the waypoint bearing through whichever of the four
    directions actually closes the distance, so a target to the side or behind
    is approached while the player turns instead of orbiting it.  The aim
    follows ``aim_bearing`` (the monster) when it differs from the waypoint.
    """

    if move_bearing is None:
        base = DuumControls(
            best_clear_movement(snapshot) or "hold", "straight", "neither"
        )
    else:
        movement = _committed_movement(snapshot, move_bearing, previous_movement)
        base = DuumControls(
            movement,
            _aim_for(
                aim_bearing if aim_bearing is not None else move_bearing,
                tolerance or TARGET_AIM_TOLERANCE_RADIANS,
            ),
            "neither",
        )
    interaction = next(
        (item for item in snapshot.nearby_interactions if not item.locked), None
    )
    if interaction is not None and interaction.distance < 60:
        base = replace(base, interaction="use")
    return apply(
        base,
        snapshot,
        bearing=aim_bearing if aim_bearing is not None else move_bearing,
        tolerance=tolerance or TARGET_AIM_TOLERANCE_RADIANS,
        guide_aim=True,
        auto_fire=True,
    )


__all__ = [
    "ROUTE_AIM_TOLERANCE_RADIANS",
    "TARGET_AIM_TOLERANCE_RADIANS",
    "aim_tolerance_for",
    "apply",
    "guide_bearing",
    "hunter_controls",
    "movement_is_safe",
]
