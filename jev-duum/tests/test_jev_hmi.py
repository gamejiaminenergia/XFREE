"""The HMI's invariants: a section never follows the data it displays.

A panel, a cell or a state block is a fixed piece of the screen.  If its width
or height followed its content, every box beside it would move on every
refresh and the operator would have to re-find the information each time.

This drives the real :class:`~jev_duum.panel.Dashboard` through deliberately
hostile states — long and short values in every field, no world model, no
model at all, every decision stale — and asserts that the geometry of every box
is byte-identical to the first state, and identical again when the data goes
back to normal.

It needs a display; without one the module is skipped.
"""

from __future__ import annotations

import tkinter
from types import SimpleNamespace

import pytest

from jev_duum import panel as panel_module
from jev_duum.panel import Dashboard


class _Canvas:
    w = 320
    h = 200


class FakeWindow:
    """The smallest object ``Dashboard`` needs: a root, a canvas and a scale."""

    def __init__(self, root):
        self.root = root
        self.cv = _Canvas()
        self.scale = 2
        self.running = True
        self.app = SimpleNamespace(quit=False)
        self.tkcv = tkinter.Canvas(root, width=640, height=400, bg="black")
        self.tkcv.pack()

    def _close(self):  # pragma: no cover - never reached in the test
        pass


class FakeWorker:
    def __init__(self):
        self.busy = False
        self.stats = SimpleNamespace(completed=1, replaced=0)


def _snapshot(*, health=100, tick=7, weapon="pistol", game_time=1.0, kills=0, stuck=0):
    player = SimpleNamespace(
        x=100.0, y=100.0, angle=0.0, health=health, armor=0, weapon=1,
        weapon_name=weapon, ammo=50, keys=0, damage_since_last=0, max_health=1000,
    )
    episode = SimpleNamespace(
        game_time=game_time, kills=kills, items=0, damage_received=0, live_enemies=1,
        projectiles=0, unique_sectors=1, stuck_ticks=stuck, idle_ticks=0, dead=False,
        finished=False, monsters_remaining=0, monsters_awake=0,
    )
    return SimpleNamespace(
        tick=tick, map_name="E1M1", player=player, visible_enemies=(),
        incoming_projectiles=(), episode=episode,
    )


