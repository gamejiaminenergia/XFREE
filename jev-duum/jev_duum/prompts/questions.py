"""The version registry: which questions each prompt travels with, and the
validator that keeps every option label constant."""

from __future__ import annotations

from ..types import AIMS, INTERACTIONS, MOVEMENTS
from .v1 import V1_QUESTIONS
from .v2 import V2_QUESTIONS
from .v3 import V3_QUESTIONS
from .v3w import V3W_QUESTIONS
from .v4 import TARGET_CHOICES, V4_QUESTIONS

PROMPT_VERSIONS = ("v1", "v2", "v3", "v3w", "v4")
DEFAULT_PROMPT_VERSION = "v3w"

_QUESTIONS = {"v1": V1_QUESTIONS, "v2": V2_QUESTIONS, "v3": V3_QUESTIONS}

# The two later versions register on top of the frozen three; the dict is the
# same object the old single-file module built by mutation, kept intact here so
# the registry has one home.
_QUESTIONS["v3w"] = V3W_QUESTIONS
_QUESTIONS["v4"] = V4_QUESTIONS

_EXPECTED_LABELS = {
    "movement": MOVEMENTS,
    "aim": AIMS,
    "interaction": INTERACTIONS,
    "target": TARGET_CHOICES,
}


def build_questions(version: str, *, reverse_order: bool = False) -> dict:
    """Return a fresh questions dict for ``version``.

    ``reverse_order`` flips the order of the ``criteria`` keys without changing
    their content; the offline harness uses it to detect position bias.
    """

    if version not in _QUESTIONS:
        raise ValueError(f"unknown prompt version: {version}")
    questions = {}
    for name, question in _QUESTIONS[version].items():
        criteria = list(question["criteria"].items())
        if reverse_order:
            criteria = list(reversed(criteria))
        questions[name] = {
            **question,
            "criteria": dict(criteria),
        }
    for name, question in questions.items():
        if set(question["criteria"]) != set(_EXPECTED_LABELS[name]):
            raise ValueError(
                f"prompt {version} question {name} has criteria "
                f"{sorted(question['criteria'])} != {sorted(_EXPECTED_LABELS[name])}"
            )
    return questions
