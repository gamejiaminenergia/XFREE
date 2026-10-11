"""Session view-model: the decision stream reduced to bounded display series.

Nothing here knows about Tk.  The dashboard owns one ``SessionModel`` and
feeds it every decision; the zones read the series back out.  Keeping the
buffers out of the widgets is what lets the charts stay throttled and the
geometry invariant hold by construction."""

from __future__ import annotations

from collections import Counter, deque

from .format import _guard_motive, _percentile
from .layout import TELEMETRY_POINTS

HISTORY_POINTS = 64



class SessionModel:
    """What the session has seen so far, as bounded series the zones can draw."""

    def __init__(self, points: int = TELEMETRY_POINTS):
        self.points = int(points)
        self.history: deque = deque(maxlen=HISTORY_POINTS)
        self.history_signature = None
        self.latencies: list[float] = []
        self.cost = 0.0
        self.tokens = 0
        self.decisions = 0
        self.counted = None
        self.confidence: dict = {}
        self.interventions: deque = deque(maxlen=self.points)
        self.rule_counts: Counter = Counter()
        self.tokens_in: deque = deque(maxlen=self.points)
        self.tokens_out: deque = deque(maxlen=self.points)
        self.health: deque = deque(maxlen=self.points)
        self.ammo: deque = deque(maxlen=self.points)
        self.intervention_marks: deque = deque(maxlen=self.points)
        self.max_health = 100
        self.previous_controls = None
        self.applied_controls = None

    def observe_vitals(self, player, decision) -> None:
        """One sample of health/ammo per refresh, plus whether the guard acted."""

        self.max_health = max(1, int(getattr(player, "max_health", 100) or 100))
        self.health.append(player.health)
        self.ammo.append(min(player.ammo, 100))
        self.intervention_marks.append(
            bool(decision is not None and decision.assistance_events)
        )

    def account(self, decision) -> None:
        """Fold one decision into the counters, exactly once per decision."""

        token = (decision.observation_tick, decision.application_tick)
        if token == self.counted:
            return
        self.counted = token
        self.latencies.append(float(decision.decision_ms))
        self.cost += float(decision.cost_usd or 0.0)
        self.tokens += int((decision.input_tokens or {}).get("request", 0) or 0)
        self.decisions += 1
        events = decision.assistance_events or ()
        self.interventions.append(bool(events))
        for event in events:
            self.rule_counts[event.kind] += 1
        request_tokens = int((decision.input_tokens or {}).get("request", 0) or 0)
        self.tokens_in.append(request_tokens)
        usage = (getattr(decision, "response_raw", None) or {}).get("usage") or {}
        try:
            self.tokens_out.append(int(usage.get("output_tokens") or 0))
        except (TypeError, ValueError):
            self.tokens_out.append(0)
        for axis, value in (decision.confidence or {}).items():
            if value is None:
                continue
            self.confidence.setdefault(
                axis, deque(maxlen=self.points)
            ).append(float(value))
        self.previous_controls = self.applied_controls
        self.applied_controls = decision.applied_controls
        self.history.appendleft(
            {
                "n": self.decisions,
                "tick": decision.observation_tick,
                "movement": decision.applied_controls.movement,
                "aim": decision.applied_controls.aim,
                "interaction": decision.applied_controls.interaction,
                "target": getattr(decision.applied_controls, "target", None),
                "confidence": max(
                    (value for value in decision.confidence.values() if value is not None),
                    default=None,
                ),
                "ms": float(decision.decision_ms or 0.0),
                "guard": _guard_motive(decision.assistance_events),
            }
        )
        self.history_signature = None

    @property
    def samples(self) -> int:
        return len(self.latencies)

    def percentile(self, fraction):
        return _percentile(self.latencies, fraction)

    def movement_counts(self):
        return Counter(item["movement"] for item in self.history)

    def interaction_counts(self):
        return Counter(item["interaction"] for item in self.history)
