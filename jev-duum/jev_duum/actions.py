"""Map semantic controls to Duum's public host key bitmap."""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import reflex
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
    of idling until the next model call.  The same call now also re-checks
    projectile dodges and blocked movements every tick, so the guard is not
    limited to the decision rate.
    """

    target = min(
        snapshot.visible_enemies,
        key=lambda enemy: (abs(enemy.bearing), enemy.distance, enemy.id),
        default=None,
    )
    urgent_pickup = next(
        (
            pickup
            for pickup in snapshot.visible_pickups
            if pickup.need in ("critical", "urgent")
        ),
        None,
    )
    if urgent_pickup is not None and urgent_pickup.need == "critical":
        target = None
    interaction = next(
        (item for item in snapshot.nearby_interactions if not item.locked), None
    )
    if interaction is not None and target is None:
        # Stop inside Duum's exact 65-unit use range instead of carrying a
        # low-rate forward command through (or sideways away from) a door.
        controls = replace(controls, movement="hold", aim="straight")
    bearing, tolerance, _ = reflex.guide_bearing(snapshot)
    settled, _ = reflex.apply(
        controls, snapshot, bearing=bearing, tolerance=tolerance
    )
    return settled


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
