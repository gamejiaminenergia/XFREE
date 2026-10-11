"""The terminal frontend: the pure presentation and the palette mapping.

The curses loop itself is exercised by the smoke run in ``tools/`` (it needs a
tty); everything that can be decided without a terminal is decided here.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jev_duum.panel.session import SessionModel
from jev_duum.session.core import Frame
from jev_duum.tui import colors, render


def _controls(movement="forward", aim="right", interaction="neither"):
    return SimpleNamespace(movement=movement, aim=aim, interaction=interaction, target=None)


def _decision(**overrides):
    base = dict(
        observation_tick=120,
        application_tick=121,
        applied_controls=_controls(),
        proposed_controls=_controls(aim="straight"),
        assistance_events=(),
        confidence={"movement": 0.8, "aim": 0.7, "interaction": 0.5},
        probabilities={
            "movement": {"forward": 0.8, "hold": 0.2},
            "aim": {"left": 0.1, "straight": 0.2, "right": 0.7},
            "interaction": {"fire": 0.1, "use": 0.1, "neither": 0.8},
        },
        observations={"movement": "moverse", "aim": "girar", "interaction": "disparar"},
        strategy={
            "mission": "clear", "priority": "hunt", "must_move": True, "hold_streak": 0,
            "max_hold_streak": 5, "status": "engaging", "plan": ["paso 1", "paso 2"],
        },
        model_id="fake-1.0", prompt_version="v3w", input_tokens={"request": 900},
        cost_usd=0.0001, response_raw={"usage": {"output_tokens": 30}},
        request_state={"tick": 1}, request_questions={"movement": {}},
        request_ms=400.0, decision_ms=410.0, prediction_calls=1, execution="single-request",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _frame(**overrides):
    player = SimpleNamespace(health=100, armor=25, ammo=50, weapon_name="shotgun")
    episode = SimpleNamespace(
        game_time=12.5, kills=3, items=2, damage_received=18, unique_sectors=6,
        stuck_ticks=0, idle_ticks=0, dead=False, finished=False,
    )
    snapshot = SimpleNamespace(map_name="E1M1", tick=123, player=player, episode=episode)
    kwargs = dict(
        tick=123, snapshot=snapshot, decision=_decision(), controls=_controls(),
        stale=0, error=None, busy=False, submitted=5, completed=5, replaced=0,
        failed=0, applied=5, log_stats=None, rgb=None,
    )
    kwargs.update(overrides)
    return Frame(**kwargs)


def _text(lines) -> str:
    return "\n".join("".join(text for text, _key in line) for line in lines)


def test_the_banner_identifies_the_run_and_the_link():
    text = _text([render.banner(_frame(), 120)])
    assert "SCADA+IA+JEV+DOOM" in text
    assert "E1M1" in text and "TICK 123" in text and "EN MARCHA" in text


def test_the_banner_spells_out_a_broken_or_stale_link():
    assert "SIN COMUNICACIÓN" in _text([render.banner(_frame(error="ReadTimeout"), 120)])
    assert "DATOS OBSOLETOS" in _text([render.banner(_frame(stale=9), 120)])


def test_the_decision_shows_the_best_choice_its_bar_and_its_band():
    rows = render.decision(_frame(), 90)
    text = _text(rows)
    assert "MOV" in text and "FORWARD" in text and "ALTA 0.80" in text
    assert "APU" in text and "RIGHT" in text
    assert "ACC" in text and "NEITHER" in text
    # the winning fraction is printed next to its bar.
    assert "0.80" in text and "0.70" in text


def test_without_a_decision_the_screen_says_so_and_stays_readable():
    rows = render.decision(_frame(decision=None), 90)
    assert "esperando" in _text(rows)
    assert "sin datos del enlace" in _text(render.link(_frame(decision=None), 60))


def test_a_dead_link_mutes_the_chosen_answer():
    text = _text(render.decision(_frame(error="ReadTimeout"), 90))
    assert "SIN DATO" in text


def test_the_guard_box_shows_proposed_applied_and_the_interventions():
    free = _text(render.guard(_frame(), 70))
    assert "SIN INTERVENCION" in free and "PROPUESTO" in free and "APLICADO" in free

    event = SimpleNamespace(kind="aim-guidance", proposed="fire", applied="neither", reason="r")
    caught = _text(render.guard(_frame(decision=_decision(assistance_events=(event,))), 70))
    assert "INTERVINO x1" in caught and "aim-guidance" in caught


def test_the_game_view_is_two_engine_pixels_per_cell():
    rgb = bytes([255, 0, 0] * 16)
    art = render.game_art(rgb, 4, 4, 4, 2, colors.basic)
    assert len(art) == 2 and len(art[0]) == 4
    assert all(char == render.UPPER_HALF for _fg, _bg, char in art[0])
    assert art[0][0][0] == 1  # red, quantised to the basic palette
    # and nothing at all when there is no frame to draw.
    assert render.game_art(None, 4, 4, 4, 2, colors.basic) == []


@pytest.mark.parametrize("width", (40, 72, 120))
def test_every_box_fits_the_width_it_is_given(width):
    """A TUI cell has the width it was given: the value is clipped, never the box."""

    frame = _frame()
    model = SessionModel()
    model.observe_vitals(frame.snapshot.player, frame.decision)
    model.account(frame.decision)
    boxes = {
        "banner": [render.banner(frame, width)],
        "measures": render.measures(frame, width),
        "decision": render.decision(frame, width),
        "guard": render.guard(frame, width),
        "why": render.why(frame, width),
        "strategy": render.strategy(frame, width),
        "link": render.link(frame, width),
        "telemetry": render.telemetry(model, width),
        "events": render.events(model, width),
        "balance": render.balance(model, width),
    }
    for name, lines in boxes.items():
        for one in lines:
            assert sum(len(text) for text, _key in one) <= width, (name, width, _text([one]))


def test_a_long_value_is_clipped_not_widened():
    frame = _frame(
        snapshot=SimpleNamespace(
            map_name="E1M1" * 40,
            tick=123,
            player=SimpleNamespace(health=100, armor=25, ammo=50, weapon_name="x" * 60),
            episode=SimpleNamespace(
                game_time=12.5, kills=3, items=2, damage_received=18, unique_sectors=6,
                stuck_ticks=0, idle_ticks=0, dead=False, finished=False,
            ),
        )
    )
    for one in render.measures(frame, 30):
        assert sum(len(text) for text, _key in one) <= 30


def test_the_telemetry_and_events_read_the_session_model():
    model = SessionModel()
    for index in range(3):
        decision = _decision(observation_tick=100 + index, application_tick=101 + index)
        model.observe_vitals(SimpleNamespace(health=80, ammo=40, max_health=100), decision)
        model.account(decision)
    assert "p50" in _text(render.telemetry(model, 60))
    assert "#0003" in _text(render.events(model, 80))
    assert "MOV forward" in _text(render.balance(model, 60))


def test_the_palette_maps_every_semantic_key_once():
    resolved = colors.resolve(colors=256)
    assert set(resolved) == set(colors.FOREGROUND)
    assert resolved["title"] != resolved["alarm"]
    # 256-colour indexes stay in range, and the 8-colour fallback too.
    assert all(0 <= value <= 255 for value in resolved.values())
    assert all(0 <= value <= 7 for value in colors.resolve(colors=8).values())


def test_the_basic_quantiser_is_stable_and_in_range():
    assert colors.basic(0, 0, 0) == 0
    assert colors.basic(255, 255, 255) == 7
    assert colors.basic(255, 0, 0) == 1
    assert colors.basic(120, 200, 60) in (2, 3)
    assert colors.basic(255, 200, 0) == 3
    with pytest.raises(ValueError):
        colors.to_256("nope")
