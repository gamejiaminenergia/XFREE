"""The immutable semantic snapshot types the whole adapter agrees on.

Frozen and slotted: a snapshot is a value, never mutated, and its ``state_hash`` is what the recording, the replay and the prompt corpus agree on."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

# The hunt catalogue is truncated so pathological maps stay bounded; E1M1's 29
# monsters all fit.  The prompt only ever quotes a plan's top three candidates.
MAX_HUNT_TARGETS = 32

@dataclass(frozen=True, slots=True)
class PlayerSnapshot:
    x: float
    y: float
    angle: float
    health: int
    armor: int
    weapon: int
    weapon_name: str
    ammo: int
    weapon_ready: bool
    keys: int
    damage_since_last: int
    # The engine's own maximum, so a balance mod that raises it still draws a
    # meaningful bar. Vanilla Duum reports 100; the optional mod reports 300.
    max_health: int = 100


@dataclass(frozen=True, slots=True)
class EnemySnapshot:
    id: int
    category: str
    bearing: float
    bearing_word: str
    distance: float
    distance_word: str
    visible: bool
    attacking: bool
    active: bool
    melee_reachable: bool
    aligned: bool
    motion: str
    threat: float


@dataclass(frozen=True, slots=True)
class MonsterSnapshot:
    """One live monster anywhere on the level, visible or not.

    This is the adversary catalogue: the engine knows every ``things_live``
    entry, dormant included, so the planner can decide where to hunt instead of
    waiting for a monster to walk into the camera.  ``kills_per_second`` is the
    shared extrapolation number: the code ranks with it and the prompt quotes
    it.
    """

    id: int
    kind: int
    category: str
    x: float
    y: float
    bearing: float
    bearing_word: str
    distance: float
    distance_word: str
    hp: int
    hp_fraction: float
    awake: bool
    attacking: bool
    has_los: bool
    direct_path: bool
    aligned: bool
    shots_to_kill: int
    kill_seconds: float
    arrival_seconds: float
    kills_per_second: float


@dataclass(frozen=True, slots=True)
class ProjectileSnapshot:
    id: int
    bearing: float
    bearing_word: str
    distance: float
    distance_word: str
    impact_time: float
    impact: bool
    dodge: str
    threat: float


@dataclass(frozen=True, slots=True)
class PickupSnapshot:
    id: int
    category: str
    bearing: float
    bearing_word: str
    distance: float
    distance_word: str
    need: str


@dataclass(frozen=True, slots=True)
class InteractionSnapshot:
    kind: str
    distance: float
    locked: bool
    required_key: str | None


@dataclass(frozen=True, slots=True)
class MovementOptionSnapshot:
    name: str
    clear_distance: float
    safe: bool


@dataclass(frozen=True, slots=True)
class NavigationSnapshot:
    objective: str
    bearing: float
    bearing_word: str
    distance: float
    distance_word: str
    next_sector: int | None
    route_length: int
    reachable: bool
    use_when_near: bool


@dataclass(frozen=True, slots=True)
class EpisodeSnapshot:
    game_time: float
    kills: int
    items: int
    damage_received: int
    live_enemies: int
    projectiles: int
    unique_sectors: int
    stuck_ticks: int
    idle_ticks: int
    dead: bool
    finished: bool
    monsters_remaining: int = 0
    monsters_awake: int = 0


@dataclass(frozen=True, slots=True)
class DuumSnapshot:
    tick: int
    map_name: str
    rng: int
    player: PlayerSnapshot
    visible_enemies: tuple[EnemySnapshot, ...]
    incoming_projectiles: tuple[ProjectileSnapshot, ...]
    visible_pickups: tuple[PickupSnapshot, ...]
    nearby_interactions: tuple[InteractionSnapshot, ...]
    movement_options: tuple[MovementOptionSnapshot, ...]
    navigation: NavigationSnapshot | None
    omitted_enemies: int
    episode: EpisodeSnapshot
    hidden_enemies: tuple[MonsterSnapshot, ...] = ()
    hunt_route: NavigationSnapshot | None = None
    hunt_route_target_id: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def state_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()
