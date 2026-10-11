"""The service and the hub.  No engine here: frames are fabricated."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from jev_service.app import create_app, palette_css
from jev_service.frames import PNG_MAGIC, decode_png_size, encode_png
from jev_service.hub import Hub, compact
from jev_service.server import build_parser


def _controls(movement="forward", aim="right", interaction="neither"):
    return SimpleNamespace(movement=movement, aim=aim, interaction=interaction, target=None)


def _frame(*, rgb=None, tick=42, with_decision=True):
    """A stand-in for jev_duum.session.core.Frame: only what the hub reads."""

    episode = SimpleNamespace(
        game_time=12.5, kills=3, items=2, damage_received=18, unique_sectors=6,
        stuck_ticks=0, idle_ticks=0, dead=False, finished=False,
    )
    player = SimpleNamespace(
        health=100, armor=25, ammo=50, weapon_name="shotgun", max_health=100,
    )
    snapshot = SimpleNamespace(
        map_name="E1M1", tick=tick, player=player, episode=episode,
        to_dict=lambda: {"tick": tick, "map_name": "E1M1"},
    )
    decision = None
    if with_decision:
        decision = SimpleNamespace(
            observation_tick=tick - 5, application_tick=tick,
            probabilities={"movement": {"forward": 0.8, "hold": 0.2}},
            confidence={"movement": 0.8},
            proposed_controls=_controls(), applied_controls=_controls(),
            assistance_events=[SimpleNamespace(kind="aim-guidance", proposed="right",
                                               applied="left", reason="r")],
            observations={"movement": "moverse"}, strategy={"mission": "clear"},
            model_id="fake-1.0", prompt_version="v3w", input_tokens={"request": 900},
            cost_usd=0.0001, request_ms=400.0, decision_ms=410.0,
        )
    return SimpleNamespace(
        tick=tick, snapshot=snapshot, decision=decision, controls=_controls(),
        stale=0, error=None, busy=False, submitted=5, completed=5, replaced=0,
        failed=0, applied=5, log_stats={"sent": 5, "dropped": 0}, rgb=rgb,
    )


# ── the PNG encoder ─────────────────────────────────────────────────────────
def test_the_png_carries_the_size_and_the_pixels():
    rgb = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])  # 2x2
    png = encode_png(rgb, 2, 2)
    assert png.startswith(PNG_MAGIC)
    assert decode_png_size(png) == (2, 2)
    assert b"IHDR" in png and b"IDAT" in png and b"IEND" in png


def test_the_png_refuses_a_buffer_that_is_not_the_declared_size():
    with pytest.raises(ValueError):
        encode_png(b"\x00" * 10, 4, 4)
    with pytest.raises(ValueError):
        decode_png_size(b"not a png")


# ── the hub ─────────────────────────────────────────────────────────────────
def test_the_hub_keeps_the_latest_state_and_encodes_the_frame_once():
    hub = Hub()
    hub.set_frame_size(2, 2)
    assert hub.state() is None and hub.png() is None
    hub.publish(_frame(rgb=bytes([0, 0, 0] * 4)))
    assert hub.state()["tick"] == 42
    first = hub.png()
    assert first is not None and first[0].startswith(PNG_MAGIC)
    # published again without a new frame: the cached PNG is reused.
    assert hub.png()[0] is first[0]
    hub.publish(_frame(tick=43, rgb=bytes([255, 255, 255] * 4)))
    assert hub.png()[0] is not first[0]


def test_a_slow_subscriber_loses_frames_and_never_blocks_the_engine():
    hub = Hub(queue_size=1)
    subscriber = hub.subscribe()
    hub.publish(_frame(tick=1))
    hub.publish(_frame(tick=2))
    hub.publish(_frame(tick=3))
    payload = subscriber.get_nowait()
    assert payload["state"]["tick"] == 3  # the freshest wins
    hub.unsubscribe(subscriber)
    hub.publish(_frame(tick=4))  # no subscriber: publishing still works


def test_the_compact_state_has_the_shape_the_web_reads():
    state = compact(_frame())
    assert state["map"] == "E1M1" and state["state"] == "running"
    assert state["decision"]["applied"]["movement"] == "forward"
    assert state["decision"]["interventions"][0]["kind"] == "aim-guidance"
    assert state["snapshot"] == {"tick": 42, "map_name": "E1M1"}
    assert json.dumps(state)  # it must be JSON-serialisable


# ── the app ─────────────────────────────────────────────────────────────────
def _client(*, token=None):
    hub = Hub()
    hub.set_frame_size(2, 2)
    hub.publish(_frame(rgb=bytes([255, 0, 0] * 4)))
    session = SimpleNamespace(paused=False, decision_rate=10.0,
                              set_paused=lambda v: setattr(session, "paused", bool(v)),
                              set_decision_rate=lambda v: setattr(session, "decision_rate", v))
    app = create_app(hub, session, meta={"pilot": "jev-assisted"}, control_token=token)
    return TestClient(app), hub, session


def test_health_and_state_answer():
    client, _hub, _session = _client()
    assert client.get("/health").json()["ok"] is True
    state = client.get("/api/state").json()
    assert state["tick"] == 42
    # full=0 drops the heavy snapshot, for a light poll.
    assert "snapshot" not in client.get("/api/state?full=0").json()


def test_the_frame_endpoint_returns_a_real_png():
    client, _hub, _session = _client()
    response = client.get("/api/frame.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_MAGIC)


def test_the_page_is_served_with_the_palette_from_theme():
    client, _hub, _session = _client()
    page = client.get("/").text
    assert "SCADA" in page
    assert "--alarm:" in page and "--warn:" in page
    assert "/* PALETTE */" not in page
    assert "__META__" not in page


def test_control_pauses_and_sets_the_rate():
    client, _hub, session = _client()
    assert client.post("/api/control", json={"paused": True}).json()["paused"] is True
    assert session.paused is True
    assert client.post("/api/control", json={"decision_rate": 4}).json()["decision_rate"] == 4


def test_control_needs_the_token_when_one_is_configured():
    client, _hub, _session = _client(token="s3cret")
    assert client.post("/api/control", json={"paused": True}).status_code == 403
    ok = client.post("/api/control", json={"paused": True}, headers={"x-control-token": "s3cret"})
    assert ok.status_code == 200


def test_the_palette_css_comes_from_the_single_home():
    assert "--bg: #000000;" in palette_css()
    assert "--alarm: #ff0000;" in palette_css()


def test_the_cli_defaults_are_local_and_fake_is_opt_in():
    args = build_parser().parse_args([])
    assert args.host == "127.0.0.1"  # never exposed by default
    assert args.fake is False and args.control_token is None
    assert args.decision_rate == 10.0
