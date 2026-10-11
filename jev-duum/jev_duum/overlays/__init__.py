"""Tk overlays for the game view: the schematic automap and the stale HUD.

This package replaces the old single-file ``overlays.py``.  It keeps the same
dotted path and re-exports both widgets; the code now lives in ``minimap``
and ``stale``."""

from __future__ import annotations

from .minimap import MiniMap, _risk_color
from .stale import StaleOverlay

__all__ = ["MiniMap", "StaleOverlay", "_risk_color"]
