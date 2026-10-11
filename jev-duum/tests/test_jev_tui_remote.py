"""The terminal UI as a client of the HTTP service.

No engine, no network stack beyond ``urllib``: the mapper turns the wire format
into the value the renderers already understand, so the same presentation runs
against a local session or a remote one.
"""

from __future__ import annotations

import json

import pytest

from jev_duum.panel.session import SessionModel
from jev_duum.tui import render
from jev_duum.tui.remote import RemoteSession, frame_from_state

META = {
    "pilot": "jev-assisted", "model": "fake-local", "prompt_version": "v3w",
    "resolution": "320x200", "paused": False, "decision_rate": 10.0,
}

STATE = {
    "tick": 42, "map": "E1M1", "game_time": 12.5, "state": "running",
    "stale": 0, "error": None,
    "controls": {"movement": "forward", "aim": "right", "interaction": "neither",
                 "target": None},
    "player": {"health": 87, "armor": 25, "ammo": 50, "weapon": "shotgun",
               "max_health": 100},
    "episode": {"kills": 3, "items": 2, "damage_received": 18, "unique_sectors": 6,
                "stuck_ticks": 0, "idle_ticks": 0},
    "worker": {"busy": False, "submitted": 5, "completed": 5, "replaced": 1,
               "failed": 0, "applied": 4},
    "link": {"sent": 5, "dropped": 0},
    "decision": {
        "observation_tick": 37, "application_tick": 42,
        "probabilities": {"movement": {"forward": 0.8, "hold": 0.2},
                          "aim": {"left": 0.1, "right": 0.9}},
        "confidence": {"movement": 0.8, "aim": 0.9},
        "proposed": {"movement": "forward", "aim": "right", "interaction": "fire"},
        "applied": {"movement": "forward", "aim": "right", "interaction": "neither"},
        "interventions": [{"kind": "fire-alignment", "proposed": "fire",
                           "applied": "neither", "reason": "no corridor"}],
        "observations": {"movement": "moverse", "aim": "girar"},
        "strategy": {"mission": "clear", "priority": "hunt", "must_move": True,
                     "hold_streak": 0, "max_hold_streak": 5, "status": "engaging",
                     "plan": ["paso"]},
        "model": "fake-local", "prompt_version": "v3w",
        "keys": 13, "questions": 3, "tokens": {"request": 900}, "cost_usd": 0.0001,
        "request_ms": 400.0, "decision_ms": 410.0,
        "prediction_calls": 1, "execution": "single-request",
    },
}


def _text(lines) -> str:
    return "\n".join("".join(text for text, _key in one) for one in lines)


def test_the_wire_format_rebuilds_a_frame_every_box_can_render():
    frame = frame_from_state(STATE, rgb=bytes([9] * (4 * 2 * 3)))
    assert frame.tick == 42
    assert frame.snapshot.player.health == 87
    assert frame.snapshot.map_name == "E1M1"
    assert frame.decision.applied_controls.movement == "forward"
    assert frame.decision.assistance_events[0].kind == "fire-alignment"
    assert frame.log_stats == {"sent": 5, "dropped": 0}
    model = SessionModel()
    model.observe_vitals(frame.snapshot.player, frame.decision)
    model.account(frame.decision)
    boxes = [
        [render.banner(frame, 120)], render.measures(frame, 60),
        render.decision(frame, 90), render.guard(frame, 70), render.why(frame, 70),
        render.strategy(frame, 70), render.link(frame, 70),
        render.telemetry(model, 60), render.events(model, 80), render.balance(model, 60),
    ]
    for box in boxes:
        assert _text(box).strip(), box


def test_the_game_view_keeps_the_engine_aspect_ratio():
    """A cell is two pixels tall, so the fitted grid is not just the free box."""

    # A 320x200 source: 1.6 wide per unit. Fitting by rows first.
    assert render.fitted_cells(320, 200, 40, 12) == (38, 12)
    # Narrow box: the columns limit, and the rows shrink to match.
    assert render.fitted_cells(320, 200, 20, 12) == (20, 6)
    # Degenerate boxes draw nothing rather than something wrong.
    assert render.fitted_cells(320, 200, 1, 12) == (0, 0)
    assert render.fitted_cells(0, 200, 40, 12) == (0, 0)


def test_the_frame_size_comes_from_the_wire_not_from_a_runtime():
    frame = frame_from_state(STATE)
    art = render.game_art(bytes([7] * (4 * 2 * 3)), 4, 2, 4, 2,
                          __import__("jev_duum.tui.colors", fromlist=["basic"]).basic)
    assert len(art) == 1 and len(art[0]) == 4  # 4x2 pixels in a 4x2 cell box: one row
    assert frame.rgb is None  # no pixels requested


def test_a_dead_link_still_maps_into_a_readable_screen():
    frame = frame_from_state({**STATE, "decision": None, "error": "ReadTimeout",
                              "state": "dead"})
    assert frame.decision is None
    assert frame.snapshot.episode.dead is True
    assert "SIN COMUNICACIÓN" in _text([render.banner(frame, 120)])
    assert "esperando" in _text(render.decision(frame, 80))


class _StubSession(RemoteSession):
    """A RemoteSession whose wire is a dictionary: no sockets in the tests."""

    def __init__(self, *, fail_pixels=False):
        self.calls: list[tuple[str, dict | None]] = []
        self._state = STATE
        self.fail_pixels = fail_pixels
        super().__init__("http://stub", pixels=False)

    def _fetch(self, path: str) -> bytes:
        if path == "/api/meta":
            return json.dumps(META).encode()
        if path.startswith("/api/state"):
            return json.dumps(self._state).encode()
        if path == "/api/frame.raw":
            if self.fail_pixels:
                raise OSError("no frame")
            return bytes([1] * (320 * 200 * 3))
        raise AssertionError(f"unexpected GET {path}")

    def _post(self, path: str, payload: dict) -> dict:
        self.calls.append((path, payload))
        if "paused" in payload:
            return {"paused": payload["paused"], "decision_rate": self.decision_rate}
        self.decision_rate = payload.get("decision_rate", self.decision_rate)
        return {"paused": self.paused, "decision_rate": self.decision_rate}


def test_the_remote_session_reads_meta_and_maps_a_step():
    session = _StubSession()
    assert session.meta["model"] == "fake-local"
    assert session.frame_size() == (320, 200)
    frame = session.step()
    assert frame.tick == 42 and frame.rgb is None
    assert session.last_tick == 42


def test_pixels_are_only_fetched_when_asked():
    session = _StubSession()
    session.set_pixels(True)
    assert session.step().rgb is not None
    assert session.frames == 1
    session.set_pixels(False)
    assert session.step().rgb is None
    # and a failing pixel fetch is not fatal: the panel keeps drawing.
    session.set_pixels(True)
    session.fail_pixels = True
    assert session.step().rgb is None


def test_control_goes_to_the_service():
    session = _StubSession()
    assert session.set_paused(True) is True
    assert session.set_decision_rate(4.0) == 4.0
    assert ("/api/control", {"paused": True}) in session.calls
    assert ("/api/control", {"decision_rate": 4.0}) in session.calls
    with pytest.raises(ValueError):
        session.set_decision_rate(0)


def test_the_remote_summary_says_it_was_remote():
    summary = _StubSession().summary(wall_seconds=1.5)
    assert summary["mode"] == "remote" and summary["url"] == "http://stub"
    assert summary["model"] == "fake-local"
