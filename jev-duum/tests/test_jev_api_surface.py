"""The public import surface survives the refactor.

The modules that grow into packages (``panel``, ``snapshot``, ``prompts``,
``telemetry``, ``overlays``) keep their dotted path and re-export the names the
CLI, the preview tool and the tests already import.  This test is the contract:
if a name moves, the facade must still expose it.
"""

from __future__ import annotations

import pytest

PANEL_NAMES = (
    "Dashboard", "run_jev_window", "advance_completed_level",
    "Panel", "Flag", "Bar", "DecidRow", "DeltaCache",
    "GREEN", "AMBER", "RED",
    "_percentile", "_state_index", "_questions_summary", "_threshold_color",
    "read_world",
)
SNAPSHOT_NAMES = (
    "DuumSnapshot", "SnapshotBuilder", "PlayerSnapshot", "EnemySnapshot",
    "MonsterSnapshot", "ProjectileSnapshot", "PickupSnapshot",
    "InteractionSnapshot", "MovementOptionSnapshot", "NavigationSnapshot",
    "EpisodeSnapshot", "MAX_HUNT_TARGETS",
)
PROMPT_NAMES = (
    "PROMPT_VERSIONS", "DEFAULT_PROMPT_VERSION", "TARGET_CHOICES",
    "build_questions", "build_state", "snapshot_from_dict", "CONVENTIONS",
)
TELEMETRY_NAMES = (
    "LatencySpark", "ConfidenceSpark", "InterventionPanel", "ActionBars",
    "VitalTrace", "ConsumptionPanel", "PolicyDelta",
)
OVERLAY_NAMES = ("MiniMap", "StaleOverlay")


def _missing(module, names):
    return [name for name in names if not hasattr(module, name)]


def test_panel_exports_the_window_surface():
    from jev_duum import panel

    assert not _missing(panel, PANEL_NAMES)


def test_snapshot_exports_the_model_surface():
    from jev_duum import snapshot

    assert not _missing(snapshot, SNAPSHOT_NAMES)


def test_prompts_exports_the_request_surface():
    from jev_duum import prompts

    assert not _missing(prompts, PROMPT_NAMES)


def test_telemetry_exports_every_instrument():
    from jev_duum import telemetry

    assert not _missing(telemetry, TELEMETRY_NAMES)


def test_overlays_exports_both_widgets():
    from jev_duum import overlays

    assert not _missing(overlays, OVERLAY_NAMES)


@pytest.mark.parametrize(
    "module, names",
    [
        ("panel", PANEL_NAMES),
        ("snapshot", SNAPSHOT_NAMES),
        ("prompts", PROMPT_NAMES),
        ("telemetry", TELEMETRY_NAMES),
        ("overlays", OVERLAY_NAMES),
    ],
)
def test_module_imports_are_stable(module, names):
    import importlib

    imported = importlib.import_module(f"jev_duum.{module}")
    assert not _missing(imported, names)
