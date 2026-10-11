"""Offline paired comparison of prompt versions over recorded snapshots.

This package replaces the old single-file ``prompt_eval.py``.  It keeps the
same dotted path and re-exports the same names, so the console script
(``jev-duum-prompt-eval``) and the tests import it unchanged."""

from __future__ import annotations

from .corpus import SCHEMA, load_corpus
from .evaluate import evaluate_corpus, main

__all__ = ["SCHEMA", "load_corpus", "evaluate_corpus", "main"]
