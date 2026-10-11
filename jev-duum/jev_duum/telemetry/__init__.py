"""Session telemetry for the decision HMI: fixed-size canvases, bounded series.

This package replaces the old single-file ``telemetry.py``.  It keeps the
same dotted path and re-exports the same instruments; the code now lives in
``canvas``, ``sparks``, ``bars``, ``series`` and ``policy``."""

from __future__ import annotations

from .bars import ActionBars, InterventionPanel
from .policy import PolicyDelta
from .series import ConsumptionPanel, VitalTrace
from .sparks import ConfidenceSpark, LatencySpark

__all__ = [
    "LatencySpark", "ConfidenceSpark", "InterventionPanel", "ActionBars",
    "VitalTrace", "ConsumptionPanel", "PolicyDelta",
]
