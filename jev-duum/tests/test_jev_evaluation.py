from jev_duum.evaluation import _score


def summary(*, finished, game_time, health=50):
    return {
        "final": {
            "episode": {
                "finished": finished,
                "game_time": game_time,
                "kills": 1,
                "items": 1,
                "unique_sectors": 2,
            },
            "player": {"health": health},
        },
        "assistance_interventions": 10,
    }


def test_completion_dominates_and_faster_completion_scores_higher():
    incomplete = _score(summary(finished=False, game_time=60), 3600)
    slow = _score(summary(finished=True, game_time=55), 3600)
    fast = _score(summary(finished=True, game_time=40), 3600)
    assert fast > slow > incomplete
