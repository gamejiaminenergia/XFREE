"""Question-specific compact text derived from one canonical Duum snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from .snapshot import DuumSnapshot, EnemySnapshot


@dataclass(frozen=True, slots=True)
class ObservationCandidates:
    tick: int
    snapshot_hash: str
    movement: tuple[tuple[str, str], ...]
    aim: tuple[tuple[str, str], ...]
    interaction: tuple[tuple[str, str], ...]


def _enemy(enemy: EnemySnapshot, *, detail=True) -> str:
    fields = [enemy.category, enemy.bearing_word, enemy.distance_word]
    if detail:
        fields.extend(
            (
                "attacking" if enemy.attacking else "not-attacking",
                enemy.motion,
                "aligned" if enemy.aligned else "not-aligned",
                "melee-clear" if enemy.melee_reachable else "melee-blocked",
            )
        )
    return "/".join(fields)


def build_observations(snapshot: DuumSnapshot) -> ObservationCandidates:
    """Return ordered semantic reductions; no candidate drops the top threat/target."""

    player = snapshot.player
    enemies = snapshot.visible_enemies
    top_enemy = enemies[0] if enemies else None
    target = min(
        enemies,
        key=lambda enemy: (abs(enemy.bearing), enemy.distance, enemy.id),
        default=None,
    )
    projectile = snapshot.incoming_projectiles[0] if snapshot.incoming_projectiles else None
    pickup = snapshot.visible_pickups[0] if snapshot.visible_pickups else None
    interaction = snapshot.nearby_interactions[0] if snapshot.nearby_interactions else None
    route = snapshot.navigation

    danger = (
        f"projectile={projectile.bearing_word}/{projectile.distance_word}/"
        f"{'impact' if projectile.impact else 'passing'}/dodge-{projectile.dodge}"
        if projectile
        else "projectile=none"
    )
    enemy_full = f"enemy={_enemy(top_enemy)}" if top_enemy else "enemy=none"
    enemy_short = f"enemy={_enemy(top_enemy, detail=False)}" if top_enemy else "enemy=none"
    pickup_text = (
        f"pickup={pickup.category}/{pickup.bearing_word}/{pickup.distance_word}/{pickup.need}"
        if pickup
        else "pickup=none"
    )
    stuck = "stuck=yes" if snapshot.episode.stuck_ticks >= 24 else "stuck=no"
    route_text = (
        f"route={route.bearing_word}/{route.distance_word}/{route.objective}"
        if route and route.reachable
        else "route=unknown"
    )
    movement = (
        (
            "full",
            f"hp={player.health} armor={player.armor} {danger} {enemy_full} "
            f"{pickup_text} {route_text} {stuck} omitted={snapshot.omitted_enemies}",
        ),
        (
            "no-summary",
            f"hp={player.health} {danger} {enemy_full} {pickup_text} {route_text} {stuck}",
        ),
        ("compact", f"hp={player.health} {danger} {enemy_short} {route_text} {stuck}"),
        ("minimum", f"{danger} {enemy_short} {route_text}"),
    )

    if target:
        target_full = f"target={_enemy(target)}/{'aligned' if target.aligned else 'turn'}"
        target_short = f"target={_enemy(target, detail=False)}"
    else:
        target_full = target_short = (
            f"target=none route={route.bearing_word}" if route and route.reachable else "target=none"
        )
    secondary = next((enemy for enemy in enemies if target and enemy.id != target.id), None)
    secondary_text = f" secondary={_enemy(secondary)}" if secondary else ""
    aim = (
        (
            "full",
            f"weapon={player.weapon_name}/{'ready' if player.weapon_ready else 'cooldown'} "
            f"{target_full}{secondary_text}",
        ),
        ("primary", f"weapon={player.weapon_name} {target_full}"),
        ("compact", target_short),
        ("minimum", f"bearing={target.bearing_word}" if target else "target=none"),
    )

    interaction_text = (
        f"use={interaction.kind}/near/{'locked' if interaction.locked else 'ready'}"
        if interaction
        else "use=none"
    )
    shot = (
        f"shot={target.bearing_word}/{target.distance_word}/"
        f"{'aligned' if target.aligned else 'not-aligned'}"
        if target
        else "shot=none"
    )
    interaction_candidates = (
        (
            "full",
            f"weapon={player.weapon_name} ammo={player.ammo} "
            f"{'ready' if player.weapon_ready else 'cooldown'} {shot} {interaction_text}",
        ),
        (
            "compact",
            f"ammo={player.ammo} {'ready' if player.weapon_ready else 'cooldown'} "
            f"{shot} {interaction_text}",
        ),
        ("action", f"{shot} {interaction_text}"),
        ("minimum", "shot=aligned" if target and target.aligned else interaction_text),
    )
    return ObservationCandidates(
        tick=snapshot.tick,
        snapshot_hash=snapshot.state_hash(),
        movement=movement,
        aim=aim,
        interaction=interaction_candidates,
    )
