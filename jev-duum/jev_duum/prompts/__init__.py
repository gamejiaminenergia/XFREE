"""Versioned Jev requests: the state we send and the questions we ask.

This package replaces the old single-file ``prompts.py``.  It keeps the same
dotted path and re-exports the same names, so the controller and the prompt
harness import it unchanged; the frozen definitions now live one per file."""

from __future__ import annotations

from .codec import snapshot_from_dict
from .conventions import CONVENTIONS
from .questions import (
    DEFAULT_PROMPT_VERSION,
    PROMPT_VERSIONS,
    build_questions,
)
from .state import build_state
from .v1 import V1_QUESTIONS
from .v4 import TARGET_CHOICES

__all__ = [
    "PROMPT_VERSIONS", "DEFAULT_PROMPT_VERSION", "TARGET_CHOICES",
    "build_questions", "build_state", "snapshot_from_dict",
    "CONVENTIONS", "V1_QUESTIONS",
]
