"""The headless session: one engine, one worker, frames without a display.

Skipped when the pinned engine or the WAD is missing, like the other
engine-backed tests.  No Tk is imported and no window is opened.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jev_duum.controller import JevDuumController
from jev_duum.integration import DuumRuntime, load_duum
from jev_duum.session.core import Session

ROOT = Path(__file__).parents[1]
DUUM_ROOT = Path(os.environ.get("JEV_DUUM_PATH", ROOT.parent / "duum"))
WAD = ROOT / "freedoom1.wad"
HAS_FIXTURE = (DUUM_ROOT / "duum" / "engine.py").is_file() and WAD.is_file()

pytestmark = pytest.mark.skipif(not HAS_FIXTURE, reason="needs the pinned engine and the WAD")


ANSWERS = {
    "movement": {
        "type": "choice", "choice": "forward", "confidence": 0.7,
        "probabilities": {
            "forward": 0.70, "forward_left": 0.03, "forward_right": 0.03,
            "strafe_left": 0.05, "strafe_right": 0.05, "back_left": 0.02,
            "back_right": 0.02, "back": 0.05, "hold": 0.05,
        },
    },
    "aim": {
        "type": "choice", "choice": "straight", "confidence": 0.6,
        "probabilities": {"left": 0.2, "straight": 0.6, "right": 0.2},
    },
    "interaction": {
        "type": "choice", "choice": "neither", "confidence": 0.9,
        "probabilities": {"fire": 0.05, "use": 0.05, "neither": 0.90},
    },
}


class FakeClient:
    """Never touches the network, and answers every question the same way."""

    endpoint = "fake://typesafe"
    model = "fake-1.0"

    def __init__(self, tokens: int = 900):
        self.tokens = tokens
        self.calls = 0

    def ask(self, state, questions, *, model=None, context=None):
        self.calls += 1
        return {
            "model": self.model,
            "answers": {name: ANSWERS[name] for name in questions},
            "usage": {"input_tokens": self.tokens, "output_tokens": 30},
        }


def _controller(client=None):
    return JevDuumController(
        client=client or FakeClient(), assisted=True, prompt_version="v3", pilot="jev-assisted"
    )


def _run(ticks: int, *, decision_rate: float = 10.0, pixels: bool = True):
    modules = load_duum(DUUM_ROOT, frontend=False)
    controller = _controller()
    runtime = DuumRuntime(modules, WAD, "E1M1", 160, 100)
    session = Session(
        runtime, controller, decision_rate=decision_rate, pixels=pixels, frame_every=1
    )
    frames = [session.step() for _ in range(ticks)]
    summary = session.summary()
    session.close()
    return frames, summary


def test_a_headless_session_ticks_without_a_display():
    frames, summary = _run(120)
    assert summary["engine_ticks"] == 120
    assert summary["simulated_seconds"] == pytest.approx(2.0, abs=0.05)


def test_frames_carry_the_engine_pixels_from_its_rgb_buffer():
    frames, _ = _run(30)
    last = frames[-1]
    assert last.rgb is not None
    assert len(last.rgb) == 160 * 100 * 3
    # It is a real frame, not a blank buffer.
    assert len(set(last.rgb[: 160 * 3])) > 1


def test_pixels_can_be_turned_off_for_data_only_frontends():
    frames, summary = _run(30, pixels=False)
    assert frames[-1].rgb is None
    assert summary["frames"] == 0
    assert frames[-1].snapshot is not None


def test_the_model_is_asked_at_the_requested_rate():
    frames, summary = _run(180, decision_rate=10.0)
    # 3 simulated seconds at 10 Hz: allow the first (immediate) plus scheduling.
    assert 25 <= summary["worker_completed"] <= 33
    assert frames[-1].applied >= 25
    assert frames[-1].submitted >= 25


def test_the_controls_reach_the_engine():
    """The fake always says forward, so the agent must have moved."""

    modules = load_duum(DUUM_ROOT, frontend=False)
    runtime = DuumRuntime(modules, WAD, "E1M1", 160, 100)
    session = Session(runtime, _controller(), decision_rate=10.0, pixels=False)
    start = (session.app.px, session.app.py)
    frames = [session.step() for _ in range(120)]
    end = (frames[-1].snapshot.player.x, frames[-1].snapshot.player.y)
    session.close()
    assert (start[0], start[1]) != (end[0], end[1])


def test_pausing_stops_the_engine_and_resuming_continues():
    modules = load_duum(DUUM_ROOT, frontend=False)
    runtime = DuumRuntime(modules, WAD, "E1M1", 160, 100)
    session = Session(runtime, _controller(), decision_rate=10.0, pixels=False)
    for _ in range(30):
        session.step()
    paused_at = session.tick
    session.set_paused(True)
    for _ in range(30):
        session.step()
    assert session.tick == paused_at
    session.set_paused(False)
    session.step()
    assert session.tick == paused_at + 1
    session.close()


def test_the_decision_rate_is_configurable():
    modules = load_duum(DUUM_ROOT, frontend=False)
    runtime = DuumRuntime(modules, WAD, "E1M1", 160, 100)
    session = Session(runtime, _controller(), decision_rate=10.0, pixels=False)
    assert session.set_decision_rate(20.0) == 20.0
    with pytest.raises(ValueError):
        session.set_decision_rate(0)
    session.close()
