"""Immutable semantic snapshots derived from Duum's authoritative state.

This package replaces the old single-file ``snapshot.py``.  It keeps the same dotted path and re-exports the same names, so every caller imports it unchanged; the code now lives in ``models``, ``geometry``, ``entities``, ``navigation`` and ``builder``."""

from __future__ import annotations

from .builder import SnapshotBuilder
from .geometry import _angle, _bearing_word, _distance_word
from .models import (
    MAX_HUNT_TARGETS,
    DuumSnapshot,
    EnemySnapshot,
    EpisodeSnapshot,
    InteractionSnapshot,
    MonsterSnapshot,
    MovementOptionSnapshot,
    NavigationSnapshot,
    PickupSnapshot,
    PlayerSnapshot,
    ProjectileSnapshot,
)

__all__ = [
    "SnapshotBuilder", "MAX_HUNT_TARGETS",
    "DuumSnapshot", "PlayerSnapshot", "EnemySnapshot", "MonsterSnapshot",
    "ProjectileSnapshot", "PickupSnapshot", "InteractionSnapshot",
    "MovementOptionSnapshot", "NavigationSnapshot", "EpisodeSnapshot",
    "_angle", "_bearing_word", "_distance_word",
]
