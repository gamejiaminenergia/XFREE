"""A local, deterministic stand-in for the model: no network, no key, no cost.

Same answers the preview tool uses, so a demo or a test can drive the whole
service end to end (engine, session, HTTP) without spending anything.
"""

from __future__ import annotations

ANSWERS = {
    "movement": {
        "type": "choice", "choice": "strafe_left", "confidence": 0.6,
        "probabilities": {
            "forward": 0.10, "forward_left": 0.02, "forward_right": 0.02,
            "strafe_left": 0.60, "strafe_right": 0.08, "back_left": 0.01,
            "back_right": 0.01, "back": 0.06, "hold": 0.10,
        },
    },
    "aim": {
        "type": "choice", "choice": "right", "confidence": 0.7,
        "probabilities": {"left": 0.1, "straight": 0.2, "right": 0.7},
    },
    "interaction": {
        "type": "choice", "choice": "fire", "confidence": 0.8,
        "probabilities": {"fire": 0.8, "use": 0.1, "neither": 0.1},
    },
    "target": {
        "type": "choice", "choice": "advance", "confidence": 0.5,
        "probabilities": {
            "target_1": 0.2, "target_2": 0.2, "target_3": 0.1,
            "exit": 0.2, "advance": 0.3,
        },
    },
}


class FakeClient:
    """Implements the one method the controller calls."""

    endpoint = "fake://local"
    logger = None

    def __init__(self, *, model: str = "fake-local", tokens: int = 1180):
        self.model = model
        self.tokens = tokens
        self.calls = 0

    def ask(self, state, questions, *, model=None, context=None):
        self.calls += 1
        return {
            "model": self.model,
            "answers": {name: ANSWERS[name] for name in questions},
            "usage": {"input_tokens": self.tokens, "output_tokens": 44},
        }
