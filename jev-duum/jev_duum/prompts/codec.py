"""Rebuild a snapshot from its ``to_dict`` output, for the offline harness."""

from __future__ import annotations

from ..snapshot import (
    DuumSnapshot,
    EnemySnapshot,
    EpisodeSnapshot,
    InteractionSnapshot,
    MonsterSnapshot,
    MovementOptionSnapshot,
    NavigationSnapshot,
    PickupSnapshot,
    PlayerSnapshot,
    ProjectileSnapshot,
)


def snapshot_from_dict(payload: dict) -> DuumSnapshot:
    """Rebuild a snapshot from ``DuumSnapshot.to_dict()`` output.

    The offline prompt harness stores snapshots once and derives the state for
    every prompt version from them, so it needs to reconstruct the dataclasses.
    """

    navigation = payload.get("navigation")
    hunt_route = payload.get("hunt_route")
    return DuumSnapshot(
        tick=int(payload["tick"]),
        map_name=str(payload["map_name"]),
        rng=int(payload["rng"]),
        player=PlayerSnapshot(**payload["player"]),
        visible_enemies=tuple(
            EnemySnapshot(**enemy) for enemy in payload["visible_enemies"]
        ),
        incoming_projectiles=tuple(
            ProjectileSnapshot(**projectile)
            for projectile in payload["incoming_projectiles"]
        ),
        visible_pickups=tuple(
            PickupSnapshot(**pickup) for pickup in payload["visible_pickups"]
        ),
        nearby_interactions=tuple(
            InteractionSnapshot(**interaction)
            for interaction in payload["nearby_interactions"]
        ),
        movement_options=tuple(
            MovementOptionSnapshot(**option) for option in payload["movement_options"]
        ),
        navigation=NavigationSnapshot(**navigation) if navigation else None,
        omitted_enemies=int(payload["omitted_enemies"]),
        episode=EpisodeSnapshot(**payload["episode"]),
        hidden_enemies=tuple(
            MonsterSnapshot(**monster) for monster in payload.get("hidden_enemies", ())
        ),
        hunt_route=NavigationSnapshot(**hunt_route) if hunt_route else None,
        hunt_route_target_id=payload.get("hunt_route_target_id"),
    )
