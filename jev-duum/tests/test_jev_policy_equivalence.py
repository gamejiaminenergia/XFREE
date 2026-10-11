"""The extracted tick policy is exactly the code that used to be inline.

``run_jev_window`` cannot be compared byte for byte across refactors: the
decision worker is asynchronous, so which snapshot a result came from and how the
strategy tracker advanced depend on thread timing.  That is why this file pins
the *predicates* instead — exhaustively, against the original inline expressions
copied verbatim from the pre-refactor loop (commit 76d4f2e).

If a future refactor changes one of these rules, this fails.
"""

from __future__ import annotations

import itertools

from jev_duum.session import policy


# ── the originals, copied from run_jev_window before the extraction ──────────
def inline_accept(tick, observation_tick, minimum_observation_tick, max_stale_ticks):
    age = tick - observation_tick
    return age <= max_stale_ticks and observation_tick >= minimum_observation_tick


def inline_ready(now, next_decision_time, model_error, dead, finished, menu):
    return (
        model_error is None
        and not dead
        and not finished
        and menu is None
        and now + 1e-9 >= next_decision_time
    )


def inline_reschedule(next_decision_time, now, decision_rate):
    next_decision_time += 1.0 / decision_rate
    if next_decision_time < now:
        next_decision_time = now + 1.0 / decision_rate
    return next_decision_time


def inline_intermission(finished, finish_since, now):
    """The old block, as a value: (new marker, just finished, advance due)."""

    if not finished:
        return None, False, False
    if finish_since is None:
        return now, True, False
    return finish_since, False, (now - finish_since) >= 1.0


def inline_refresh(tick, latest, model_error):
    return tick % 4 == 0 or latest is None or model_error


def test_accept_result_matches_the_inline_rule_everywhere():
    for tick, observation, minimum, stale in itertools.product(
        range(0, 12), range(-2, 12), (0, 5, 9), (0, 3, 30)
    ):
        assert policy.accept_result(
            tick=tick, observation_tick=observation,
            minimum_observation_tick=minimum, max_stale_ticks=stale,
        ) == inline_accept(tick, observation, minimum, stale), (tick, observation, minimum, stale)


def test_ready_to_submit_matches_the_inline_rule_everywhere():
    for now, following, error, dead, finished, menu in itertools.product(
        (0.0, 0.05, 0.1, 0.1000000001, 0.2, 1.0),
        (0.0, 0.1, 0.2),
        (None, "ReadTimeout"),
        (False, True),
        (False, True),
        (None, "menu"),
    ):
        assert policy.ready_to_submit(
            now=now, next_decision_time=following, model_error=error,
            dead=dead, finished=finished, menu_open=menu is not None,
        ) == inline_ready(now, following, error, dead, finished, menu), (
            now, following, error, dead, finished, menu,
        )


def test_reschedule_matches_the_inline_rule_everywhere():
    for previous, now, rate in itertools.product(
        (0.0, 0.05, 0.0999, 0.1, 0.5), (0.0, 0.05, 0.1, 0.5), (10.0, 12.0)
    ):
        assert policy.reschedule(now, rate, previous=previous) == inline_reschedule(
            previous, now, rate
        ), (previous, now, rate)


def test_observe_intermission_matches_the_inline_block_everywhere():
    for finished, since, now in itertools.product(
        (False, True), (None, 0.0, 1.0), (0.0, 0.5, 1.0, 1.5, 2.0)
    ):
        assert policy.observe_intermission(
            finished=finished, since=since, now=now
        ) == inline_intermission(finished, since, now), (finished, since, now)


def test_should_refresh_matches_the_inline_rule_everywhere():
    for tick, latest, error in itertools.product(
        range(0, 12), (None, "decision"), (None, "boom")
    ):
        assert policy.should_refresh(tick=tick, latest=latest, model_error=error) == bool(
            inline_refresh(tick, latest, error)
        ), (tick, latest, error)
