"""``v2``: named fields, numeric bearings, rubric-shaped criteria.

Follows https://docs.typesafe.ai/primitives/advanced: the model judges, the
code computes every comparison that matters and quotes it in the rubric."""

from __future__ import annotations

from .conventions import _SEE

_MOVEMENT_INSTRUCTIONS = {
    "role": "Choose the movement a Doom player performs now.",
    "task": "Pick one movement for the next decision interval.",
    "rules": [
        "Never choose a movement whose `safe` flag is false.",
        "If an entry in `projectiles_inbound` has impact true, move in its `dodge` direction.",
        "A pickup with `need` critical or urgent outranks progress: move toward it when a safe direction exists, strafing when it lies to the side and holding to turn when it is far off axis.",
        "A `useful` pickup never changes the movement decision.",
        "Otherwise progress toward the objective: choose `forward` only when `forward.safe` is true and the absolute `objective.bearing_degrees` is at or below `objective.forward_tolerance_degrees`.",
        "When the objective is further off axis than that tolerance, corner toward it with `forward_left` or `forward_right` while the aim turns; take `hold` only when no safe direction makes progress.",
        "When the objective is within the forward tolerance but `forward.safe` is false, choose the safer lateral strafe instead.",
        "`forward_left`, `forward_right`, `back_left` and `back_right` combine forward or back with a strafe: take a diagonal when the goal lies between two axes and that diagonal is safe.",
        "An attacking threat at contact distance is a reason to `back` when `back.safe` is true.",
        "When `situation.stuck` is true, prefer any safe movement over repeating `hold`.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which movement should the player use now?",
}

_MOVEMENT_CRITERIA = {
    "forward": {
        "what": "Step forward.",
        "use_when": "`forward.safe` is true and the goal ahead is within its forward tolerance.",
        "not_for": "`forward.safe` is false, or the goal needs a turn in place first.",
    },
    "back": {
        "what": "Walk backwards.",
        "use_when": "a threat attacks at contact distance and `back.safe` is true.",
        "not_for": "no threat is in contact and the goal lies behind.",
    },
    "strafe_left": {
        "what": "Side-step left without turning.",
        "use_when": "`strafe_left.safe` is true and the reason is a projectile dodge, a needed pickup to the left, or a blocked forward with the objective nearly ahead.",
        "not_for": "`strafe_left.safe` is false, or the objective is more than its forward tolerance off axis to the right.",
    },
    "strafe_right": {
        "what": "Side-step right without turning.",
        "use_when": "`strafe_right.safe` is true and the reason is a projectile dodge, a needed pickup to the right, or a blocked forward with the objective nearly ahead.",
        "not_for": "`strafe_right.safe` is false, or the objective is more than its forward tolerance off axis to the left.",
    },
    "forward_left": {
        "what": "Step forward while side-stepping left.",
        "use_when": "`forward_left.safe` is true and the goal lies between ahead and the player's left, nearer the diagonal than either axis.",
        "not_for": "`forward_left.safe` is false, or a single safe axis already closes more distance.",
    },
    "forward_right": {
        "what": "Step forward while side-stepping right.",
        "use_when": "`forward_right.safe` is true and the goal lies between ahead and the player's right, nearer the diagonal than either axis.",
        "not_for": "`forward_right.safe` is false, or a single safe axis already closes more distance.",
    },
    "back_left": {
        "what": "Walk backwards while side-stepping left.",
        "use_when": "`back_left.safe` is true and retreating or escaping lies behind and to the left, near the diagonal.",
        "not_for": "`back_left.safe` is false, or a single safe axis already closes more distance.",
    },
    "back_right": {
        "what": "Walk backwards while side-stepping right.",
        "use_when": "`back_right.safe` is true and retreating or escaping lies behind and to the right, near the diagonal.",
        "not_for": "`back_right.safe` is false, or a single safe axis already closes more distance.",
    },
    "hold": {
        "what": "Stay in place.",
        "use_when": "the goal is more than `objective.forward_tolerance_degrees` off axis, or every goal-ward direction is unsafe.",
        "not_for": "an impacting projectile is inbound, or the goal is within the forward tolerance and forward is safe.",
    },
}

_AIM_INSTRUCTIONS = {
    "role": "Choose how far to turn now.",
    "task": "Point the weapon at the best threat, or at the objective when none is visible.",
    "rules": [
        "With ammunition above zero, the target is the visible threat with the smallest absolute `bearing_degrees` among those that are `attacking`, `active` or closer than 560 units.",
        "If the chosen target has `shot_would_hit` true, choose `straight`: the shot already reaches it.",
        "Otherwise turn toward the sign of its `bearing_degrees`: positive means `left`, negative means `right`.",
        "When no threat qualifies, or ammunition is zero, the target is the objective: apply the same sign rule to `objective.bearing_degrees` using `objective.aim_tolerance_degrees`.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which way should the player turn now?",
}

_AIM_CRITERIA = {
    "left": {
        "what": "Turn left.",
        "use_when": "the chosen target's `bearing_degrees` is positive and its `shot_would_hit` is false.",
        "not_for": "the target is already in the firing corridor, or it lies to the right.",
    },
    "straight": {
        "what": "Do not turn.",
        "use_when": "the chosen threat has `shot_would_hit` true, or the target is the objective and its absolute `bearing_degrees` is within `objective.aim_tolerance_degrees`.",
        "not_for": "the chosen target is off axis and the shot does not reach it.",
    },
    "right": {
        "what": "Turn right.",
        "use_when": "the chosen target's `bearing_degrees` is negative and its `shot_would_hit` is false.",
        "not_for": "the target is already in the firing corridor, or it lies to the left.",
    },
}

_INTERACTION_INSTRUCTIONS = {
    "role": "Choose the weapon or use action now.",
    "task": "Pick exactly one action: fire, use or neither.",
    "rules": [
        "`fire` needs `player.weapon_ready` true, `player.ammo` above zero and a threat with `shot_would_hit` true.",
        "`use` needs an unlocked entry in `usable_geometry`.",
        "Never fire at a threat whose `shot_would_hit` is false: the shot would miss.",
        "Otherwise choose `neither`.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which action should the player take now?",
}

_INTERACTION_CRITERIA = {
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

V2_QUESTIONS = {
    "movement": {
        "type": "choice",
        "instructions": _MOVEMENT_INSTRUCTIONS,
        "criteria": _MOVEMENT_CRITERIA,
    },
    "aim": {
        "type": "choice",
        "instructions": _AIM_INSTRUCTIONS,
        "criteria": _AIM_CRITERIA,
    },
    "interaction": {
        "type": "choice",
        "instructions": _INTERACTION_INSTRUCTIONS,
        "criteria": _INTERACTION_CRITERIA,
    },
}
