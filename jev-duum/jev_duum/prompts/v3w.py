"""``v3w``: the v3 plan plus the schematic world model from ``map/``."""

from __future__ import annotations

from .v3 import V3_QUESTIONS

# ── v3w: the v3 plan plus the schematic world model from `map/` ────────────

_WORLD_MODEL_NOTE = (
    "`state.world_model` is informative, not authoritative: it comes from a "
    "schematic map of the level and may be approximate. The visible state and "
    "the deterministic guard always win."
)

_WORLD_MODEL_RULES = {
    "movement": [
        _WORLD_MODEL_NOTE,
        "If `world_model.hazards.nukage` is true or `world_model.sector_risk.worst_risk` is above 0.5, leave the hazard: pick a safe direction with lower risk.",
        "`world_model.hidden_items.top_aspirations` lists pickups the snapshot cannot see; treat the top entry as a detour candidate when health is low.",
    ],
    "aim": [
        _WORLD_MODEL_NOTE,
        "`world_model.hidden_foes` counts enemies you cannot see; never turn for one that is not in `strategy.focus`.",
    ],
    "interaction": [_WORLD_MODEL_NOTE],
}


def _with_world_model(questions: dict) -> dict:
    expanded = {}
    for name, question in questions.items():
        instructions = dict(question["instructions"])
        instructions["rules"] = list(instructions["rules"]) + _WORLD_MODEL_RULES[name]
        expanded[name] = {**question, "instructions": instructions}
    return expanded


V3W_QUESTIONS = _with_world_model(V3_QUESTIONS)

