import json
import math
import os
from pathlib import Path

import pytest

from jev_duum.integration import DuumRuntime, load_duum
from jev_duum.prompts import (
    CONVENTIONS,
    PROMPT_VERSIONS,
    V1_QUESTIONS,
    build_questions,
    build_state,
    snapshot_from_dict,
)
from jev_duum.snapshot import SnapshotBuilder
from jev_duum.types import AIMS, INTERACTIONS, MOVEMENTS

ROOT = Path(__file__).parents[1]
DUUM_ROOT = Path(os.environ.get("JEV_DUUM_PATH", ROOT.parent / "duum"))
WAD = ROOT / "freedoom1.wad"
HAS_FIXTURE = (DUUM_ROOT / "duum" / "engine.py").is_file() and WAD.is_file()

LABELS = {"movement": MOVEMENTS, "aim": AIMS, "interaction": INTERACTIONS}


def test_v1_questions_are_frozen_and_v2_keeps_the_same_labels():
    assert build_questions("v1") == V1_QUESTIONS
    for version in PROMPT_VERSIONS:
        questions = build_questions(version)
        assert set(questions) == set(LABELS)
        for name, labels in LABELS.items():
            assert set(questions[name]["criteria"]) == set(labels)


@pytest.mark.parametrize("version", ("v2", "v3"))
def test_structured_questions_carry_instructions_and_rubrics(version):
    questions = build_questions(version)
    for name, question in questions.items():
        instructions = question["instructions"]
        assert isinstance(instructions, dict), name
        assert {"role", "task", "rules", "question"} <= set(instructions), name
        assert instructions["rules"], name
        for label, criterion in question["criteria"].items():
            assert isinstance(criterion, dict), (name, label)
            assert {"what", "use_when", "not_for"} <= set(criterion), (name, label)


def test_v2_points_at_code_computed_facts_and_exact_conventions():
    questions = build_questions("v2")
    movement_rules = " ".join(questions["movement"]["instructions"]["rules"])
    aim_rules = " ".join(questions["aim"]["instructions"]["rules"])
    assert "safe" in movement_rules and "forward.safe" in movement_rules
    assert "projectiles_inbound" in movement_rules
    assert "shot_would_hit" in aim_rules
    assert "left" in aim_rules and "right" in aim_rules
    assert "no abstention" in movement_rules


def test_reverse_order_flips_position_without_changing_content():
    straight = build_questions("v2")
    reversed_questions = build_questions("v2", reverse_order=True)
    for name in straight:
        assert list(reversed_questions[name]["criteria"]) == list(
            reversed(list(straight[name]["criteria"]))
        )
        assert reversed_questions[name]["criteria"] == dict(
            reversed(list(straight[name]["criteria"].items()))
        )


def test_unknown_version_is_rejected():
    with pytest.raises(ValueError, match="unknown prompt version"):
        build_questions("v9")


def test_v3_requires_a_strategy_and_keeps_the_same_labels():
    questions = build_questions("v3")
    assert set(questions) == set(LABELS)
    rules = " ".join(questions["movement"]["instructions"]["rules"])
    assert "strategy.must_move" in rules and "progress" in rules
    assert "strategy.focus" in " ".join(questions["aim"]["instructions"]["rules"])


def test_v3w_questions_mention_the_world_model():
    questions = build_questions("v3w")
    for name, question in questions.items():
        rules = " ".join(question["instructions"]["rules"])
        assert "world_model" in rules, name
    movement = " ".join(questions["movement"]["instructions"]["rules"])
    assert "hazards.nukage" in movement
    assert set(questions["movement"]["criteria"]) == set(MOVEMENTS)


