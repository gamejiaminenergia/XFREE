"""Non-model pilots retained as deterministic adapter and engine baselines."""

from __future__ import annotations

import random

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
