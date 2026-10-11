"""The palette, translated to what a terminal can show.

``theme.py`` stays the single home of the colours; this module only maps those
hex values to ANSI colour numbers, once, and exposes the same semantic keys the
panel uses (``ok``, ``warn``, ``alarm``…).  256-colour when the terminal has it,
the eight basic colours otherwise.
"""

from __future__ import annotations

from ..theme import (
    ALARM,
    BG,
    INFO,
    OFF,
    OK,
    PANEL,
    RULE,
    STATIC,
    TITLE,
    TRACK,
    VALUE,
    WARN,
)

# The semantic keys the rest of the TUI speaks.  Same names as ``Flag.LEVELS``.
FOREGROUND = {
    "title": TITLE,
    "value": VALUE,
    "static": STATIC,
    "off": OFF,
    "ok": OK,
    "warn": WARN,
    "alarm": ALARM,
    "info": INFO,
    "rule": RULE,
    "bg": BG,
    "panel": PANEL,
    "track": TRACK,
}


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def to_256(color: str) -> int:
    """Nearest xterm-256 index for a ``#rrggbb`` colour."""

    r, g, b = _rgb(color)
    if abs(r - g) < 9 and abs(g - b) < 9:
        if r < 8:
            return 16
        if r > 238:
            return 231
        return 232 + (r - 8) // 10
    return 16 + 36 * round(r / 51) + 6 * round(g / 51) + round(b / 51)


def basic(r: int, g: int, b: int) -> int:
    """Nearest of the eight basic colours from raw components."""

    if r + g + b < 60:
        return 0
    if r > 170 and g > 170 and b > 170:
        return 7
    if r > 150 and g > 100 and b < 100:
        return 3
    if g > 150 and r < 150:
        return 2
    if g > 130 and r > 130 and b < 120:
        return 3
    if r > 150 and g < 120:
        return 1
    return 6


def to_8(color: str) -> int:
    """Nearest of the eight basic colours, for a terminal without 256."""

    return basic(*_rgb(color))


def resolve(*, colors: int) -> dict[str, int]:
    """Map every semantic key to a colour number for this terminal."""

    mapper = to_256 if colors >= 256 else to_8
    return {key: mapper(value) for key, value in FOREGROUND.items()}
