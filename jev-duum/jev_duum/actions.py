"""Map semantic controls to Duum's public host key bitmap."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .types import DuumControls

# These values are Duum's documented host contract, not frontend key names.
A_FORWARD = 1
A_BACK = 2
A_TURN_RIGHT = 4
A_TURN_LEFT = 8
A_FIRE = 16
A_USE = 32
A_STRAFE_LEFT = 64
A_STRAFE_RIGHT = 128

MOVEMENT_MASKS = {
    "forward": A_FORWARD,
    "back": A_BACK,
    "strafe_left": A_STRAFE_LEFT,
    "strafe_right": A_STRAFE_RIGHT,
    "hold": 0,
}
AIM_MASKS = {"left": A_TURN_LEFT, "straight": 0, "right": A_TURN_RIGHT}
INTERACTION_MASKS = {"fire": A_FIRE, "use": A_USE, "neither": 0}


def controls_to_mask(controls: DuumControls) -> int:
    """Return the host-level bitmap consumed by `duum.hosts.desktop`."""

    return (
        MOVEMENT_MASKS[controls.movement]
        | AIM_MASKS[controls.aim]
        | INTERACTION_MASKS[controls.interaction]
    )


def settle_assisted_controls(controls: DuumControls, snapshot) -> DuumControls:
    """Close the loop between slower model decisions and 60 Hz turning.

    A model turn held for a full 5--20 Hz decision interval can cross a narrow
    waypoint several times.  The deterministic assisted layer therefore ends
    that turn on the first engine tick at which its combat target or route is
    centered (or has crossed the centerline).  Once a route is centered it may
    also begin the already-approved safe forward movement immediately instead
    of idling until the next model call.
    """

    if snapshot.player.weapon_name == "fist":
        combat = tuple(
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
        combat = (
            tuple(
                enemy
                for enemy in snapshot.visible_enemies
                if enemy.active or enemy.attacking or enemy.distance < 560
            )
            if snapshot.player.ammo > 0
            else ()
        )
    target = min(
        combat,
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
    interaction = next(
        (item for item in snapshot.nearby_interactions if not item.locked), None
    )
    if interaction is not None and target is None:
        # Stop inside Duum's exact 65-unit use range instead of carrying a
        # low-rate forward command through (or sideways away from) a door.
        controls = replace(controls, movement="hold", aim="straight")
    if controls.aim == "straight":
        return controls
    if target is not None:
        bearing = target.bearing
        guided_movement = False
    elif urgent_pickup is not None:
        bearing = urgent_pickup.bearing
        guided_movement = True
    elif route is not None and route.reachable:
        bearing = route.bearing
        guided_movement = True
    else:
        return controls
    tolerance = 0.10 if target is not None else 0.04
    crossed = (controls.aim == "left" and bearing <= tolerance) or (
        controls.aim == "right" and bearing >= -tolerance
    )
    if not crossed:
        return controls
    movement = controls.movement
    if guided_movement and movement == "hold":
        forward = next(
            (option for option in snapshot.movement_options if option.name == "forward"),
            None,
        )
        if forward is not None and forward.safe:
            movement = "forward"
    return replace(controls, aim="straight", movement=movement)


def ensure_usable_weapon(app, engine) -> bool:
    """Keep an actually usable weapon selected through Duum's public key API.

    Duum falls back to the fist when a gun runs dry, but collecting ammunition
    later does not restore a ranged weapon.  Recover here so the pilot cannot
    remain in a wall-punch loop despite once again having usable ammunition.
    """

    weapon = engine.WEAP[app.weapon]
    ammo_kind, per_shot = weapon[4], weapon[5]
    if ammo_kind and app.ammo[ammo_kind] < per_shot and 1 in app.owned:
        app.key(ord("1"), 0, False)
        return True
    if not ammo_kind:
        # Prefer effective general-purpose weapons, leaving the
        # self-damaging rocket launcher as a last resort.
        for slot in (6, 4, 3, 2, 5):
            if slot not in app.owned:
                continue
            candidate = engine.WEAP[slot]
            candidate_ammo, candidate_cost = candidate[4], candidate[5]
            if candidate_ammo and app.ammo[candidate_ammo] >= candidate_cost:
                app.key(ord(str(slot)), 0, False)
                return True
    return False


@dataclass(slots=True)
class SyntheticInput:
    """Adapter-owned held state; physical key names never enter this layer."""

    host: object
    mask: int = 0

    def apply(self, controls: DuumControls) -> int:
        self.mask = controls_to_mask(controls)
        self.host.set_keys(self.mask)
        return self.mask

    def release(self) -> None:
        self.mask = 0
        self.host.set_keys(0)
