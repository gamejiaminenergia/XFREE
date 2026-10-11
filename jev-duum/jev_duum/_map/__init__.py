"""Vendored schematic level knowledge for Freedoom E1M1.

``sense.py`` and ``heuristics.py`` are copied verbatim from ``map/`` at the
repository root (the source of truth, stdlib only).  Only the imports were made
package-relative so they can travel inside ``jev_duum``.  Nothing here talks to
the engine: the adapter in ``jev_duum.world_model`` feeds it player coordinates
and receives plain JSON.
"""

from . import heuristics, sense

__all__ = ["heuristics", "sense"]
