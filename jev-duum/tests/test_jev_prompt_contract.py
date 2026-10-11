"""The Jev request contract is frozen: the refactor may move code, not bytes.

Every decision sends ``state`` and ``questions`` to the model.  Restructuring
``prompts.py`` or ``snapshot.py`` is safe only while those payloads stay
byte-identical, so this pins a SHA-256 over both for every prompt version,
computed from the deterministic snapshot in ``conftest.py``.

If one of these fails, the refactor changed the wire format: revert it.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from conftest import (
    synthetic_hunt,
    synthetic_snapshot,
    synthetic_strategy,
    synthetic_world_model,
)

from jev_duum.prompts import PROMPT_VERSIONS, build_questions, build_state

# Recorded before the refactor (Fase 0 baseline); see docs/REFACTOR.md.
QUESTIONS_HASH = {
    "v1": "d025461700f8541ba412ab26a259bcc4d6853e38c901eb639d43383bff3aa810",
    "v2": "bd0c28566b836e7d3ea3ddcc813787aa589a153a56de23b174b9cd820d880455",
    "v3": "e4e6786f867e4cc97545388de775f345753aeed51ad6af8a2e203bdacbe0ef7b",
    "v3w": "402754dec35c1324b9c298c7a89eaf823c4241bca9085b04f99dbcdeb3b24237",
    "v4": "3d372f824052f6d14096bd7829ac5f88415b75e4a45debc3e62901c34bcbb8ca",
}
STATE_HASH = {
    "v1": "ade65e3956d62469a13f5f73ea963c821a5cb03d9f8ff8ea76172c10e6a0dc14",
    "v2": "6fc7b47a49f358f5e9d59d4b7cbea8c9bb9388671863edfb67f99601e9fe1a9e",
    "v3": "b42177f94ada0c36e357b1195be551cfe7f24236209d585e8d3c05664449f687",
    "v3w": "73c0b02ecd7463910d3005ed36dc661dd5358f0106558f9154463041e8e1ed0e",
    "v4": "62e5bc333621de3c1f889298f8c5827ef0410dc132b25cbf0e269edfff15a5f1",
}
OBSERVATIONS_HASH = "53dc55a1cd2cfa17d24a0e124cdb041ddf01fc41dbcc553e86426815ef3d1e0a"


def _digest(payload) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize("version", PROMPT_VERSIONS)
def test_questions_payload_is_frozen(version):
    assert _digest(build_questions(version)) == QUESTIONS_HASH[version]


@pytest.mark.parametrize("version", PROMPT_VERSIONS)
def test_state_payload_is_frozen(version):
    state, _observations = build_state(
        synthetic_snapshot(), version, synthetic_strategy(),
        synthetic_world_model(), synthetic_hunt(),
    )
    assert _digest(state) == STATE_HASH[version]


@pytest.mark.parametrize("version", PROMPT_VERSIONS)
def test_observations_payload_is_frozen(version):
    _state, observations = build_state(
        synthetic_snapshot(), version, synthetic_strategy(),
        synthetic_world_model(), synthetic_hunt(),
    )
    assert _digest(observations) == OBSERVATIONS_HASH
