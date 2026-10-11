"""Damage autopsy: attribute every hit to the code path that dealt it.

The recorded episode already replays deterministically, so the only thing
missing for a useful post-mortem is *who* dealt each hit.  This module wraps
the engine's damage funnels for the duration of a run and can write one JSON
line per landed hit:

    {"tick": 503, "game_time": 8.38, "source": "projectile", "requested": 12,
     "applied": 12, "health": 92, "monster_kind": 3001}

Patching is scoped: the class attributes are restored when the context exits,
so nothing else in the process can observe it.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class DamageEvent:
    tick: int
    game_time: float
    source: str
    requested: int
    applied: int
    health: int
    monster_kind: int | None = None

    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "game_time": round(self.game_time, 3),
            "source": self.source,
            "requested": self.requested,
            "applied": self.applied,
            "health": self.health,
            "monster_kind": self.monster_kind,
        }


@dataclass(slots=True)
class DamageLog:
    """Scoped instrumentation for one runtime; use as a context manager."""

    engine: object
    events: list[DamageEvent] = field(default_factory=list)
    _current: str = "other"
    _current_kind: int | None = None
    _originals: dict = field(default_factory=dict)

    def __enter__(self) -> DamageLog:
        Duum = self.engine.Duum
        self._originals = {
            "damage_player": Duum.damage_player,
            "monster_attack": Duum.monster_attack,
            "run_proj": Duum.run_proj,
            "floor_damage": Duum.floor_damage,
            "explode_barrel": Duum.explode_barrel,
        }
        log = self
        original_damage = self._originals["damage_player"]
        original_attack = self._originals["monster_attack"]
        original_projectile = self._originals["run_proj"]
        original_floor = self._originals["floor_damage"]
        original_barrel = self._originals["explode_barrel"]

        def damage_player(app, amount):
            before = int(app.health)
            result = original_damage(app, amount)
            applied = before - int(app.health)
            if applied > 0:
                log.events.append(
                    DamageEvent(
                        tick=int(app.ticks) if hasattr(app, "ticks") else 0,
                        game_time=float(app.now),
                        source=log._current,
                        requested=int(amount),
                        applied=int(applied),
                        health=int(app.health),
                        monster_kind=log._current_kind,
                    )
                )
            return result

        def monster_attack(app, thing, monster, dx, dy, dist2):
            attack = int(monster[4])
            if dist2 < 4900:
                # Inside 70 units every attack kind lands a melee blow, even
                # the ones whose ranged attack is a projectile.
                log._current, log._current_kind = "melee", int(thing[3])
            elif attack in (1, 2):
                log._current, log._current_kind = "hitscan", int(thing[3])
            else:
                log._current, log._current_kind = "projectile-spawn", int(thing[3])
            return original_attack(app, thing, monster, dx, dy, dist2)

        def run_proj(app, dt):
            log._current = "projectile"
            return original_projectile(app, dt)

        def floor_damage(app):
            log._current, log._current_kind = "floor", None
            return original_floor(app)

        def explode_barrel(app, thing):
            log._current, log._current_kind = "barrel", None
            return original_barrel(app, thing)

        Duum.damage_player = damage_player
        Duum.monster_attack = monster_attack
        Duum.run_proj = run_proj
        Duum.floor_damage = floor_damage
        Duum.explode_barrel = explode_barrel
        return self

    def __exit__(self, *exc) -> None:
        Duum = self.engine.Duum
        for name, original in self._originals.items():
            setattr(Duum, name, original)

    def by_source(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for event in self.events:
            totals[event.source] = totals.get(event.source, 0) + event.applied
        return totals

    def write(self, path) -> Path:
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w") as stream:
            for event in self.events:
                stream.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        return target


__all__ = ["DamageEvent", "DamageLog"]


def main(argv=None) -> int:
    """``jev-duum-autopsy <recording>``: replay it and attribute every hit."""

    import argparse
    from pathlib import Path as _Path

    from .integration import default_duum_checkout, load_duum
    from .replay import replay_recording
    from .wad import default_wad_path, resolve_wad

    parser = argparse.ArgumentParser(
        prog="jev-duum-autopsy",
        description=(
            "Replay a synchronous Duum recording deterministically and attribute every "
            "point of damage to its source (hitscan, projectile, melee, floor, barrel)."
        ),
    )
    parser.add_argument("recording", type=_Path)
    parser.add_argument("--wad", type=_Path, default=default_wad_path())
    parser.add_argument("--duum-path", type=_Path, default=default_duum_checkout())
    parser.add_argument(
        "--output",
        type=_Path,
        default=None,
        help="Write every landed hit as one JSON line to this path",
    )
    args = parser.parse_args(argv)
    try:
        modules = load_duum(args.duum_path)
        wad = resolve_wad(args.wad)
    except Exception as error:  # noqa: BLE001 - surface the loader's own message
        parser.error(str(error))
    result = replay_recording(
        modules, wad, args.recording, damage_log=args.output or True
    )
    events = result.pop("damage_events", [])
    summary = {
        "recording": str(_Path(args.recording).expanduser().resolve()),
        "matched": result.get("matched"),
        "engine_ticks": result.get("engine_ticks"),
        "damage_by_source": result.get("damage_by_source", {}),
        "total_damage": sum(result.get("damage_by_source", {}).values()),
        "hits": len(events),
        "first_hits": events[:5],
        "output": str(args.output) if args.output else None,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if result.get("matched") else 1


if __name__ == "__main__":  # pragma: no cover - exercised through the entry point
    sys.exit(main())
