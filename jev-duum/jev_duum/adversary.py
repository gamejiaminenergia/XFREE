"""Adversary model derived from the pinned engine's own tables.

Duum's monsters are deterministic automata: a dormant state that wakes on
sight or noise, a 0.4 s attack wind-up, a chase that re-decides every half
second and a fixed damage roll per attack kind.  The engine owns those numbers
in ``MONST`` and in the combat methods of ``engine.py``; this module turns them
into the one question a planner needs to ask:

    how many shots, how many seconds, and how much damage comes back?

Nothing here talks to the network or to the framebuffer.  Everything is derived
from the loaded engine module, so the balance mod's multipliers are honoured by
``getattr`` and the pin stays the single source of truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Player movement speed in Duum's engine (``MOVSPD``), used to turn a distance
# into arrival seconds.  Kept here so the planner never guesses.
PLAYER_SPEED = 320.0

# Monster sight/melee ranges, straight from ``run_monsters``: a dormant monster
# wakes with line of sight when it is in front or within 200 units, and any
# noise wakes it within 1000 units.
WAKE_FRONTAL_UNITS = 200.0
WAKE_NOISE_UNITS = 1000.0
MELEE_RANGE_UNITS = 70.0

# Hitscan hit probability, straight from ``monster_attack``: 0.45 at zero
# range, 0.08 at 1400 units and beyond.
HITSCAN_ZERO_RANGE_HIT = 0.45
HITSCAN_RANGE_UNITS = 1400.0
HITSCAN_MIN_HIT = 0.08

# Ranged attack cadence: the 0.4 s wind-up plus a refire lockout of at least a
# second, plus the average wait for the 25%-per-chase-tick firing roll
# (four half-second ticks).  Approximate by construction and documented as such.
RANGED_REFIRE_SECONDS = 2.4
# A melee monster inside reach attacks on every chase decision (0.4 s) after a
# 0.4 s wind-up, with no refire lockout.
MELEE_REFIRE_SECONDS = 0.8

# Per-attack damage in the pinned engine, before the balance mod:
#   melee  (1 + rnd%10) * (4 for the demon, else 3)
#   hitscan 3 * (1 + rnd%5) per pellet, three pellets for the shotgunner
#   projectile mult * (1 + rnd%8) with mult 3 (imp), 5 (caco), 8 (baron)
#   skull charge is a melee attack kind with the same 3x roll
_ATTACK_DAMAGE = {
    0: (3, 30),
    1: (3, 15),
    2: (3, 15),
    3: (3, 24),
    4: (5, 40),
    5: (8, 64),
    6: (3, 30),
}
_ATTACK_PELLETS = {0: 1, 1: 1, 2: 3, 3: 1, 4: 1, 5: 1, 6: 1}
_PINKY_DEMON = 3002  # melee roll is 4x instead of the usual 3x

# Player weapon damage, before the balance mod.  These live in the combat
# methods rather than in a table, so they are mirrored here and pinned by test.
_WEAPON_DAMAGE = {
    1: (2, 20, 1),   # fist
    2: (5, 15, 1),   # pistol
    3: (5, 15, 7),   # shotgun, seven pellets
    4: (5, 15, 1),   # chaingun
    5: (20, 160, 1),  # rocket, direct hit
    6: (5, 40, 1),   # plasma
}


def damage_multiplier(engine) -> int:
    """The player's outgoing damage multiplier (1 without the balance mod)."""

    try:
        value = int(getattr(engine, "DAMAGE_MULT", 1))
    except (TypeError, ValueError):
        return 1
    return value if value > 0 else 1


def health_multiplier(engine) -> int:
    """The player's maximum-health multiplier (1 without the balance mod)."""

    try:
        value = int(getattr(engine, "HEALTH_MULT", 1))
    except (TypeError, ValueError):
        return 1
    return value if value > 0 else 1


def _expected(low: float, high: float) -> float:
    return (low + high) / 2.0


@dataclass(frozen=True, slots=True)
class MonsterProfile:
    """One row of the engine's monster table, enriched for planning."""

    kind: int
    hp: int
    speed: float
    radius: float
    attack: int
    category: str
    damage_low: int
    damage_high: int
    pellets: int
    refire_seconds: float

    @property
    def expected_damage_per_attack(self) -> float:
        return _expected(self.damage_low, self.damage_high) * self.pellets

    @property
    def ranged(self) -> bool:
        return self.attack not in (0, 6)


@dataclass(frozen=True, slots=True)
class WeaponProfile:
    """One row of the engine's weapon table, enriched for planning."""

    slot: int
    name: str
    refire_seconds: float
    ammo_kind: int
    per_shot: int
    damage_low: int
    damage_high: int
    pellets: int

    def expected_damage(self, multiplier: int = 1) -> float:
        return _expected(self.damage_low, self.damage_high) * self.pellets * multiplier


def monster_category(engine, kind: int) -> str:
    """The snapshot's coarse category for one monster type."""

    profile = engine.MONST.get(kind)
    if profile is None:
        return "unknown"
    attack = int(profile[4])
    if attack in (0, 6):
        return "melee-enemy"
    if attack in (1, 2):
        return "hitscan-enemy"
    return "projectile-enemy"


