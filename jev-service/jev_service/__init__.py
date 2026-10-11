"""HTTP/WebSocket front end over the headless Jev session.

The engine lives in ``jev_duum.session``; this package only adapts it to the
web: the latest state as JSON, the latest frame as PNG, a push socket and a
small control endpoint.  It never advances the engine.
"""

from __future__ import annotations

from .app import create_app
from .hub import Hub, compact

__all__ = ["create_app", "Hub", "compact"]
