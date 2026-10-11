"""``v3``: the v2 rubrics plus the code-owned strategy and per-option progress."""

from __future__ import annotations

from .conventions import _SEE

_MOVEMENT_V3_INSTRUCTIONS = {
    "role": "You execute a plan the code already made; your job is the tactical step.",
    "task": "Pick the movement that executes `strategy.plan` for this decision.",
    "rules": [
        "The mission and the plan are fixed data: execute them, do not replace them.",
        "Never choose a movement whose `safe` flag is false.",
        "`movement_options.<name>.progress` is how much that direction closes the distance to `strategy.guide_bearing_degrees`: 1 aims straight at it, 0 is sideways, negative walks away.",
        "If `strategy.must_move` is true, `hold` is forbidden: choose the safe option with the highest positive `progress`.",
        "If `strategy.must_move` is false, `hold` is allowed only when no safe direction makes progress or the plan is to use the geometry ahead.",
        "An entry in `projectiles_inbound` with `impact` true means dodge: move in its `dodge` direction when that direction is safe.",
        "Diagonals (`forward_left`, `forward_right`, `back_left`, `back_right`) combine forward or back with a strafe: prefer the diagonal when it has strictly more `progress` than either single axis.",
        "Firing is a separate question; keep the player moving while it fights.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which movement executes the plan now?",
}

_MOVEMENT_V3_CRITERIA = {
    "forward": {
        "what": "Step forward along the current facing.",
        "use_when": "`forward.safe` is true and forward has the highest positive `progress`, or the objective is already within its aim tolerance.",
        "not_for": "`forward.safe` is false, or another safe direction has clearly more progress.",
    },
    "back": {
        "what": "Walk backwards.",
        "use_when": "a threat attacks at contact distance, `back.safe` is true and retreating is the plan (low health), or `back` has the highest positive progress toward a goal directly behind.",
        "not_for": "the objective is ahead; backing up then walks away from the mission.",
    },
    "strafe_left": {
        "what": "Side-step left while the aim keeps turning.",
        "use_when": "`strafe_left.safe` is true and it has the highest positive `progress`, or the plan is to dodge a projectile to the left.",
        "not_for": "`strafe_left.safe` is false, or its progress is zero and forward makes progress.",
    },
    "strafe_right": {
        "what": "Side-step right while the aim keeps turning.",
        "use_when": "`strafe_right.safe` is true and it has the highest positive `progress`, or the plan is to dodge a projectile to the right.",
        "not_for": "`strafe_right.safe` is false, or its progress is zero and forward makes progress.",
    },
    "forward_left": {
        "what": "Step forward and side-step left, cornering toward the guide.",
        "use_when": "`forward_left.safe` is true and it has the highest positive `progress`.",
        "not_for": "`forward_left.safe` is false, or a cardinal direction has higher `progress`.",
    },
    "forward_right": {
        "what": "Step forward and side-step right, cornering toward the guide.",
        "use_when": "`forward_right.safe` is true and it has the highest positive `progress`.",
        "not_for": "`forward_right.safe` is false, or a cardinal direction has higher `progress`.",
    },
    "back_left": {
        "what": "Back away and side-step left, withdrawing on the diagonal.",
        "use_when": "`back_left.safe` is true and it has the highest positive `progress` toward an escape direction behind and to the left.",
        "not_for": "`back_left.safe` is false, or a cardinal direction has higher `progress`.",
    },
    "back_right": {
        "what": "Back away and side-step right, withdrawing on the diagonal.",
        "use_when": "`back_right.safe` is true and it has the highest positive `progress` toward an escape direction behind and to the right.",
        "not_for": "`back_right.safe` is false, or a cardinal direction has higher `progress`.",
    },
    "hold": {
        "what": "Stand still for this decision.",
        "use_when": "`strategy.must_move` is false and either no safe direction makes progress or the plan is to use the geometry directly ahead.",
        "not_for": "`strategy.must_move` is true, a safe direction with positive `progress` exists, or an impacting projectile is inbound.",
    },
}

_AIM_V3_INSTRUCTIONS = {
    "role": "You execute the plan's targeting.",
    "task": "Point the weapon at `strategy.focus`; when the focus is the objective, aim the route.",
    "rules": [
        "`strategy.focus` is already the code's chosen target: enemies it ignores are scenery.",
        "If the focus is a threat with `shot_would_hit` true, choose `straight`: the shot already reaches it.",
        "If the focus is a threat without a shot, turn toward the sign of its `bearing_degrees`: positive means `left`, negative means `right`.",
        "If the focus is the objective or a pickup, apply the same sign rule using `objective.aim_tolerance_degrees`.",
        "Threats listed as `relevant` false never justify a turn.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which way should the player turn now?",
}

_AIM_V3_CRITERIA = {
    "left": {
        "what": "Turn left.",
        "use_when": "`strategy.focus` is to the left (`bearing_degrees` positive) and no shot reaches it yet.",
        "not_for": "the focus is already in the firing corridor, or it lies to the right.",
    },
    "straight": {
        "what": "Do not turn.",
        "use_when": "the focus threat has `shot_would_hit` true, or the focus is the objective and its absolute `bearing_degrees` is within `objective.aim_tolerance_degrees`.",
        "not_for": "the focus is off axis and the shot does not reach it yet.",
    },
    "right": {
        "what": "Turn right.",
        "use_when": "`strategy.focus` is to the right (`bearing_degrees` negative) and no shot reaches it yet.",
        "not_for": "the focus is already in the firing corridor, or it lies to the left.",
    },
}

_INTERACTION_V3_INSTRUCTIONS = {
    "role": "You execute the plan's rules of engagement.",
    "task": "Pick exactly one action: fire, use or neither.",
    "rules": [
        "`fire` whenever `player.weapon_ready` is true, `player.ammo` is above zero and some threat has `shot_would_hit` true.",
        "Ammunition is plentiful: do not hold fire to save bullets.",
        "`use` when `usable_geometry` lists an entry whose `locked` is false.",
        "Otherwise choose `neither`; never fire at a threat whose `shot_would_hit` is false.",
        "Firing does not pause movement; both questions answer the same decision.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which action should the player take now?",
}

_INTERACTION_V3_CRITERIA = {
    "fire": {
        "what": "Shoot with the current weapon.",
        "use_when": "the weapon is ready, ammunition is above zero and a threat has `shot_would_hit` true.",
        "not_for": "the weapon is on cooldown, there is no ammunition, or no shot reaches a target.",
    },
    "use": {
        "what": "Open or activate the geometry ahead.",
        "use_when": "`usable_geometry` holds an entry whose `locked` is false.",
        "not_for": "no geometry is listed, or the entry is locked.",
    },
    "neither": {
        "what": "Take no weapon or use action.",
        "use_when": "no shot reaches a target and nothing usable is ahead.",
        "not_for": "a threat is in the firing corridor with a ready, loaded weapon.",
    },
}

V3_QUESTIONS = {
    "movement": {
        "type": "choice",
        "instructions": _MOVEMENT_V3_INSTRUCTIONS,
        "criteria": _MOVEMENT_V3_CRITERIA,
    },
    "aim": {
        "type": "choice",
        "instructions": _AIM_V3_INSTRUCTIONS,
        "criteria": _AIM_V3_CRITERIA,
    },
    "interaction": {
        "type": "choice",
        "instructions": _INTERACTION_V3_INSTRUCTIONS,
        "criteria": _INTERACTION_V3_CRITERIA,
    },
}