def monster_profile(engine, kind: int) -> MonsterProfile | None:
    """Enrich one engine monster row, or ``None`` for non-monsters."""

    row = engine.MONST.get(kind)
    if row is None:
        return None
    hp, speed, radius, _pain, attack = (
        int(row[0]),
        float(row[1]),
        float(row[2]),
        int(row[3]),
        int(row[4]),
    )
    low, high = _ATTACK_DAMAGE.get(attack, (0, 0))
    if attack in (0, 6) and kind == _PINKY_DEMON:
        high = 40
    refire = MELEE_REFIRE_SECONDS if attack in (0, 6) else RANGED_REFIRE_SECONDS
    return MonsterProfile(
        kind=kind,
        hp=hp,
        speed=speed,
        radius=radius,
        attack=attack,
        category=monster_category(engine, kind),
        damage_low=int(low),
        damage_high=int(high),
        pellets=int(_ATTACK_PELLETS.get(attack, 1)),
        refire_seconds=round(float(refire), 3),
    )


def weapon_profile(engine, slot: int) -> WeaponProfile | None:
    """Enrich one engine weapon row, or ``None`` for an unknown slot."""

    row = engine.WEAP.get(slot)
    if row is None:
        return None
    low, high, pellets = _WEAPON_DAMAGE.get(slot, (0, 0, 1))
    return WeaponProfile(
        slot=int(slot),
        name=row[0].decode(errors="replace").lower(),
        refire_seconds=float(row[3]),
        ammo_kind=int(row[4]),
        per_shot=int(row[5]),
        damage_low=int(low),
        damage_high=int(high),
        pellets=int(pellets),
    )


def shots_to_kill(engine, kind: int, weapon_slot: int, *, effective: bool = True) -> int:
    """How many shots of ``weapon_slot`` finish a fresh monster of ``kind``."""

    monster = monster_profile(engine, kind)
    weapon = weapon_profile(engine, weapon_slot)
    if monster is None or weapon is None:
        return 0
    multiplier = damage_multiplier(engine) if effective else 1
    per_shot = weapon.expected_damage(multiplier)
    if per_shot <= 0:
        return 0
    return int(math.ceil(monster.hp / per_shot))


def kill_seconds(engine, kind: int, weapon_slot: int, *, effective: bool = True) -> float:
    """Seconds of trigger time needed to kill a fresh monster of ``kind``."""

    weapon = weapon_profile(engine, weapon_slot)
    if weapon is None:
        return 0.0
    shots = shots_to_kill(engine, kind, weapon_slot, effective=effective)
    # The first shot has no refire delay; the rest wait one weapon refire each.
    return round(max(1, shots) * weapon.refire_seconds, 3)


def arrival_seconds(distance: float, *, speed: float = PLAYER_SPEED) -> float:
    """Seconds to close ``distance`` at the player's run speed."""

    if distance <= 0.0 or speed <= 0.0:
        return 0.0
    return round(float(distance) / speed, 3)


def hitscan_hit_probability(distance: float) -> float:
    """The engine's own roll for a hitscan monster, clamped like the engine."""

    probability = HITSCAN_ZERO_RANGE_HIT - float(distance) / HITSCAN_RANGE_UNITS
    return max(HITSCAN_MIN_HIT, min(HITSCAN_ZERO_RANGE_HIT, probability))


def incoming_dps(engine, kind: int, distance: float, *, awake: bool = True) -> float:
    """Expected damage per second from one awake monster at ``distance``.

    Ranged monsters multiply their per-attack roll by the engine's distance
    hit probability; melee monsters only threaten inside their reach.  A
    dormant monster deals nothing at all.
    """

    monster = monster_profile(engine, kind)
    if monster is None or not awake:
        return 0.0
    if not monster.ranged:
        if distance > MELEE_RANGE_UNITS:
            return 0.0
        return round(monster.expected_damage_per_attack / max(monster.refire_seconds, 0.1), 3)
    probability = hitscan_hit_probability(distance) if monster.attack in (1, 2) else 1.0
    per_attack = monster.expected_damage_per_attack * probability
    return round(per_attack / max(monster.refire_seconds, 0.1), 3)


def wake_seconds(distance: float, *, speed: float) -> float:
    """Seconds a chasing monster needs to bring a dormant fight to contact."""

    if speed <= 0:
        return 0.0
    return round(max(0.0, float(distance) - MELEE_RANGE_UNITS) / float(speed), 3)


def kills_per_second(
    engine,
    kind: int,
    weapon_slot: int,
    distance: float,
    *,
    awake: bool,
    has_los: bool,
    direct_path: bool,
) -> float:
    """Projected kills per second for going after one monster.

    Extrapolates the exchange: walk there, aim, shoot it dead.  A monster that
    cannot be reached in a straight line is discounted because the hunt will
    have to route around geometry or open a door first; a monster that is
    already awake and looking at the player is coming here on its own.
    """

    monster = monster_profile(engine, kind)
    if monster is None:
        return 0.0
    travel = arrival_seconds(distance)
    if not direct_path:
        travel *= 2.0
    total = travel + kill_seconds(engine, kind, weapon_slot) + 0.3  # +0.3 s to acquire
    if total <= 0:
        return 0.0
    score = 1.0 / total
    if awake and has_los:
        score *= 1.5
    elif awake:
        score *= 1.2
    return round(score, 6)


__all__ = [
    "HITSCAN_MIN_HIT",
    "MELEE_REFIRE_SECONDS",
    "MELEE_RANGE_UNITS",
    "PLAYER_SPEED",
    "WAKE_FRONTAL_UNITS",
    "WAKE_NOISE_UNITS",
    "MonsterProfile",
    "WeaponProfile",
    "arrival_seconds",
    "damage_multiplier",
    "health_multiplier",
    "hitscan_hit_probability",
    "incoming_dps",
    "kill_seconds",
    "kills_per_second",
    "monster_category",
    "monster_profile",
    "shots_to_kill",
    "wake_seconds",
    "weapon_profile",
]
