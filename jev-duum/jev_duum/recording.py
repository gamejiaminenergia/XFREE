"""Portable JSON episode records containing metadata and applied controls, never assets.

Schema ``jev-duum-episode-v2`` adds an optional ``snapshots`` array.  When a run
is recorded with ``--record-snapshots`` each model decision also stores the
canonical snapshot and the exact request state, which lets prompts be compared
offline on identical states.  v1 records stay loadable for deterministic replay.
"""

from __future__ import annotations

import json
from pathlib import Path

from .prompts import DEFAULT_PROMPT_VERSION, build_state
from .strategy import StrategyTracker, compute_strategy

SCHEMA = "jev-duum-episode-v2"
LEGACY_SCHEMAS = ("jev-duum-episode-v1",)
ACCEPTED_SCHEMAS = (SCHEMA, *LEGACY_SCHEMAS)


class EpisodeRecorder:
    def __init__(
        self,
        path,
        *,
        pilot,
        duum,
        wad,
        map_name,
        tick_rate,
        decision_rate,
        model=None,
        network="offline",
        capture_snapshots=False,
    ):
        self.path = Path(path).expanduser().resolve()
        self.capture_snapshots = bool(capture_snapshots)
        self.data = {
            "schema": SCHEMA,
            "pilot": pilot,
            "network": network,
            "duum": duum,
            "wad": wad,
            "map": map_name,
            "tick_rate": tick_rate,
            "decision_rate": decision_rate,
            "model": model,
            "decisions": [],
            "controls": [],
            "checkpoints": [],
            "snapshots": [],
            "summary": None,
        }

    def decision(self, result, snapshot=None) -> None:
        self.data["decisions"].append(result.to_dict())
        if self.capture_snapshots and snapshot is not None:
            state, _ = build_state(
                snapshot,
                result.prompt_version,
                getattr(result, "strategy", None),
                getattr(result, "world_model", None),
            )
            self.capture(snapshot, result.prompt_version, state=state)

    def capture(self, snapshot, prompt_version=None, *, state=None) -> None:
        """Store one snapshot for offline prompt comparison (offline pilots included)."""

        if not self.capture_snapshots:
            return
        version = prompt_version or DEFAULT_PROMPT_VERSION
        if state is None:
            strategy = (
                compute_strategy(snapshot, StrategyTracker())
                if version in ("v3", "v3w")
                else None
            )
            state, _ = build_state(snapshot, version, strategy)
        self.data["snapshots"].append(
            {
                "tick": int(snapshot.tick),
                "prompt_version": version,
                "state": state,
                "snapshot": snapshot.to_dict(),
            }
        )

    def controls(self, tick: int, controls, mask: int) -> None:
        self.data["controls"].append(
            {
                "application_tick": int(tick),
                "controls": {
                    "movement": controls.movement,
                    "aim": controls.aim,
                    "interaction": controls.interaction,
                },
                "mask": int(mask),
            }
        )

    def checkpoint(self, state) -> None:
        self.data["checkpoints"].append(
            {"tick": state.tick, "state_hash": state.state_hash(), "state": state.to_dict()}
        )

    def finish(self, summary: dict) -> Path:
        self.data["summary"] = summary
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")
        temporary.replace(self.path)
        return self.path


def load_recording(path) -> dict:
    path = Path(path).expanduser().resolve()
    data = json.loads(path.read_text())
    if data.get("schema") not in ACCEPTED_SCHEMAS:
        raise ValueError(f"Unsupported Duum recording schema in {path}")
    return data
