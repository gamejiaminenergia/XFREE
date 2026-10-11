"""Non-model pilots retained as deterministic adapter and engine baselines."""

from __future__ import annotations

import random

from . import reflex
from .hunt import HuntTracker, compute_hunt
from .types import DuumControls


def scripted_controls(tick: int) -> DuumControls:
    """A repeatable sequence exercising every semantic control dimension."""

    phase = tick % 360
    if phase < 60:
        return DuumControls("forward", "straight", "neither")
    if phase < 90:
        return DuumControls("hold", "left", "neither")
    if phase < 150:
        return DuumControls("forward", "straight", "fire")
    if phase < 210:
        return DuumControls("strafe_right", "right", "neither")
    if phase == 210:
        return DuumControls("hold", "straight", "use")
    if phase < 270:
        return DuumControls("back", "straight", "neither")
    if phase < 330:
        return DuumControls("strafe_left", "left", "fire")
    return DuumControls()


class RandomPilot:
    def __init__(self, seed=0):
        self.random = random.Random(seed)

    def decide(self, _snapshot) -> DuumControls:
        return DuumControls(
            self.random.choice(("forward", "back", "strafe_left", "strafe_right", "hold")),
            self.random.choice(("left", "straight", "right")),
            self.random.choice(("fire", "use", "neither")),
        )


class HunterPilot:
    """Deterministic level-clear pilot: code-owned hunt plan plus 60 Hz reflex.

    It exists to answer one question without spending a token: how many kills
    can the adversary model and the reflex layer get on their own?  The answer
    is the baseline the Jev ``v4`` target choice has to beat.
    """

    def __init__(self) -> None:
        self.tracker = HuntTracker()
        self.plan = None
        self._last_movement: str | None = None

    def decide(self, snapshot) -> DuumControls:
        self.plan = compute_hunt(snapshot, self.tracker)
        return self.reflex(snapshot)

    def reflex(self, snapshot) -> DuumControls:
        """Re-apply the per-tick reflex between decisions."""

        move_bearing = self.plan.target_bearing if self.plan is not None else None
        target = None
        if self.plan is not None and self.plan.target_id is not None:
            target = next(
                (
                    monster
                    for monster in snapshot.hidden_enemies
                    if monster.id == self.plan.target_id
                ),
                None,
            )
        if target is None and (
            snapshot.navigation is not None and snapshot.navigation.reachable
        ):
            move_bearing = snapshot.navigation.bearing
        aim_bearing = None
        tolerance = None
        if target is not None:
            if target.has_los or target.direct_path:
                aim_bearing = target.bearing
            tolerance = reflex.aim_tolerance_for(target.distance)
        controls, _ = reflex.hunter_controls(
            snapshot,
            move_bearing,
            aim_bearing=aim_bearing,
            tolerance=tolerance,
            previous_movement=self._last_movement,
        )
        self._last_movement = controls.movement
        return controls
        bearing = self.plan.target_bearing
        if bearing is None and snapshot.navigation is not None and snapshot.navigation.reachable:
            bearing = snapshot.navigation.bearing
        controls, _ = reflex.hunter_controls(snapshot, bearing)
        return controls


def heuristic_controls(snapshot) -> DuumControls:
    projectile = next(
        (item for item in snapshot.incoming_projectiles if item.impact), None
    )
    target = min(
        snapshot.visible_enemies,
        key=lambda enemy: (abs(enemy.bearing), enemy.distance, enemy.id),
        default=None,
    )
    if projectile:
        movement = projectile.dodge
    elif snapshot.episode.stuck_ticks >= 60:
        movement = "back"
    elif target and target.distance < 120:
        movement = "back"
    else:
        movement = "forward"
    if target is None or abs(target.bearing) <= 0.08:
        aim = "straight"
    else:
        aim = "left" if target.bearing > 0 else "right"
    interaction = "neither"
    if (
        target
        and abs(target.bearing) <= 0.12
        and snapshot.player.weapon_ready
        and snapshot.player.ammo > 0
    ):
        interaction = "fire"
    elif snapshot.nearby_interactions and not snapshot.nearby_interactions[0].locked:
        interaction = "use"
    return DuumControls(movement, aim, interaction)