@pytest.mark.skipif(
    not HAS_FIXTURE,
    reason="needs the pinned sibling Duum checkout and a local freedoom1.wad",
)
def test_v3w_state_publishes_the_world_model_or_null():
    from jev_duum.prompts import build_state
    from jev_duum.strategy import StrategyTracker, compute_strategy

    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        snapshot = SnapshotBuilder(runtime.app, modules.engine).build(0)
    strategy = compute_strategy(snapshot, StrategyTracker())
    block = {"map": "E1M1", "room": "START"}
    state, _ = build_state(snapshot, "v3w", strategy, block)
    assert state["world_model"] == block
    # Fail-soft: without the adapter the key is still present, explicitly null.
    state, _ = build_state(snapshot, "v3w", strategy, None)
    assert state["world_model"] is None
    with pytest.raises(ValueError, match="needs a strategy"):
        build_state(snapshot, "v3w")


@pytest.mark.skipif(
    not HAS_FIXTURE,
    reason="needs the pinned sibling Duum checkout and a local freedoom1.wad",
)
def test_v3_state_carries_the_strategy_block_and_progress():
    from jev_duum.prompts import build_state
    from jev_duum.strategy import StrategyTracker, compute_strategy

    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        snapshot = SnapshotBuilder(runtime.app, modules.engine).build(0)
    strategy = compute_strategy(snapshot, StrategyTracker())
    state, _ = build_state(snapshot, "v3", strategy)
    assert state["strategy"]["mission"] == "advance"
    assert state["strategy"]["max_hold_streak"] == 5
    assert state["strategy"]["rules_of_engagement"]
    assert isinstance(state["movement_options"]["forward"]["progress"], float)
    assert all("relevant" in threat for threat in state["threats"])
    with pytest.raises(ValueError, match="needs a strategy"):
        build_state(snapshot, "v3")


@pytest.mark.skipif(
    not HAS_FIXTURE,
    reason="needs the pinned sibling Duum checkout and a local freedoom1.wad",
)
def test_structured_state_is_numeric_named_and_bounded():
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        snapshot = SnapshotBuilder(runtime.app, modules.engine).build(0)
    state, observations = build_state(snapshot, "v2")
    assert set(state) >= {
        "conventions",
        "player",
        "objective",
        "threats",
        "projectiles_inbound",
        "pickups",
        "usable_geometry",
        "movement_options",
        "situation",
    }
    assert isinstance(state["conventions"], dict)
    assert state["conventions"]["bearing_degrees"]
    assert set(state["movement_options"]) == set(MOVEMENTS)
    for name, option in state["movement_options"].items():
        assert isinstance(option["safe"], bool), name
        assert isinstance(option["clear_distance_units"], (int, float)), name
    for threat in state["threats"]:
        assert isinstance(threat["bearing_degrees"], (int, float))
        assert isinstance(threat["shot_would_hit"], bool)
    assert state["objective"]["aim_tolerance_degrees"] == pytest.approx(2.29, abs=0.01)
    assert state["objective"]["forward_tolerance_degrees"] == pytest.approx(4.58, abs=0.01)
    # No compressed `key=value/word/word` blobs leak into the structured state.
    assert "=" not in json.dumps(state)
    assert isinstance(observations["aim"], str) and "target=" in observations["aim"]
    assert len(json.dumps(state)) < 12_000


@pytest.mark.skipif(
    not HAS_FIXTURE,
    reason="needs the pinned sibling Duum checkout and a local freedoom1.wad",
)
def test_snapshot_round_trips_through_json():
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        snapshot = SnapshotBuilder(runtime.app, modules.engine).build(0)
    restored = snapshot_from_dict(json.loads(json.dumps(snapshot.to_dict())))
    assert restored == snapshot
    assert restored.state_hash() == snapshot.state_hash()
    state, _ = build_state(restored, "v2")
    original, _ = build_state(snapshot, "v2")
    assert state == original


def test_bearing_convention_matches_the_snapshot_encoder():
    # `_bearing_word` calls positive angles "left"; the prompt promises the same.
    from jev_duum.snapshot import _bearing_word

    assert _bearing_word(math.radians(30)) == "left"
    assert _bearing_word(math.radians(-30)) == "right"
    assert _bearing_word(math.radians(5)) == "aligned"
    assert CONVENTIONS["bearing_degrees"].startswith("Degrees to turn")
    assert "LEFT" in CONVENTIONS["bearing_degrees"]
