"""The request state: one snapshot rendered into the named fields a prompt
version travels with.

``build_state`` is the single entry point; the per-version shape is chosen
by the frozen question definitions, never by the panel."""

from __future__ import annotations

import math

from ..observation import build_observations
from ..snapshot import (
    DuumSnapshot,
)
from .conventions import (
    CONVENTIONS,
    ROUTE_AIM_TOLERANCE_DEGREES,
    ROUTE_FORWARD_TOLERANCE_DEGREES,
)
from .questions import PROMPT_VERSIONS
from .v4 import TARGET_CHOICES


def _degrees(radians: float) -> float:
    return round(math.degrees(radians), 1)


def _movement_options(
    snapshot: DuumSnapshot, progress: dict[str, float] | None = None
) -> dict:
    options = {
        option.name: {
            "safe": bool(option.safe),
            "clear_distance_units": round(float(option.clear_distance), 1),
        }
        for option in snapshot.movement_options
    }
    if progress:
        for name, value in options.items():
            value["progress"] = progress.get(name)
    options.setdefault(
        "hold",
        {
            "safe": True,
            "clear_distance_units": 0.0,
            "note": "standing still cannot collide",
            **({"progress": 0.0} if progress else {}),
        },
    )
    return options


def _threats(snapshot: DuumSnapshot, relevant_ids: tuple[int, ...] | None = None) -> list:
    return [
        {
            "id": enemy.id,
            "kind": enemy.category,
            "bearing_degrees": _degrees(enemy.bearing),
            "bearing_word": enemy.bearing_word,
            "distance_units": round(float(enemy.distance), 1),
            "distance_word": enemy.distance_word,
            "attacking": bool(enemy.attacking),
            "active": bool(enemy.active),
            "shot_would_hit": bool(enemy.aligned),
            "melee_reachable": bool(enemy.melee_reachable),
            "motion": enemy.motion,
            **(
                {"relevant": enemy.id in relevant_ids}
                if relevant_ids is not None
                else {}
            ),
        }
        for enemy in snapshot.visible_enemies
    ]


def _projectiles(snapshot: DuumSnapshot) -> list:
    return [
        {
            "bearing_degrees": _degrees(projectile.bearing),
            "distance_units": round(float(projectile.distance), 1),
            "impact": bool(projectile.impact),
            "impact_in_seconds": round(float(projectile.impact_time), 2),
            "dodge": projectile.dodge,
        }
        for projectile in snapshot.incoming_projectiles
    ]


def _pickups(snapshot: DuumSnapshot) -> list:
    return [
        {
            "category": pickup.category,
            "bearing_degrees": _degrees(pickup.bearing),
            "distance_units": round(float(pickup.distance), 1),
            "need": pickup.need,
        }
        for pickup in snapshot.visible_pickups
    ]


def _geometry(snapshot: DuumSnapshot) -> list:
    return [
        {
            "kind": interaction.kind,
            "distance_units": round(float(interaction.distance), 1),
            "locked": bool(interaction.locked),
            "required_key": interaction.required_key,
        }
        for interaction in snapshot.nearby_interactions
    ]


def _objective(snapshot: DuumSnapshot) -> dict | None:
    route = snapshot.navigation
    if route is None:
        return None
    return {
        "kind": route.objective,
        "bearing_degrees": _degrees(route.bearing),
        "bearing_word": route.bearing_word,
        "distance_units": round(float(route.distance), 1),
        "route_length": int(route.route_length),
        "reachable": bool(route.reachable),
        "use_when_near": bool(route.use_when_near),
        "aim_tolerance_degrees": ROUTE_AIM_TOLERANCE_DEGREES,
        "forward_tolerance_degrees": ROUTE_FORWARD_TOLERANCE_DEGREES,
    }


def _hunt_state(hunt) -> dict | None:
    """The hunt order that travels in ``v4``: the mission, the numbers, the picks."""

    if hunt is None:
        return None
    if isinstance(hunt, dict):
        # A recorded hunt block replays verbatim.
        return hunt
    candidates = []
    for index, monster in enumerate(hunt.candidates[:3]):
        candidates.append(
            {
                "choice": TARGET_CHOICES[index],
                "id": monster.id,
                "kind": monster.category,
                "bearing_degrees": _degrees(monster.bearing),
                "bearing_word": monster.bearing_word,
                "distance_units": round(float(monster.distance), 1),
                "distance_word": monster.distance_word,
                "hp_fraction": monster.hp_fraction,
                "awake": bool(monster.awake),
                "attacking": bool(monster.attacking),
                "shot_would_hit": bool(monster.aligned),
                "shots_to_kill": int(monster.shots_to_kill),
                "kill_seconds": round(float(monster.kill_seconds), 2),
                "arrival_seconds": round(float(monster.arrival_seconds), 2),
                "kills_per_second": monster.kills_per_second,
                "route_reachable": (
                    bool(hunt.route_reachable) if monster.id == hunt.target_id else None
                ),
            }
        )
    return {
        "mission": hunt.objective,
        "monsters_remaining": hunt.monsters_remaining,
        "monsters_awake": hunt.monsters_awake,
        "unique_sectors": hunt.unique_sectors,
        "chosen_target_id": hunt.target_id,
        "target_bearing_degrees": (
            None
            if hunt.target_bearing is None
            else _degrees(hunt.target_bearing)
        ),
        "target_distance_units": (
            None if hunt.target_distance is None else round(hunt.target_distance, 1)
        ),
        "rationale": hunt.rationale,
        "candidates": candidates,
    }


