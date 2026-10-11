import json
import math

import pytest

from jev_duum.assistance import reference_controls, reference_fire_allowed
from jev_duum.prompt_eval import SCHEMA, evaluate_corpus, load_corpus
from jev_duum.snapshot import (
    DuumSnapshot,
    EnemySnapshot,
    EpisodeSnapshot,
    MovementOptionSnapshot,
    NavigationSnapshot,
    PlayerSnapshot,
)


def snapshot(*, bearing=math.radians(20), forward_safe=False):
    enemy = EnemySnapshot(
        id=1,
        category="hitscan-enemy",
        bearing=bearing,
        bearing_word="left" if bearing > 0 else "right",
        distance=100.0,
        distance_word="near",
        visible=True,
        attacking=True,
        active=True,
        melee_reachable=True,
        aligned=False,
        motion="steady",
        threat=900.0,
    )
    return DuumSnapshot(
        tick=120,
        map_name="E1M1",
        rng=1,
        player=PlayerSnapshot(
            x=0.0,
            y=0.0,
            angle=0.0,
            health=74,
            armor=0,
            weapon=2,
            weapon_name="pistol",
            ammo=50,
            weapon_ready=True,
            keys=0,
            damage_since_last=0,
        ),
        visible_enemies=(enemy,),
        incoming_projectiles=(),
        visible_pickups=(),
        nearby_interactions=(),
        movement_options=(
            MovementOptionSnapshot("forward", 0.0 if not forward_safe else 200.0, forward_safe),
            MovementOptionSnapshot("back", 96.0, True),
            MovementOptionSnapshot("strafe_left", 48.0, True),
            MovementOptionSnapshot("strafe_right", 48.0, True),
        ),
        navigation=NavigationSnapshot(
            objective="exit",
            bearing=math.radians(30),
            bearing_word="left",
            distance=120.0,
            distance_word="near",
            next_sector=17,
            route_length=16,
            reachable=True,
            use_when_near=False,
        ),
        omitted_enemies=0,
        episode=EpisodeSnapshot(
            game_time=2.0,
            kills=0,
            items=0,
            damage_received=26,
            live_enemies=3,
            projectiles=0,
            unique_sectors=4,
            stuck_ticks=0,
            idle_ticks=0,
            dead=False,
            finished=False,
        ),
    )


class ScriptedClient:
    """Deterministic answers per prompt version, chosen by the state shape."""

    def __init__(self, picks, tokens=111):
        self.picks = picks
        self.tokens = tokens
        self.calls = 0

    def ask(self, state, questions, *, context=None):
        self.calls += 1
        version = "v2" if "conventions" in state else "v1"
        answers = {}
        for name, question in questions.items():
            labels = list(question["criteria"])
            chosen = self.picks[version][name]
            answers[name] = {
                "type": "choice",
                "choice": chosen,
                "confidence": 0.9,
                "probabilities": {
                    label: (1.0 if label == chosen else 0.0) for label in labels
                },
            }
        return {
            "model": "fake-1.0",
            "answers": answers,
            "usage": {"input_tokens": self.tokens},
        }


PICKS = {
    "v1": {"movement": "forward", "aim": "straight", "interaction": "fire"},
    "v2": {"movement": "hold", "aim": "left", "interaction": "neither"},
}


def test_reference_policy_reads_geometry_and_the_firing_corridor():
    state = snapshot()
    reference = reference_controls(state)
    assert reference.aim == "left"  # attacking target is off axis to the left
    assert reference.movement == "hold"  # a visible target suppresses route progress
    assert reference_fire_allowed(state) is False  # no shot reaches the target
    blocked = snapshot(bearing=-math.radians(20))
    assert reference_controls(blocked).aim == "right"


def test_paired_evaluation_separates_v1_from_v2():
    client = ScriptedClient(PICKS)
    report = evaluate_corpus(client, [snapshot(), snapshot()], ("v1", "v2"))
    assert report["schema"] == SCHEMA
    assert report["snapshots"] == 2
    v1 = report["versions"]["v1"]
    v2 = report["versions"]["v2"]
    assert v1["mean_guard_interventions"] == 3.0
    assert v1["aim_direction_error"] == 0.0
    assert v1["straight_outside_tolerance"] == 1.0
    assert v1["unsafe_proposal_rate"] == 1.0  # the model proposed a blocked direction
    assert v1["unsafe_movement"] == 0.0  # the guard never lets it happen
    assert v1["fire_without_corridor"] == 1.0
    assert v1["hold_rate"] == 0.0
    assert set(v1["guard_intervention_kinds"]) == {
        "blocked-movement",
        "aim-guidance",
        "fire-alignment",
    }
    assert v2["mean_guard_interventions"] == 0.0
    assert v2["aim_reference_agreement"] == 1.0
    assert v2["hold_rate"] == 1.0
    assert v2["unsafe_movement"] == 0.0
    assert v2["mean_input_tokens"] == 111.0
    # The report rounds money to six decimals.
    assert report["total_cost_usd"] == pytest.approx(
        4 * 111 * 0.042 / 1_000_000, abs=1e-6
    )


def test_order_probe_reports_agreement_per_question():
    client = ScriptedClient(PICKS)
    report = evaluate_corpus(
        client, [snapshot()], ("v2",), order_probe=True
    )
    assert report["order_probe"] is True
    assert report["versions"]["v2"]["order_agreement"] == {
        "movement": 1.0,
        "aim": 1.0,
        "interaction": 1.0,
    }


def test_load_corpus_accepts_recordings_and_bare_snapshot_lists(tmp_path):
    state = snapshot()
    recording = tmp_path / "episode.json"
    recording.write_text(
        json.dumps(
            {
                "schema": "jev-duum-episode-v2",
                "snapshots": [{"tick": state.tick, "snapshot": state.to_dict()}],
            }
        )
    )
    loaded = load_corpus(recording)
    assert len(loaded) == 1
    assert loaded[0].state_hash() == state.state_hash()

    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps([state.to_dict()]))
    assert load_corpus(bare)[0] == state

    empty = tmp_path / "v1.json"
    empty.write_text(json.dumps({"schema": "jev-duum-episode-v1"}))
    with pytest.raises(ValueError, match="no `snapshots` array"):
        load_corpus(empty)
