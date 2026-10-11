"""``v4``: the model picks the next kill, the code owns the reflexes."""

from __future__ import annotations

from .conventions import _SEE
from .v3 import V3_QUESTIONS

# ── v4: the model picks the next kill, the code owns the reflexes ──────────

# Index labels keep the answer's label set constant while the monsters behind
# them change every decision.  ``state.hunt.candidates[i].choice`` names the
# label for each candidate.
TARGET_CHOICES = ("target_1", "target_2", "target_3", "exit", "advance")

_TARGET_INSTRUCTIONS = {
    "role": "You choose the next kill; the code executes the movement and the shots.",
    "task": "Pick which monster the player should hunt next, or leave for the exit.",
    "rules": [
        "`hunt.candidates` holds up to three monsters, each tagged with its `choice` label.",
        "`hunt.candidates[i].kills_per_second` is the code's projection for going after it: arrival plus trigger time, discounted when the way is indirect.",
        "`awake` true means the monster already comes to the player, so finishing it is cheap.",
        "`route_reachable` false means the way itself is blocked for now; it is still a valid target, the code will detour.",
        "Choose `target_n` for the monster with the best projected kill rate given the mission: kill everything, then leave.",
        "Choose `exit` to abandon the hunt and head for the exit.",
        "`advance` keeps the code's own ranking; it is the safe default.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which monster should the player hunt next?",
}

_TARGET_CRITERIA = {
    "target_1": {
        "what": "Hunt the first candidate in `hunt.candidates`.",
        "use_when": "its `kills_per_second` is the best of the listed candidates.",
        "not_for": "another candidate has a clearly better projected kill rate.",
    },
    "target_2": {
        "what": "Hunt the second candidate in `hunt.candidates`.",
        "use_when": "it is awake and closer than the first candidate, or the first is unreachable.",
        "not_for": "a candidate with a clearly better projected kill rate exists.",
    },
    "target_3": {
        "what": "Hunt the third candidate in `hunt.candidates`.",
        "use_when": "the first two are unreachable or already dying.",
        "not_for": "a candidate with a clearly better projected kill rate exists.",
    },
    "exit": {
        "what": "Stop hunting and head for the exit.",
        "use_when": "the mission is to leave with monsters still alive.",
        "not_for": "the mission is to clear the level and monsters remain reachable.",
    },
    "advance": {
        "what": "Keep the code's own ranking for this decision.",
        "use_when": "no candidate stands out and the default order is good enough.",
        "not_for": "one candidate is clearly better than the rest.",
    },
}

V4_QUESTIONS = {
    **V3_QUESTIONS,
    "target": {
        "type": "choice",
        "instructions": _TARGET_INSTRUCTIONS,
        "criteria": _TARGET_CRITERIA,
    },
}
