"""The whole style guide in numbers, shared by the panel and the telemetry.

``DESIGN.md`` is the prose source of truth; this module is its single code home.
It exists so ``telemetry.py`` can draw without importing ``panel.py`` (which
imports the telemetry), and so a colour is defined exactly once.
"""

from __future__ import annotations

# ── palette: nine values, and none of them decoration ────────────────────────
BG = "#000000"        # screen background: black is the transmission default
PANEL = "#0d0d0d"     # panel background, a shade above the screen
RULE = "#333333"      # 1px separators; emphasis is line weight, not colour
STATIC = "#b0b0b0"    # static text: labels, tags, table headers
TITLE = "#ffffff"     # panel headings
VALUE = "#ffffff"     # measured values, when everything is normal
OK = "#00ff00"        # in service / applied as proposed
WARN = "#ffa500"      # above a limit, guard intervention, stale data
ALARM = "#ff0000"     # alarm: no link, critical health
INFO = "#ffff00"      # reference information: limits, units, secondary
OFF = "#808080"       # out of service / no data
TRACK = "#3c3c3c"     # bargraph background (chrome, not information)

# ── palette of the schematic automap and the canvas status band ──────────────
# DESIGN.md §3.1.  Muted grays carry the geometry so the agent and the threats
# read above it; the irregular colours are the map's own alarms (exit, nukage,
# live enemy).  Kept here so no widget defines a colour of its own.
MAP_BACKDROP = "#0a0c11"
MAP_ROOM_FILL = "#111620"
MAP_ROOM_LINE = "#232d3d"
MAP_WALL = "#556077"
MAP_DOOR = "#c9a227"
MAP_EXIT = "#ef5350"
MAP_NUKAGE = "#2f6b3a"
MAP_WATER = "#1f4f6b"
MAP_PLAYER = "#65d8ff"
MAP_TARGET = "#8ee8a8"
MAP_TARGET_TURN = "#ffb74d"
MAP_TARGET_ASSISTED = "#ff7043"
MAP_ENEMY = "#ef5350"
MAP_PROJECTILE = "#ff8a80"
MAP_GUIDE = "#b388ff"
MAP_MUTED = "#8b93a7"
MAP_STALE_ERROR_BG = "#6f1a1a"
MAP_STALE_WARN_BG = "#6b3f00"
MAP_STALE_TEXT = "#ffe7c2"

# The panel's own tests import these names; the semantics are the ones above.
GREEN, AMBER, RED = OK, WARN, ALARM

# One family for everything; the value type stays monospace so figures never
# jitter (tabular by construction, no CSS to ask for).
FONTS = {"mono": "DejaVu Sans Mono", "ui": "DejaVu Sans"}