def _adversary_state(snapshot: DuumSnapshot) -> list:
    """Per-threat combat arithmetic for the visible enemies (``v4`` only)."""

    catalogue = {monster.id: monster for monster in snapshot.hidden_enemies}
    threats = []
    for enemy in snapshot.visible_enemies:
        monster = catalogue.get(enemy.id)
        threats.append(
            {
                "id": enemy.id,
                "kind": enemy.category,
                "shots_to_kill": monster.shots_to_kill if monster else None,
                "kill_seconds": (
                    round(float(monster.kill_seconds), 2) if monster else None
                ),
                "kills_per_second": monster.kills_per_second if monster else None,
                "hp_fraction": monster.hp_fraction if monster else None,
                "awake": bool(monster.awake) if monster else bool(enemy.active),
            }
        )
    return threats


def _structured_state(snapshot: DuumSnapshot, strategy=None, hunt=None) -> dict:
    player = snapshot.player
    episode = snapshot.episode
    if isinstance(strategy, dict):
        # A recorded strategy block can be replayed verbatim.
        block = strategy
        relevant_ids = tuple(strategy.get("relevant_threat_ids") or ())
        progress = strategy.get("progress") or None
    elif strategy is not None:
        block = strategy.to_dict()
        relevant_ids = strategy.relevant_threat_ids
        progress = strategy.progress
    else:
        block = None
        relevant_ids = None
        progress = None
    state = {
        "tick": snapshot.tick,
        "map": snapshot.map_name,
        "conventions": CONVENTIONS,
        "player": {
            "health": int(player.health),
            "armor": int(player.armor),
            "weapon": player.weapon_name,
            "ammo": int(player.ammo),
            "weapon_ready": bool(player.weapon_ready),
            "keys": int(player.keys),
        },
        "objective": _objective(snapshot),
        "threats": _threats(snapshot, relevant_ids),
        "projectiles_inbound": _projectiles(snapshot),
        "pickups": _pickups(snapshot),
        "usable_geometry": _geometry(snapshot),
        "movement_options": _movement_options(snapshot, progress),
        "situation": {
            "stuck": bool(episode.stuck_ticks >= 24),
            "game_time": round(float(episode.game_time), 1),
            "damage_received": int(episode.damage_received),
            "kills": int(episode.kills),
            "items": int(episode.items),
            "unique_sectors": int(episode.unique_sectors),
            "live_enemies": int(episode.live_enemies),
            "omitted_enemies": int(snapshot.omitted_enemies),
            "dead": bool(episode.dead),
            "finished": bool(episode.finished),
        },
    }
    if block is not None:
        state["strategy"] = block
    if hunt is not None:
        state["hunt"] = _hunt_state(hunt)
        state["adversary"] = _adversary_state(snapshot)
    return state


def _legacy_state(snapshot: DuumSnapshot) -> tuple[dict, dict[str, str]]:
    candidates = build_observations(snapshot)
    observations = {
        name: getattr(candidates, name)[0][1]
        for name in ("movement", "aim", "interaction")
    }
    state = {
        "tick": candidates.tick,
        "map": snapshot.map_name,
        "movement": observations["movement"],
        "aim": observations["aim"],
        "interaction": observations["interaction"],
    }
    return state, observations


def build_state(
    snapshot: DuumSnapshot,
    version: str,
    strategy=None,
    world_model: dict | None = None,
    hunt=None,
) -> tuple[dict, dict[str, str]]:
    """Return ``(state, observations)`` for one snapshot and prompt version.

    ``observations`` stays the short human summary the Tk panel already renders,
    independent of the version.  ``state`` is what actually travels to Jev.
    """

    if version not in PROMPT_VERSIONS:
        raise ValueError(f"unknown prompt version: {version}")
    legacy_state, observations = _legacy_state(snapshot)
    if version == "v1":
        return legacy_state, observations
    if version == "v2":
        return _structured_state(snapshot), observations
    if version == "v4":
        if strategy is None:
            raise ValueError("prompt v4 needs a strategy")
        return _structured_state(snapshot, strategy, hunt), observations
    if strategy is None:
        raise ValueError(f"prompt {version} needs a strategy")
    state = _structured_state(snapshot, strategy)
    if version == "v3w":
        # Fail-soft: the adapter may return None and the prompt still works.
        state["world_model"] = world_model
    return state, observations
