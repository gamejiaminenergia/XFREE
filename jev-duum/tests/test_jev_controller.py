import os
from dataclasses import replace
from pathlib import Path

import pytest

from jev_duum.controller import DEFINITIONS, JevDuumController
from jev_duum.integration import DuumRuntime, load_duum
from jev_duum.jev_client import JevError
from jev_duum.snapshot import PickupSnapshot, ProjectileSnapshot, SnapshotBuilder
from jev_duum.types import DuumControls

ROOT = Path(__file__).parents[1]
DUUM_ROOT = Path(os.environ.get("JEV_DUUM_PATH", ROOT.parent / "duum"))
WAD = ROOT / "freedoom1.wad"
HAS_FIXTURE = (DUUM_ROOT / "duum" / "engine.py").is_file() and WAD.is_file()


class FakeJevClient:
    """A stand-in for JevClient that never touches the network."""

    def __init__(self, answers=None, *, model="jev-test-1.0", tokens=101):
        self.endpoint = "fake://typesafe"
        self.model = model
        self.tokens = tokens
        self.calls = 0
        self.input_tokens = 0
        self.last_state = None
        self.last_questions = None
        self.answers = answers or {
            "movement": {
                "type": "choice",
                "choice": "strafe_left",
                "confidence": 0.6,
                "probabilities": {
                    "forward": 0.1,
                    "back": 0.1,
                    "strafe_left": 0.6,
                    "strafe_right": 0.1,
                    "hold": 0.1,
                },
            },
            "aim": {
                "type": "choice",
                "choice": "right",
                "confidence": 0.7,
                "probabilities": {"left": 0.1, "straight": 0.2, "right": 0.7},
            },
            "interaction": {
                "type": "choice",
                "choice": "fire",
                "confidence": 0.8,
                "probabilities": {"fire": 0.8, "use": 0.1, "neither": 0.1},
            },
        }

    def ask(self, state, questions, *, model=None):
        self.calls += 1
        self.last_state = state
        self.last_questions = questions
        self.input_tokens += self.tokens
        return {
            "model": self.model,
            "answers": {name: self.answers[name] for name in questions},
            "usage": {"input_tokens": self.tokens, "output_tokens": 40},
        }


def snapshot():
    if not HAS_FIXTURE:
        pytest.skip("needs the pinned sibling Duum checkout and a local WAD")
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        return SnapshotBuilder(runtime.app, modules.engine).build(0)


def test_one_request_carries_all_three_questions():
    client = FakeJevClient()
    result = JevDuumController(client=client).decide(snapshot())
    assert client.calls == 1
    assert result.prediction_calls == 1
    assert result.execution == "single-request"
    assert set(client.last_questions) == {name for name, _ in DEFINITIONS}
    assert set(client.last_state) >= {"movement", "aim", "interaction", "tick", "map"}
    assert result.model_id == "jev-test-1.0"
    assert result.cost_usd == pytest.approx(101 * 0.042 / 1_000_000)
    assert result.input_tokens == {"request": 101}


def test_fake_probabilities_map_to_three_factorized_controls():
    client = FakeJevClient()
    result = JevDuumController(client=client).decide(snapshot())
    assert result.proposed_controls == result.applied_controls == DuumControls(
        "strafe_left", "right", "fire"
    )
    assert result.observation_tick == 0
    assert result.application_tick is None
    assert result.with_application_tick(1).application_tick == 1
    assert result.confidence == {"movement": 0.6, "aim": 0.7, "interaction": 0.8}


def test_assistance_preserves_raw_action_and_records_override():
    state = snapshot()
    projectile = ProjectileSnapshot(
        id=1,
        bearing=0.0,
        bearing_word="aligned",
        distance=50,
        distance_word="contact",
        impact_time=0.2,
        impact=True,
        dodge="strafe_right",
        threat=1000,
    )
    state = replace(state, incoming_projectiles=(projectile,))
    result = JevDuumController(client=FakeJevClient(), assisted=True).decide(state)
    assert result.proposed_controls.movement == "strafe_left"
    assert result.applied_controls.movement == "strafe_right"
    assert result.assistance_events[0].kind == "projectile-dodge"


