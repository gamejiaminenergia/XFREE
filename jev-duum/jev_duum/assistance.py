"""Deterministic assistance and the geometry-only reference policy.

The assisted pilot never throws away what the model proposed: it records every
override.  This module keeps that logic pure so the same function can (a) guard
a live model decision and (b) act as the labelled reference when prompts are
compared offline over recorded snapshots.  Extracting it changes no behaviour.
"""

from __future__ import annotations

from dataclasses import replace

from .geometry import best_progress_movement
from .snapshot import DuumSnapshot
from .types import (
    ROUTE_AIM_TOLERANCE_RADIANS,
    AssistanceEvent,
    DuumControls,
)

__all__ = ["AssistanceEvent", "apply_assistance", "reference_controls", "reference_fire_allowed"]


def apply_assistance(
    snapshot: DuumSnapshot, proposed: DuumControls
) -> tuple[DuumControls, tuple[AssistanceEvent, ...]]:
    """Return the guarded controls and every override the guard had to make."""

    applied = proposed
    events = []
    options = {option.name: option for option in snapshot.movement_options}
    projectile = next(
        (item for item in snapshot.incoming_projectiles if item.impact), None
    )
    if projectile and applied.movement != projectile.dodge:
        events.append(
            AssistanceEvent(
                "projectile-dodge",
                f"predicted impact in {projectile.impact_time:.2f}s",
                applied.movement,
                projectile.dodge,
            )
        )
        applied = replace(applied, movement=projectile.dodge)
    selected = options.get(applied.movement)
    if selected is not None and not selected.safe:
        alternatives = [option for option in options.values() if option.safe]
        if alternatives:
            replacement = max(
                alternatives, key=lambda option: (option.clear_distance, option.name)
            ).name
        else:
            crawl = max(
                options.values(),
                key=lambda option: (option.clear_distance, option.name),
                default=None,
            )
            replacement = (
                crawl.name if crawl is not None and crawl.clear_distance > 0 else "hold"
            )
        events.append(
            AssistanceEvent(
                "blocked-movement",
                f"{applied.movement} has only {selected.clear_distance:.0f} clear units",
                applied.movement,
                replacement,
            )
        )
        applied = replace(applied, movement=replacement)
    if snapshot.player.weapon_name == "fist":
        combat_enemies = tuple(
            enemy
            for enemy in snapshot.visible_enemies
            if enemy.melee_reachable
            and (
                enemy.attacking
                or (enemy.active and enemy.distance < 160)
                or enemy.distance < 64
            )
        )
    else:
        combat_enemies = (
            tuple(
                enemy
                for enemy in snapshot.visible_enemies
                if enemy.active or enemy.attacking or enemy.distance < 560
            )
            if snapshot.player.ammo > 0
            else ()
        )
    target = min(
        combat_enemies,
        key=lambda enemy: (abs(enemy.bearing), enemy.distance, enemy.id),
        default=None,
    )
    route = snapshot.navigation
    near_exit = (
        route is not None
        and route.reachable
        and route.objective == "exit"
        and route.route_length <= 7
    )
    urgent_pickup = next(
        (
            pickup
            for pickup in snapshot.visible_pickups
            if pickup.need in ("critical", "urgent")
        ),
        None,
    )
    if (
        near_exit
        and urgent_pickup is not None
        and urgent_pickup.need != "critical"
        and snapshot.player.health >= 25
    ):
        urgent_pickup = None
    if urgent_pickup is not None and urgent_pickup.need == "critical":
        target = None
    if (
        target is not None
        and snapshot.player.health < 50
        and applied.movement in ("forward", "hold")
    ):
        evasive = [
            options[name]
            for name in ("strafe_left", "strafe_right")
            if options.get(name) is not None and options[name].safe
        ]
        if evasive:
            replacement = max(evasive, key=lambda option: option.clear_distance).name
            events.append(
                AssistanceEvent(
                    "combat-evasion",
                    "low health while an enemy has line of sight",
                    applied.movement,
                    replacement,
                )
            )
            applied = replace(applied, movement=replacement)
    if target is not None:
        desired_aim = (
            "straight"
            if target.aligned
            else "left"
            if target.bearing > 0
            else "right"
        )
        aim_reason = f"visible target is {target.bearing_word}"
    elif urgent_pickup is not None:
        desired_aim = (
            "straight"
            if abs(urgent_pickup.bearing) <= ROUTE_AIM_TOLERANCE_RADIANS
            else "left"
            if urgent_pickup.bearing > 0
            else "right"
        )
        aim_reason = (
            f"{urgent_pickup.need} {urgent_pickup.category} pickup is "
            f"{urgent_pickup.bearing_word}"
        )
    elif route is not None and route.reachable:
        desired_aim = (
            "straight"
            if abs(route.bearing) <= ROUTE_AIM_TOLERANCE_RADIANS
            else "left"
            if route.bearing > 0
            else "right"
        )
        aim_reason = f"{route.objective.replace('-', ' ')} route is {route.bearing_word}"
    else:
        desired_aim = applied.aim
        aim_reason = "no target or route"
    if applied.aim != desired_aim:
        events.append(AssistanceEvent("aim-guidance", aim_reason, applied.aim, desired_aim))
        applied = replace(applied, aim=desired_aim)

    if (
        projectile is None
        and target is None
        and (urgent_pickup is not None or (route is not None and route.reachable))
    ):
        guide_bearing = (
            urgent_pickup.bearing if urgent_pickup is not None else route.bearing
        )
        guide_name = (
            f"{urgent_pickup.need} {urgent_pickup.category}"
            if urgent_pickup is not None
            else f"{route.objective.replace('-', ' ')} route"
        )
        # Prefer the safe direction with the most progress toward the guide
        # instead of turning in place.  `progress` is the shared geometric
        # score: turning plus a strafe keeps the player moving and converges on
        # the waypoint, while a pure turn-in-place freeze was the old behaviour.
        # `hold` intentionally has no MovementOptionSnapshot because it cannot
        # collide, so it is only the answer when nothing safe makes progress.
        preferred = best_progress_movement(snapshot, guide_bearing) or "hold"
        if applied.movement != preferred:
            events.append(
                AssistanceEvent(
                    "navigation-progress",
                    f"{guide_name} is "
                    f"{urgent_pickup.bearing_word if urgent_pickup else route.bearing_word}",
                    applied.movement,
                    preferred,
                )
            )
            applied = replace(applied, movement=preferred)

    interaction = (
        snapshot.nearby_interactions[0] if snapshot.nearby_interactions else None
    )
    if interaction is not None and not interaction.locked and (
        target is None or not target.aligned
    ):
        if applied.interaction != "use":
            events.append(
                AssistanceEvent(
                    "navigation-use",
                    f"usable {interaction.kind} is directly ahead",
                    applied.interaction,
                    "use",
                )
            )
            applied = replace(applied, interaction="use")
    elif applied.interaction == "fire" and (target is None or not target.aligned):
        events.append(
            AssistanceEvent(
                "fire-alignment",
                "no target intersects the firing corridor",
                "fire",
                "neither",
            )
        )
        applied = replace(applied, interaction="neither")
    if (
        snapshot.player.weapon_name == "rockets"
        and proposed.interaction == "fire"
        and target is not None
        and target.distance < 160
    ):
        events.append(
            AssistanceEvent(
                "rocket-self-damage",
                "aligned target is inside the close explosive radius",
                applied.interaction,
                "neither",
            )
        )
        applied = replace(applied, interaction="neither")
    return applied, tuple(events)


def reference_controls(snapshot: DuumSnapshot) -> DuumControls:
    """The pure geometry-only reference: what the guard enforces from a neutral proposal.

    ``DuumControls()`` is ``hold``/``straight``/``neither``, so the returned
    controls are exactly the movement, aim and use the deterministic layer
    wants when the model has no opinion.  It is the offline label source.
    """

    return apply_assistance(snapshot, DuumControls())[0]


def reference_fire_allowed(snapshot: DuumSnapshot) -> bool:
    """Whether the deterministic layer would let a ``fire`` proposal survive."""

    return apply_assistance(snapshot, DuumControls(interaction="fire"))[0].interaction == "fire"
