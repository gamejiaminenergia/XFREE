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


# The eight basic ANSI colours, as the terminals render them.
_ANSI_RGB = (
    (0, 0, 0), (170, 0, 0), (0, 170, 0), (170, 170, 0),
    (0, 0, 170), (170, 0, 170), (0, 170, 170), (170, 170, 170),
)
_LUT: bytearray | None = None


def _build_lut() -> bytearray:
    """Nearest basic colour for every 15-bit RGB, computed once.

    Doom's palette is browns, greys and dark reds; a rule-of-thumb mapping sent
    all of them to cyan, which turned the game view into noise.  Nearest colour
    in RGB is not subtle but it is right, and a table makes it one lookup per
    pixel instead of eight distance computations.
    """

    table = bytearray(32 * 32 * 32)
    for r5 in range(32):
        for g5 in range(32):
            for b5 in range(32):
                r, g, b = r5 * 8, g5 * 8, b5 * 8
                best, best_distance = 0, 1 << 30
                for index, (cr, cg, cb) in enumerate(_ANSI_RGB):
                    distance = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
                    if distance < best_distance:
                        best, best_distance = index, distance
                table[(r5 << 10) | (g5 << 5) | b5] = best
    return table


def basic(r: int, g: int, b: int) -> int:
    """Nearest of the eight basic colours from raw components."""

    global _LUT
    if _LUT is None:
        _LUT = _build_lut()
    return _LUT[((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)]


def to_8(color: str) -> int:
    """Nearest of the eight basic colours, for a terminal without 256."""

    return basic(*_rgb(color))


def resolve(*, colors: int) -> dict[str, int]:
    """Map every semantic key to a colour number for this terminal."""

    mapper = to_256 if colors >= 256 else to_8
    return {key: mapper(value) for key, value in FOREGROUND.items()}
