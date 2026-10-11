"""``v1``: the original frozen one-line questions."""

from __future__ import annotations

V1_QUESTIONS = {
    "movement": {
        "type": "choice",
        "instructions": "Choose the safest useful immediate movement.",
        "criteria": {
            "forward": "advance",
            "forward_left": "advance and dodge left",
            "forward_right": "advance and dodge right",
            "strafe_left": "dodge left",
            "strafe_right": "dodge right",
            "back_left": "retreat and dodge left",
            "back_right": "retreat and dodge right",
            "back": "retreat",
            "hold": "stay",
        },
    },
    "aim": {
        "type": "choice",
        "instructions": "Turn toward the best visible target.",
        "criteria": {"left": "turn left", "straight": "keep aim", "right": "turn right"},
    },
    "interaction": {
        "type": "choice",
        "instructions": "Choose the useful immediate action.",
        "criteria": {"fire": "shoot", "use": "open or activate", "neither": "wait"},
    },
}
