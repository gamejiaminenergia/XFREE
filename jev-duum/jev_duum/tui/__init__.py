"""The terminal frontend: the same panel, over SSH, with no window at all.

``app`` is the curses loop and ``render`` is the pure, testable presentation;
``colors`` maps the palette in ``theme.py`` to what a terminal can show.  The
backend is ``jev_duum.session``; this package only reads its frames.
"""

from __future__ import annotations

from .app import TuiApp, run_tui

__all__ = ["TuiApp", "run_tui"]
