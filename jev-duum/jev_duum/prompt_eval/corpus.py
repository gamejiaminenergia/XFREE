"""Read a recorded corpus of snapshots back into the dataclasses."""

from __future__ import annotations

import json
from pathlib import Path

from ..assistance import reference_controls, reference_fire_allowed
from ..geometry import progress_scores
from ..prompts import snapshot_from_dict
from ..strategy import guide_bearing

SCHEMA = "jev-duum-prompt-eval-v1"

def load_corpus(path) -> list[dict]:
    """Read snapshots from a recording (v1/v2) or a bare list of snapshots."""

    path = Path(path).expanduser().resolve()
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        items = data.get("snapshots")
        if items is None:
            raise ValueError(f"{path} has no `snapshots` array; re-record with --record-snapshots")
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"Unsupported corpus in {path}")
    snapshots = []
    for item in items:
        payload = item.get("snapshot") if isinstance(item, dict) and "snapshot" in item else item
        if not isinstance(payload, dict) or "player" not in payload:
            raise ValueError(f"Malformed snapshot entry in {path}")
        snapshots.append(snapshot_from_dict(payload))
    return snapshots


def _reference(snapshot) -> dict:
    neutral = reference_controls(snapshot)
    ready = bool(snapshot.player.weapon_ready and snapshot.player.ammo > 0)
    progress = progress_scores(guide_bearing(snapshot))
    safe = {option.name for option in snapshot.movement_options if option.safe}
    return {
        "movement": neutral.movement,
        "aim": neutral.aim,
        "fire_allowed": reference_fire_allowed(snapshot),
        "fire_ready": ready,
        "fire_expected": reference_fire_allowed(snapshot) and ready,
        "progress": progress,
        "progress_available": any(
            progress.get(name, -1.0) > 0.05 for name in safe
        ),
        "unsafe": {
            option.name: not option.safe for option in snapshot.movement_options
        },
    }