def test_navigation_turn_holds_position_instead_of_backing_up():
    state = snapshot()
    route = replace(
        state.navigation,
        bearing=0.5,
        bearing_word="left",
        distance=40,
        distance_word="contact",
    )
    state = replace(
        state,
        visible_enemies=(),
        incoming_projectiles=(),
        visible_pickups=(),
        nearby_interactions=(),
        navigation=route,
    )
    proposed = DuumControls("hold", "straight", "neither")
    applied, _ = JevDuumController(
        client=FakeJevClient(), assisted=True
    )._assist(state, proposed)
    assert applied == DuumControls("hold", "left", "neither")


def test_critical_health_takes_priority_over_nonattacking_enemy():
    state = snapshot()
    enemy = replace(
        state.visible_enemies[0],
        bearing=-0.5,
        bearing_word="right",
        distance=200,
        distance_word="near",
        attacking=False,
        active=True,
        melee_reachable=True,
        aligned=False,
    )
    health = PickupSnapshot(
        id=999,
        category="health",
        bearing=0.5,
        bearing_word="left",
        distance=80,
        distance_word="contact",
        need="critical",
    )
    state = replace(
        state,
        player=replace(state.player, health=19),
        visible_enemies=(enemy,),
        incoming_projectiles=(),
        visible_pickups=(health,),
        nearby_interactions=(),
    )
    proposed = DuumControls("hold", "straight", "fire")
    applied, _ = JevDuumController(
        client=FakeJevClient(), assisted=True
    )._assist(state, proposed)
    assert applied == DuumControls("hold", "left", "neither")


def test_fist_does_not_target_enemy_across_impassable_height():
    state = snapshot()
    enemy = replace(
        state.visible_enemies[0],
        distance=40,
        distance_word="contact",
        attacking=True,
        active=True,
        melee_reachable=False,
        aligned=True,
    )
    state = replace(
        state,
        player=replace(state.player, weapon=1, weapon_name="fist", ammo=999),
        visible_enemies=(enemy,),
        incoming_projectiles=(),
        visible_pickups=(),
        nearby_interactions=(),
    )
    proposed = DuumControls("hold", "straight", "fire")
    applied, _ = JevDuumController(
        client=FakeJevClient(), assisted=True
    )._assist(state, proposed)
    assert applied.interaction == "neither"


def test_nonfinite_probability_fails_before_controls_are_returned():
    answers = FakeJevClient().answers
    answers["aim"] = {
        "probabilities": {"left": 0.1, "straight": 0.2, "right": float("nan")}
    }
    with pytest.raises(ValueError, match="invalid aim probability"):
        JevDuumController(client=FakeJevClient(answers=answers)).decide(snapshot())


def test_unnormalized_probabilities_are_rejected():
    answers = FakeJevClient().answers
    answers["movement"] = {
        "probabilities": {
            "forward": 0.5,
            "back": 0.5,
            "strafe_left": 0.5,
            "strafe_right": 0.1,
            "hold": 0.1,
        }
    }
    with pytest.raises(ValueError, match="unnormalized movement"):
        JevDuumController(client=FakeJevClient(answers=answers)).decide(snapshot())


def test_two_decimal_rounding_of_a_five_option_choice_is_accepted():
    # Observed live: 0.07 + 0.17 + 0.20 + 0.28 + 0.27 == 0.99.
    answers = FakeJevClient().answers
    answers["movement"] = {
        "type": "choice",
        "choice": "strafe_right",
        "confidence": 0.1,
        "probabilities": {
            "forward": 0.07,
            "back": 0.17,
            "strafe_left": 0.20,
            "strafe_right": 0.28,
            "hold": 0.27,
        },
    }
    result = JevDuumController(client=FakeJevClient(answers=answers)).decide(snapshot())
    assert result.proposed_controls.movement == "strafe_right"


def test_missing_api_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(JevError, match="TYPESAFE_API_KEY"):
        JevDuumController(model="jev-latest")
