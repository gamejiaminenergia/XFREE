"""The screen's fixed numbers: titles, section heights and the typed axes.

``DESIGN.md`` is the prose source of truth for the layout; this module is
its single code home, so the dashboard and the zones agree on one geometry."""

from __future__ import annotations

# The palette lives in ``theme.py`` so the telemetry widgets share one source of
# truth; the names above are re-exported here unchanged for the panel's tests.
# The title's tracking and the brand marks are the only type that is not chrome.
TITLE_TEXT = "SCADA+IA+JEV+DOOM"
TITLE_SUBTITLE = "Supervisión en tiempo real · jev-1.13.0"
TITLE_PT = 22
# How often the telemetry widgets are allowed to redraw, in seconds.  The loop
# calls ``update`` every few ticks; the charts only need a few frames a second.
TELEMETRY_INTERVAL = 0.30
# How many decisions the telemetry buffers keep, and the brand type size.
TELEMETRY_POINTS = 60
# The banner's fixed height; the flexible row below it gets the rest.
BANNER_H = 54

# Height of the event list pinned to the bottom of the window.
EVENT_H = 145
# How many decisions the event list shows at once.
EVENT_ROWS = 5
# Fixed heights of the centre column's sections.  Only the decision box takes
# the slack of the window; the other three are the same size in every state.
# The threat cell: one width for the diagram's key, whatever the numbers are.
THREAT_CELL = 34
GUARD_H = 132
WHY_H = 106
STRATEGY_H = 128
SECTION_GAP = 8

# The typed questions the model answers, in the order the panel presents them.
# ``target`` only exists on the hunt prompts; the panel builds the rows it
# actually receives, so a new prompt version needs no change here.
AXES = (
    ("movement", "MOVIMIENTO", "MOV"),
    ("aim", "APUNTADO", "APU"),
    ("interaction", "ACCIÓN", "ACC"),
    ("target", "OBJETIVO", "OBJ"),
)

AXIS_ORDER = {name: index for index, (name, _, _) in enumerate(AXES)}
