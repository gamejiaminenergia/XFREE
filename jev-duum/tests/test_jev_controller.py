import os
from dataclasses import replace
from pathlib import Path

import pytest

from jev_duum.controller import DEFINITIONS, JevDuumController
from jev_duum.integration import DuumRuntime, load_duum
from jev_duum.jev_client import JevError
from jev_duum.prompts import DEFAULT_PROMPT_VERSION
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

    def ask(self, state, questions, *, model=None, context=None):
        self.calls += 1
        self.last_state = state
        self.last_questions = questions
        self.last_context = context
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
    assert set(client.last_state) >= {
        "conventions",
        "player",
        "objective",
        "threats",
        "movement_options",
        "situation",
        "tick",
        "map",
    }
    assert isinstance(client.last_questions["aim"]["instructions"], dict)
    assert isinstance(client.last_questions["movement"]["criteria"]["forward"], dict)
    assert result.prompt_version == DEFAULT_PROMPT_VERSION == "v3w"
    # v3 is the strategy-executing prompt: the code's plan travels with the state.
    assert isinstance(client.last_state["strategy"], dict)
    assert client.last_state["strategy"]["mission"] == "advance"
    # v3w also publishes the schematic world model (None until the adapter lands).
    assert "world_model" in client.last_state
    assert result.model_id == "jev-test-1.0"
    assert result.cost_usd == pytest.approx(101 * 0.042 / 1_000_000)
    assert result.input_tokens == {"request": 101}


def test_decision_keeps_the_exact_request_for_the_inspector():
    client = FakeJevClient()
    result = JevDuumController(client=client).decide(snapshot())
    # The Tk inspector shows the request verbatim, so the decision must carry it.
    assert result.request_state == client.last_state
    assert result.request_questions == client.last_questions


def test_v1_prompt_version_keeps_the_frozen_legacy_request():
    client = FakeJevClient()
    controller = JevDuumController(client=client, prompt_version="v1")
    result = controller.decide(snapshot())
    assert set(client.last_state) == {"tick", "map", "movement", "aim", "interaction"}
    assert all(isinstance(value, str) for key, value in client.last_state.items() if key != "tick")
    assert client.last_questions["aim"]["instructions"] == "Turn toward the best visible target."
    assert result.prompt_version == "v1"
    assert controller.metadata["prompt_version"] == "v1"


def test_prompt_version_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("JEV_PROMPT_VERSION", "v1")
    controller = JevDuumController(client=FakeJevClient())
    assert controller.prompt_version == "v1"
    assert "movement" in JevDuumController(
        client=FakeJevClient(), prompt_version="v2"
    ).questions
    monkeypatch.setenv("JEV_PROMPT_VERSION", "v9")
    with pytest.raises(ValueError, match="unknown prompt version"):
        JevDuumController(client=FakeJevClient())
    with pytest.raises(ValueError, match="unknown prompt version"):
        JevDuumController(client=FakeJevClient(), prompt_version="v9")


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


def test_navigation_turn_advances_instead_of_freezing():
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
    # The route is 28 degrees to the left and forward is safe: turn and walk
    # instead of turning in place, which is what froze the old pilot.
    assert applied == DuumControls("forward", "left", "neither")


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
    # Critical health wins over the harmless enemy: face the pickup and keep
    # moving toward it instead of standing still.
    assert applied == DuumControls("forward", "left", "neither")


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


def test_v3_sends_the_strategy_and_never_freezes_forever():
    state = snapshot()
    hold_answers = {
        "movement": {
            "type": "choice",
            "choice": "hold",
            "confidence": 0.9,
            "probabilities": {
                "forward": 0.02,
                "back": 0.02,
                "strafe_left": 0.02,
                "strafe_right": 0.02,
                "hold": 0.92,
            },
        },
        "aim": {
            "type": "choice",
            "choice": "straight",
            "confidence": 0.9,
            "probabilities": {"left": 0.05, "straight": 0.9, "right": 0.05},
        },
        "interaction": {
            "type": "choice",
            "choice": "neither",
            "confidence": 0.9,
            "probabilities": {"fire": 0.05, "use": 0.05, "neither": 0.9},
        },
    }
    client = FakeJevClient(answers=hold_answers)
    controller = JevDuumController(
        client=client, prompt_version="v3"
    )
    results = [controller.decide(replace(state, tick=tick)) for tick in range(1, 9)]
    assert results[0].strategy["mission"] == "advance"
    assert client.last_state["strategy"]["mission"] == "advance"
    assert "progress" in client.last_state["movement_options"]["forward"]
    assert any("relevant" in threat for threat in client.last_state["threats"])
    kinds = [event.kind for result in results for event in result.assistance_events]
    assert "strategy-progress" in kinds
    assert results[-1].applied_controls.movement != "hold"


def test_v3w_attaches_the_world_model_when_the_adapter_is_available(monkeypatch):
    import jev_duum.controller as controller_module

    block = {"map": "E1M1", "room": "START", "hidden_foes": {"total": 17}}
    monkeypatch.setattr(controller_module, "build_world_model", lambda snap: block)
    client = FakeJevClient()
    controller = JevDuumController(client=client, prompt_version="v3w")
    result = controller.decide(snapshot())
    assert client.last_state["world_model"] == block
    assert result.world_model == block and result.world_model_used is True
    assert result.strategy["mission"] == "advance"


def test_world_model_failure_never_breaks_a_decision(monkeypatch):
    import jev_duum.controller as controller_module

    def explode(_snapshot):
        raise RuntimeError("adapter exploded")

    monkeypatch.setattr(controller_module, "build_world_model", explode)
    client = FakeJevClient()
    result = JevDuumController(client=client, prompt_version="v3w").decide(snapshot())
    assert client.last_state["world_model"] is None
    assert result.world_model_used is False
    assert result.prediction_calls == 1


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
