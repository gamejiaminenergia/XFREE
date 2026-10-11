import pytest

from jev_duum.scheduler import FixedClock, FractionalScheduler


@pytest.mark.parametrize("decision_rate", [5, 7, 12, 20])
def test_fractional_scheduler_has_exact_ten_second_counts(decision_rate):
    scheduler = FractionalScheduler(60, decision_rate)
    boundaries = 0
    for _ in range(600):
        boundaries += scheduler.due()
        scheduler.advance()
    assert boundaries == decision_rate * 10
    assert scheduler.decisions == boundaries


def test_fixed_clock_advances_only_when_requested():
    clock = FixedClock(10)
    assert clock() == 10
    assert clock.advance() == 11
    assert clock.advance(4) == 15
    with pytest.raises(ValueError):
        clock.advance(-1)


def test_scheduler_rejects_impossible_or_invalid_rates():
    with pytest.raises(ValueError):
        FractionalScheduler(60, 61)
    with pytest.raises(ValueError):
        FractionalScheduler(0, 1)
    with pytest.raises(ValueError):
        FractionalScheduler(60, 0)
