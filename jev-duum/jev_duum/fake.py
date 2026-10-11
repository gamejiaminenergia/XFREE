"""A local, deterministic stand-in for the model: demos and tests at 0 $.

Several things need to drive the whole pilot without a key, a network or a bill:
the offline dev tools, the HTTP service, the terminal UI and the tests.  They all
use this one client, so the "fake" answers live in a single place.

It is deliberately dull: the same distribution for every question, every time.
That is what makes a preview reproducible.
"""

from __future__ import annotations

from typing import Any

# The shape the controller validates: one ``choice`` question per head, with the
# exact label set the prompts declare.  ``target`` is only asked by v4.
ANSWERS: dict[str, dict[str, Any]] = {
    "movement": {
        "type": "choice", "choice": "strafe_left", "confidence": 0.60,
        "probabilities": {
            "forward": 0.10, "forward_left": 0.02, "forward_right": 0.02,
            "strafe_left": 0.60, "strafe_right": 0.08, "back_left": 0.01,
            "back_right": 0.01, "back": 0.06, "hold": 0.10,
        },
    },
    "aim": {
        "type": "choice", "choice": "right", "confidence": 0.70,
        "probabilities": {"left": 0.1, "straight": 0.2, "right": 0.7},
    },
    "interaction": {
        "type": "choice", "choice": "fire", "confidence": 0.80,
        "probabilities": {"fire": 0.8, "use": 0.1, "neither": 0.1},
    },
    "target": {
        "type": "choice", "choice": "advance", "confidence": 0.50,
        "probabilities": {
            "target_1": 0.20, "target_2": 0.20, "target_3": 0.10,
            "exit": 0.20, "advance": 0.30,
        },
    },
}

DEFAULT_MODEL = "fake-local"
DEFAULT_TOKENS = 1180


class FakeJevClient:
    """Implements the one method ``JevDuumController`` calls."""

    endpoint = "fake://local"
    logger = None

    def __init__(self, *, model: str = DEFAULT_MODEL, tokens: int = DEFAULT_TOKENS):
        self.model = model
        self.tokens = int(tokens)
        self.calls = 0

    def ask(self, state, questions, *, model=None, context=None):
        self.calls += 1
        return {
            "model": self.model,
            "answers": {name: ANSWERS[name] for name in questions},
            "usage": {"input_tokens": self.tokens, "output_tokens": 44},
        }
