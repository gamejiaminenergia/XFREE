"""Exact fixed-tick scheduling primitives for deterministic Duum runs."""

from __future__ import annotations

from fractions import Fraction


class FixedClock:
    """A host-compatible integer 60 Hz clock advanced only by the adapter."""

    def __init__(self, tick: int = 0):
        self.tick = int(tick)

    def __call__(self) -> int:
        return self.tick

    def advance(self, count: int = 1) -> int:
        if count < 0:
            raise ValueError("clock advance must be non-negative")
        self.tick += count
        return self.tick


class FractionalScheduler:
    """Return exact decision boundaries for rational rates over engine ticks."""

    def __init__(self, tick_rate=60, decision_rate=12, *, due_initially=True):
        self.tick_rate = Fraction(str(tick_rate))
        self.decision_rate = Fraction(str(decision_rate))
        if self.tick_rate <= 0 or self.decision_rate <= 0:
            raise ValueError("tick and decision rates must be positive")
        if self.decision_rate > self.tick_rate:
            raise ValueError("decision rate cannot exceed tick rate")
        self.credit = self.tick_rate if due_initially else Fraction(0)
        self.decisions = 0

    def due(self) -> bool:
        if self.credit < self.tick_rate:
            return False
        self.credit -= self.tick_rate
        self.decisions += 1
        return True

    def advance(self, ticks: int = 1) -> None:
        if ticks < 0:
            raise ValueError("ticks must be non-negative")
        self.credit += self.decision_rate * ticks
