"""The canonical snapshot is frozen: the refactor may move code, not the model.

``DuumSnapshot.state_hash`` is what the recording, the replay and the prompt
corpus all agree on.  Restructuring ``snapshot.py`` must not change it, so this
pins the hash and the JSON round-trip over the deterministic snapshot from
``conftest.py``.
"""

from __future__ import annotations

from conftest import synthetic_snapshot

from jev_duum.prompts import snapshot_from_dict

# Recorded before the refactor (Fase 0 baseline); see docs/REFACTOR.md.
STATE_HASH = "06c61bb6b40a6f8b28bb772dedeb09d41d787f5300df7387434ef66229311bcf"


def test_snapshot_state_hash_is_frozen():
    assert synthetic_snapshot().state_hash() == STATE_HASH


def test_snapshot_round_trips_through_dict_unchanged():
    snapshot = synthetic_snapshot()
    rebuilt = snapshot_from_dict(snapshot.to_dict())
    assert rebuilt == snapshot
    assert rebuilt.state_hash() == STATE_HASH


def test_snapshot_dict_keeps_every_field_the_prompts_read():
    payload = synthetic_snapshot().to_dict()
    assert set(payload) == {
        "tick", "map_name", "rng", "player", "visible_enemies",
        "incoming_projectiles", "visible_pickups", "nearby_interactions",
        "movement_options", "navigation", "omitted_enemies", "episode",
        "hidden_enemies", "hunt_route", "hunt_route_target_id",
    }
    assert payload["tick"] == 750
    assert payload["player"]["ammo"] == 24
