"""The live decision window: one fixed SCADA-style screen for the Jev pilot.

This package replaces the old single-file ``panel.py``.  It keeps the same
dotted path and re-exports the same names, so ``cli`` and the preview tool
import it unchanged; the code now lives in ``layout``, ``format``,
``widgets``, ``session``, ``zones``, ``dashboard`` and ``loop``."""

from __future__ import annotations

from .. import theme
from ..world_readout import read_world
from .dashboard import Dashboard
from .delta import DeltaCache
from .format import (
    _percentile,
    _questions_summary,
    _state_index,
    _threshold_color,
)
from .frame import HmiFrame, WorkerLike
from .loop import advance_completed_level, run_jev_window
from .session import SessionModel
from .widgets import Bar, DecidRow, Flag, Panel

# The panel's own tests import these names; the semantics are the ones in theme.
GREEN, AMBER, RED = theme.OK, theme.WARN, theme.ALARM

__all__ = [
    "Dashboard", "run_jev_window", "advance_completed_level",
    "Panel", "Flag", "Bar", "DecidRow", "DeltaCache",
    "HmiFrame", "WorkerLike", "SessionModel",
    "GREEN", "AMBER", "RED",
    "_percentile", "_state_index", "_questions_summary", "_threshold_color",
    "read_world",
]