def _readout(*, available=True, **overrides):
    """A world readout as ``read_world`` would build it, with hostile strings."""

    base = dict(
        available=available, heading_deg=0.0, position_px=(0.0, 0.0), sector_values=(),
        room="START", room_kind="normal", floor="floor", standing_on="floor", nukage=False,
        route_steps=3, route_rooms=("START", "NUKAGE"), hidden_foes=16, foes_total=17,
        foes_in_sight=1, worst_risk=0.206, worst_sector=8, overall_risk=0.026,
        recommended_bearing_degrees=10.0, recommended_target="exit", top_threats=(),
        top_aspirations=(),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _decision(*, events=0, axes=3, model="jev-preview-1.0", prompt="v3w",
              reason="motivo", observation="moverse", status="estado"):
    names = (
        ("movement", "strafe_left"), ("aim", "right"),
        ("interaction", "fire"), ("target", "target_1"),
    )[:axes]
    controls = SimpleNamespace(
        movement="strafe_left", aim="left", interaction="neither", target=None
    )
    return SimpleNamespace(
        observation_tick=5,
        application_tick=6,
        applied_controls=controls,
        proposed_controls=controls,
        confidence=dict.fromkeys((name for name, _ in names), 0.8),
        probabilities={name: {value: 0.5, "other": 0.5} for name, value in names},
        assistance_events=[
            SimpleNamespace(kind="fire-alignment", reason=reason, proposed="fire",
                            applied="neither")
            for _ in range(events)
        ],
        observations={name: observation for name, _ in names},
        strategy={
            "mission": "advance", "priority": "advance", "must_move": True,
            "hold_streak": 0, "max_hold_streak": 5, "status": status,
            "plan": ["paso"],
        },
        decision_ms=2.0,
        cost_usd=0.00005,
        input_tokens={"request": 1180},
        model_id=model,
        prompt_version=prompt,
        request_state={"a": 1, "b": {"c": 2}},
        request_questions={
            "movement": {
                "type": "choice",
                "instructions": {"task": "decidir"},
                "criteria": {"forward": {}, "hold": {}},
            }
        },
        response_raw={"answers": {"movement": {"choice": "strafe_left"}}},
        request_ms=1.0,
        prediction_calls=1,
        execution="single-request",
        hunt=None,
    )


def _geometry(panel):
    """Every box on screen, by position and size."""

    boxes = {
        "banner": panel.banner,
        "bottom": panel.bottom,
        "center": panel.center,
        "right": panel.right,
        "decision": panel.decision_panel.frame,
        "guard": panel.guard_panel.frame,
        "why": panel.why_panel.frame,
        "strategy": panel.strategy_panel.frame,
        "minimap": panel.minimap.canvas,
        "measures": panel.health.frame.master.master,
        "threats": panel.world_threats,
        "live": panel.live_label,
        "map_label": panel.map_label,
        "cost": panel.cost_label,
        "alarm": panel.alarm_count,
        "room": panel.world_fields["room"],
        "route": panel.world_fields["route"],
        "risk": panel.world_fields["risk"],
        "bar_health": panel.health.canvas,
        "bar_value": panel.health.value,
        "axis_bar": panel.axes["movement"].canvas,
        "axis_choice": panel.axes["movement"].choice,
        "axis_breakdown": panel.axes["movement"].breakdown,
        "axis_conf": panel.axes["movement"].conf.label,
        "guard_flag": panel.guard_flag.label,
        "guard_title": panel.guard_panel.title,
        "decision_flag": panel.decision_flag.label,
        "link_flag": panel.link_flag.label,
        "guard_proposed": panel.guard_fields["prop"],
        "guard_applied": panel.guard_fields["appl"],
        "why_move": panel.observations["movement"],
        "why_aim": panel.observations["aim"],
        "strategy_head": panel.strategy_head,
        "request_model": panel.request_fields["model"],
        "request_prompt": panel.request_fields["prompt"],
        "response_age": panel.response_fields["age"],
        "state_index": panel.state_index_text,
        "response_raw": panel.response_raw_text,
        "kpi": panel._tiles["decisions"],
        "kpi_p95": panel._tiles["p95"],
        "kpi_caption": panel._tile_captions["p50"][0],
        "event_number": panel._event_cells[0][0],
        "event_state": panel._event_cells[0][8],
        "event_motive": panel._event_cells[0][9],
        "event_note": panel._event_note,
        # The session telemetry: fixed-size canvases and one clipped line, so
        # they hold the same invariant as every numbered panel.
        "latency": panel.latency_spark.canvas,
        "confidence": panel.confidence_spark.canvas,
        "intervention": panel.intervention.canvas,
        "actions": panel.action_bars.canvas,
        "vital": panel.vital_trace.canvas,
        "consumption": panel.consumption.canvas,
        "policy_delta": panel.policy_delta.value,
        "balance": panel._balance_panel.frame,
    }
    return {
        name: (widget.winfo_x(), widget.winfo_y(),
               widget.winfo_width(), widget.winfo_height())
        for name, widget in boxes.items()
    }


@pytest.fixture
def dashboard(monkeypatch):
    try:
        root = tkinter.Tk()
    except tkinter.TclError:  # pragma: no cover - headless build box
        pytest.skip("no display available for a Tk geometry test")
    root.resizable(True, True)
    window = FakeWindow(root)
    panel = Dashboard(tkinter, window, fullscreen=False)
    root.geometry("1600x1000+0+0")
    root.update()
    panel._relayout(1600, 1000)
    root.update()

    state = {"readout": _readout()}
    monkeypatch.setattr(panel_module, "read_world", lambda _snapshot: state["readout"])
    yield panel, root, state
    root.destroy()


def _draw(panel, root, state, snapshot, decision, readout, *, pilot="jev-assisted",
          stale=0, error=None):
    state["readout"] = readout
    panel.update(
        pilot=pilot, snapshot=snapshot, decision=decision,
        controls=decision.applied_controls, worker=FakeWorker(),
        stale=stale, error=error, log_stats=None,
    )
    root.update()


def test_every_section_keeps_its_geometry_when_the_data_changes(dashboard):
    panel, root, state = dashboard

    states = [
        # Normal.
        dict(snapshot=_snapshot(), decision=_decision(), readout=_readout()),
        # Everything long at once: eight-digit tick, absurd weapon and pilot
        # names, seven interventions with 200-character reasons, a fourth typed
        # question, a long observation, a long strategy, a long route and three
        # threats with wide numbers.
        dict(
            snapshot=_snapshot(health=22, tick=99999999, weapon="super-shotgun-deluxe",
                               game_time=99999.9, kills=99, stuck=999),
            decision=_decision(events=7, axes=4, model="jev-latest-with-a-long-name",
                               prompt="v4-experimental-world-model", reason="r" * 200,
                               observation="hp=100 armor=0 projectile=none " * 8,
                               status="s" * 200),
            readout=_readout(
                room="NUKAGE YARD", room_kind="water-pool-with-a-long-name",
                route_steps=12, route_rooms=("START", "NUKAGE YARD", "ARENA", "EXIT"),
                hidden_foes=12345, foes_total=99999, foes_in_sight=1234,
                worst_risk=0.9876, worst_sector=123, overall_risk=0.5432,
                top_threats=(
                    {"bearing_degrees": -179.5, "distance_px": 99999.0,
                     "threat_score": 0.9876, "line_of_sight": True},
                    {"bearing_degrees": 123.5, "distance_px": 54321.0,
                     "threat_score": 0.5432, "line_of_sight": False},
                    {"bearing_degrees": -1.5, "distance_px": 1.0,
                     "threat_score": 0.0123, "line_of_sight": True},
                ),
                recommended_target={"kind": "medkit-with-a-long-name",
                                    "position_px": (12345.0, 67890.0)},
            ),
            pilot="jev-assisted-with-a-very-long-pilot-name", stale=17,
        ),
        # Everything at its floor, and no threats at all: the diagram used to
        # grow when the threat list went from three lines to one.
        dict(snapshot=_snapshot(health=1, tick=0, weapon="fist", game_time=0.0),
             decision=_decision(events=0, axes=3, model="m", prompt="v3",
                                observation="x"),
             readout=_readout(room="A", room_kind=None, route_steps=0, route_rooms=(),
                              hidden_foes=0, foes_total=0, foes_in_sight=0,
                              worst_risk=0.0, worst_sector=0, overall_risk=0.0,
                              recommended_target=None)),
        # No world model at all.
        dict(snapshot=_snapshot(), decision=_decision(), readout=_readout(available=False)),
        # No model at all.
        dict(snapshot=_snapshot(), decision=_decision(), readout=_readout(),
             error="ReadTimeout: api.typesafe.ai did not answer in 20s"),
        # Every decision stale.
        dict(snapshot=_snapshot(), decision=_decision(), readout=_readout(), stale=99),
        # Back to normal: it has to land on the same pixels.
        dict(snapshot=_snapshot(), decision=_decision(), readout=_readout()),
    ]

    _draw(panel, root, state, **states[0])
    reference = _geometry(panel)

    for index, case in enumerate(states[1:], start=1):
        _draw(panel, root, state, **case)
        moved = {
            name: (reference[name], value)
            for name, value in _geometry(panel).items()
            if value != reference[name]
        }
        assert not moved, f"state {index} moved {sorted(moved)}: {moved}"
