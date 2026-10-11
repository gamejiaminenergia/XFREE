"""Inference-free deterministic replay for synchronous Duum recordings."""

from __future__ import annotations

from .actions import ensure_usable_weapon
from .autopsy import DamageLog
from .integration import DUUM_COMMIT, DuumRuntime
from .recording import load_recording
from .types import DuumControls


def replay_recording(modules, wad, recording, *, width=160, height=100, damage_log=None):
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
    divergence = None
    damage = DamageLog(modules.engine) if damage_log else None
    if damage is not None:
        damage.__enter__()
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
                    divergence = {
                        "matched": False,
                        "first_divergent_tick": tick,
                        "expected": item["state"],
                        "actual": state.to_dict(),
                        "checked_checkpoints": checked,
                    }
                    break
                checked += 1
    if damage is not None:
        damage.__exit__(None, None, None)
    if divergence is not None:
        divergence["network"] = "offline"
        divergence["model_inference"] = False
        if damage is not None:
            divergence["damage_by_source"] = damage.by_source()
        return divergence
    result = {
        "matched": True,
        "first_divergent_tick": None,
        "checked_checkpoints": checked,
        "engine_ticks": final_tick,
        "final_state_hash": state.state_hash(),
        "model_inference": False,
        "network": "offline",
    }
    if damage is not None:
        result["damage_by_source"] = damage.by_source()
        result["damage_events"] = [event.to_dict() for event in damage.events]
        if not isinstance(damage_log, bool):
            damage.write(damage_log)
    return result
