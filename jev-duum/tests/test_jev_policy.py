"""The session tick policy, pinned as a truth table.

These rules used to live inline inside ``run_jev_window`` with no tests of their
own, which made the loop the one place where a refactor could change behaviour
silently.  They are pure functions now, and this is their contract.
"""

from __future__ import annotations

import pytest

from jev_duum.session import policy
from jev_duum.types import DuumControls


def test_result_is_accepted_while_it_is_fresh():
    assert policy.accept_result(
        tick=100, observation_tick=90, minimum_observation_tick=0, max_stale_ticks=30
    )


def test_result_is_rejected_once_it_is_too_old():
    assert not policy.accept_result(
        tick=100, observation_tick=69, minimum_observation_tick=0, max_stale_ticks=30
    )
    # exactly at the limit is still usable: the comparison is inclusive.
    assert policy.accept_result(
        tick=100, observation_tick=70, minimum_observation_tick=0, max_stale_ticks=30
    )


def test_result_from_the_previous_level_is_rejected_even_if_recent():
    """After a level change, a fresh-looking decision is from the old level."""

    assert not policy.accept_result(
        tick=205, observation_tick=200, minimum_observation_tick=201, max_stale_ticks=30
    )
    assert policy.accept_result(
        tick=205, observation_tick=202, minimum_observation_tick=201, max_stale_ticks=30
    )


def _submit(**overrides):
    base = dict(
        now=10.0, next_decision_time=10.0, model_error=None, dead=False,
        finished=False, menu_open=False,
    )
    base.update(overrides)
    return policy.ready_to_submit(**base)


def test_a_decision_is_due_when_the_schedule_says_so():
    assert _submit()
    # a hair of slack, so an instant scheduled for exactly now is not pushed.
    assert _submit(now=9.9999999995)
    assert not _submit(now=9.0)


def test_nothing_is_submitted_after_a_failure_or_into_a_closed_episode():
    assert not _submit(model_error="ReadTimeout")
    assert not _submit(dead=True)
    assert not _submit(finished=True)
    assert not _submit(menu_open=True)


def test_the_schedule_advances_one_interval_and_resynchronises_when_late():
    assert policy.reschedule(10.0, 10.0, previous=10.0) == pytest.approx(10.1)
    assert policy.reschedule(10.0, 10.0, previous=9.0) == pytest.approx(10.1)
    # more than one interval behind: restart from now, never a backlog.
    assert policy.reschedule(10.5, 10.0, previous=9.0) == pytest.approx(10.6)


def test_the_intermission_is_held_then_released_once():
    since, just_finished, due = policy.observe_intermission(
        finished=True, since=None, now=5.0
    )
    assert (since, just_finished, due) == (5.0, True, False)

    since, just_finished, due = policy.observe_intermission(
        finished=True, since=5.0, now=5.9
    )
    assert (since, just_finished, due) == (5.0, False, False)

    since, just_finished, due = policy.observe_intermission(
        finished=True, since=5.0, now=6.0
    )
    assert (since, just_finished, due) == (5.0, False, True)


def test_a_running_level_clears_the_intermission_marker():
    assert policy.observe_intermission(finished=False, since=5.0, now=9.0) == (
        None, False, False,
    )


def test_a_fresh_result_clears_the_staleness_counter():
    """It reports the link's health now, not how many slow calls ever happened."""

    assert policy.stale_after(accepted=False, stale=0) == 1
    assert policy.stale_after(accepted=False, stale=3) == 4
    assert policy.stale_after(accepted=True, stale=4) == 0


def test_the_screen_refreshes_on_its_cadence_and_always_while_blind():
    assert policy.should_refresh(tick=4, latest="decision", model_error=None)
    assert not policy.should_refresh(tick=5, latest="decision", model_error=None)
    # no decision yet, or a broken link: refresh every tick.
    assert policy.should_refresh(tick=5, latest=None, model_error=None)
    assert policy.should_refresh(tick=5, latest="decision", model_error="boom")


def test_use_is_released_after_its_application_tick():
    assert policy.release_one_shot(DuumControls(interaction="use")).interaction == "neither"
    for other in ("fire", "neither"):
        controls = DuumControls(interaction=other)
        assert policy.release_one_shot(controls) is controls
