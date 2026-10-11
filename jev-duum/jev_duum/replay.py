"""Inference-free deterministic replay for synchronous Duum recordings."""

from __future__ import annotations

from .actions import ensure_usable_weapon
from .integration import DUUM_COMMIT, DuumRuntime
from .recording import load_recording
from .types import DuumControls


def replay_recording(modules, wad, recording, *, width=160, height=100):
    data = load_recording(recording) if not isinstance(recording, dict) else recording
    if data["duum"]["commit"] != DUUM_COMMIT:
        raise ValueError("Recording uses a different Duum commit")
    if data["wad"]["sha256"] != wad.sha256:
        raise ValueError("Recording WAD checksum does not match the supplied WAD")
    if not data.get("summary") or data["summary"].get("mode") != "synchronous":
        raise ValueError("Only synchronous recordings support deterministic regeneration")
    controls_by_tick = {
        int(item["application_tick"]): DuumControls(**item["controls"])
        for item in data["controls"]
    }
    expected = {int(item["tick"]): item for item in data["checkpoints"]}
    final_tick = int(data["summary"]["engine_ticks"])
    controls = DuumControls()
    checked = 0
    with DuumRuntime(modules, wad.path, data["map"], width, height) as runtime:
        for tick in range(1, final_tick + 1):
            controls = controls_by_tick.get(tick, controls)
            if data.get("pilot") == "jev-assisted":
                ensure_usable_weapon(runtime.app, modules.engine)
            state, _, _ = runtime.step(controls)
            item = expected.get(tick)
            if item is not None:
                actual = state.state_hash()
                if actual != item["state_hash"]:
                    return {
                        "matched": False,
                        "first_divergent_tick": tick,
                        "expected": item["state"],
                        "actual": state.to_dict(),
                        "checked_checkpoints": checked,
                    }
                checked += 1
    return {
        "matched": True,
        "first_divergent_tick": None,
        "checked_checkpoints": checked,
        "engine_ticks": final_tick,
        "final_state_hash": state.state_hash(),
        "model_inference": False,
        "network": "offline",
    }
