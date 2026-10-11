"""Balance mod for the pinned Duum engine: 10x life, 10x damage, 20x ammo.

The engine is an external, pinned dependency (never vendored), so this is a
*reproducible, reversible patch* applied to whatever checkout you are running —
not a hand edit. ``apply`` is idempotent and also *upgrades* an older version of
the block (change the multipliers below and re-run it).

    python3 mods/balance.py --duum /path/to/duum          # apply / update
    python3 mods/balance.py --duum /path/to/duum --check   # report only
    python3 mods/balance.py --duum /path/to/duum --revert  # undo

What it changes in ``duum/engine.py``:

1. adds ``HEALTH_MULT = 10``, ``DAMAGE_MULT = 10``, ``AMMO_MULT = 20`` and
   ``PLAYER_MAXHEALTH = 100 * HEALTH_MULT``;
2. the player starts with ``PLAYER_MAXHEALTH`` health and a full clip of
   ``AMMO_MULT`` starting bullets, with every ammo cap raised ``AMMO_MULT``x;
3. ``damage_monster`` multiplies every hit the player lands (hitscan, melee,
   projectiles, splash, barrels);
4. health pickups cap at the new maximum (otherwise a 1000 HP player could
   never pick up a medikit again);
5. ammo pickups, weapon pickups and the backpack all grant ``AMMO_MULT``x;
6. the status-bar face scales against the new maximum instead of 100.
7. with 4-digit health (>= 1000) the ammo counter slides left, because the
   original status bar only reserves room for three digits.

It does not touch the repository's git HEAD, so the adapter's pin check still
passes. Revert with ``--revert`` or ``git -C <duum> checkout -- duum/engine.py``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER_PREFIX = "# ---- balance mod"
MARKER = f"{MARKER_PREFIX} (10x life / 10x damage / 20x ammo, see mods/balance.py) ----"

CONSTANTS = (
    f"{MARKER}\n"
    "HEALTH_MULT = 10                # player max health multiplier\n"
    "DAMAGE_MULT = 10                # damage the player deals multiplier\n"
    "AMMO_MULT = 20                  # ammunition the player gets multiplier\n"
    "PLAYER_MAXHEALTH = 100 * HEALTH_MULT\n"
)

# The marker line plus the assignment block it introduces, whatever the values.
BLOCK = re.compile(r"# ---- balance mod[^\n]*\n(?:[A-Z_]+ = [^\n]*\n)+")

# Anchor the block goes right after; stable across the pinned engine.
ANCHOR = 'WADNAME = "DOOM1.WAD"\nLEVEL = "E1M1"\n'

EDITS = (
    (
        "max health on spawn",
        "        self.health = 100; self.armor = 0\n",
        "        self.health = PLAYER_MAXHEALTH; self.armor = 0\n",
    ),
    (
        "starting ammo and ammo caps",
        "        self.ammo = [0, 50, 0, 0, 0]\n"
        "        self.maxammo = list(AMMOMAX)\n",
        "        self.ammo = [0, 50 * AMMO_MULT, 0, 0, 0]\n"
        "        self.maxammo = [m * AMMO_MULT for m in AMMOMAX]\n",
    ),
    (
        "double the player's damage",
        "    def damage_monster(self, t, d):\n        ms = MONST.get(t[3])\n",
        "    def damage_monster(self, t, d):\n"
        "        d = int(d * DAMAGE_MULT)\n"
        "        ms = MONST.get(t[3])\n",
    ),
    (
        "health pickups cap at the new maximum",
        "        if kind == 0:\n"
        "            if self.health >= b and a > 1:\n"
        "                return False\n"
        "            self.health = min(self.health + a, b)\n",
        "        if kind == 0:\n"
        "            b = min(b * HEALTH_MULT, PLAYER_MAXHEALTH)\n"
        "            if self.health >= b and a > 1:\n"
        "                return False\n"
        "            self.health = min(self.health + a, b)\n",
    ),
    (
        "ammo pickups are worth AMMO_MULT",
        "        elif kind == 3:\n"
        "            if self.ammo[a] >= self.maxammo[a]:\n"
        "                return False\n"
        "            self.ammo[a] = min(self.ammo[a] + b, self.maxammo[a])\n",
        "        elif kind == 3:\n"
        "            b = b * AMMO_MULT\n"
        "            if self.ammo[a] >= self.maxammo[a]:\n"
        "                return False\n"
        "            self.ammo[a] = min(self.ammo[a] + b, self.maxammo[a])\n",
    ),
    (
        "weapon pickups grant AMMO_MULT ammo",
        "            self.ammo[w[4]] = min(self.ammo[w[4]] + b * 2,"
        " self.maxammo[w[4]])\n",
        "            self.ammo[w[4]] = min(self.ammo[w[4]] + b * 2 * AMMO_MULT,"
        " self.maxammo[w[4]])\n",
    ),
    (
        "backpack grants AMMO_MULT ammo and caps",
        "            for i in range(1, 5):\n"
        "                self.maxammo[i] = AMMOMAX[i] * 2\n"
        "                self.ammo[i] = min(self.ammo[i] + (10, 4, 1, 20)[i - 1],\n"
        "                                   self.maxammo[i])\n",
        "            for i in range(1, 5):\n"
        "                self.maxammo[i] = AMMOMAX[i] * 2 * AMMO_MULT\n"
        "                self.ammo[i] = min(\n"
        "                    self.ammo[i] + (10, 4, 1, 20)[i - 1] * AMMO_MULT,\n"
        "                    self.maxammo[i])\n",
    ),
    (
        "status-bar face scales with the new maximum",
        "            pain = (100 - self.health) * 5 // 101\n",
        "            pain = max(0, (PLAYER_MAXHEALTH - self.health) * 5"
        " // (PLAYER_MAXHEALTH + 1))\n",
    ),
    (
        "status bar makes room for 4-digit health",
        "        num(self.ammo[wk], 44, 3)\n",
        "        num(self.ammo[wk], 30 if self.health > 999 else 44, 3)\n",
    ),
)


def engine_path(duum) -> Path:
    candidate = Path(duum).expanduser() / "duum" / "engine.py"
    if not candidate.is_file():
        raise SystemExit(f"not a Duum checkout (no duum/engine.py): {duum}")
    return candidate


def is_applied(text: str) -> bool:
    return MARKER_PREFIX in text


def _set_block(text: str) -> str:
    """Insert or update the constants block; leaves it exactly once."""

    if BLOCK.search(text):
        return BLOCK.sub(CONSTANTS, text, count=1)
    if text.count(ANCHOR) != 1:
        raise SystemExit(
            "balance mod: cannot find the constants anchor; the engine changed"
        )
    return text.replace(ANCHOR, ANCHOR + "\n" + CONSTANTS, 1)


def apply(duum) -> str:
    """Patch the engine. Returns 'applied', 'updated' or 'already applied'."""

    path = engine_path(duum)
    text = path.read_text(encoding="utf-8")
    had_block = bool(BLOCK.search(text))
    current = had_block and BLOCK.search(text).group(0) == CONSTANTS
    body_done = all(new in text for _, _, new in EDITS)
    if current and body_done:
        return "already applied"

    text = _set_block(text)
    for label, old, new in EDITS:
        if new in text:
            continue
        if text.count(old) != 1:
            raise SystemExit(
                f"balance mod: cannot find exactly one '{label}' anchor in {path} "
                f"(found {text.count(old)}); the engine changed, update mods/balance.py"
            )
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    return "updated" if had_block else "applied"


def revert(duum) -> bool:
    """Remove the mod. Returns False when it was not there."""

    path = engine_path(duum)
    text = path.read_text(encoding="utf-8")
    if not is_applied(text):
        return False
    for label, old, new in reversed(EDITS):
        if new not in text:
            raise SystemExit(
                f"balance mod: cannot cleanly revert '{label}' in {path}; "
                f"use `git -C {duum} checkout -- duum/engine.py`"
            )
        text = text.replace(new, old, 1)
    text = BLOCK.sub("", text, count=1)
    text = text.replace(ANCHOR + "\n" + ANCHOR, ANCHOR)  # defensive no-op
    path.write_text(text, encoding="utf-8")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--duum", required=True, type=Path, help="Duum checkout path")
    parser.add_argument("--check", action="store_true", help="report state, change nothing")
    parser.add_argument("--revert", action="store_true", help="remove the mod")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    path = engine_path(args.duum)
    text = path.read_text(encoding="utf-8")
    if args.check:
        state = "applied" if is_applied(text) else "not applied"
        if not args.quiet:
            print(f"balance mod: {state} in {path}")
        return 0 if is_applied(text) else 1
    if args.revert:
        changed = revert(args.duum)
        if not args.quiet:
            print(f"balance mod: {'reverted' if changed else 'was not applied'} in {path}")
        return 0
    result = apply(args.duum)
    if not args.quiet:
        print(
            f"balance mod: {result} (10x health, 10x damage, 20x ammo) in {path}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
