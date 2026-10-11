"""Small deterministic engine checkpoints used before canonical snapshots exist."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class EngineCheckpoint:
    tick: int
    game_time: float
    map_name: str
    player_x: float
    player_y: float
    player_angle: float
    health: int
    armor: int
    weapon: int
    ammo: tuple[int, ...]
    keys: int
    rng: int
    dead: bool
    finished: bool
    live_things: int
    projectiles: int
    movers: int

    def to_dict(self) -> dict:
        return asdict(self)

    def state_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


def checkpoint(app, tick: int) -> EngineCheckpoint:
    values = (app.now, app.px, app.py, app.pa)
    if not all(math.isfinite(value) for value in values):
        raise FloatingPointError("Duum returned a non-finite authoritative state")
    return EngineCheckpoint(
        tick=tick,
        game_time=float(app.now),
        map_name=str(app.level),
        player_x=float(app.px),
        player_y=float(app.py),
        player_angle=float(app.pa),
        health=int(app.health),
        armor=int(app.armor),
        weapon=int(app.weapon),
        ammo=tuple(int(value) for value in app.ammo),
        keys=int(app.keys),
        rng=int(app.rng),
        dead=bool(app.dead),
        finished=app.finish is not None,
        live_things=len(app.things_live),
        projectiles=len(app.proj),
        movers=len(app.movers),
    )
