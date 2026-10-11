"""Portable JSON episode records containing metadata and applied controls, never assets."""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "jev-duum-episode-v1"


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
    ):
        self.path = Path(path).expanduser().resolve()
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
            "summary": None,
        }

    def decision(self, result) -> None:
        self.data["decisions"].append(result.to_dict())

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
    if data.get("schema") != SCHEMA:
        raise ValueError(f"Unsupported Duum recording schema in {path}")
    return data
