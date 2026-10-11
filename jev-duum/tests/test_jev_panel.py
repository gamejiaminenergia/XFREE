from jev_duum.panel import (
    AMBER,
    GREEN,
    RED,
    DeltaCache,
    _percentile,
    _questions_text,
    _threshold_color,
    advance_completed_level,
)


class App:
    def __init__(self, finish):
        self.finish = finish
        self.keys = []

    def key(self, unicode_value, scan, ctrl):
        self.keys.append((unicode_value, scan, ctrl))


def test_completed_level_advances_with_public_space_key():
    app = App(("E1M2", False))
    assert advance_completed_level(app)
    assert app.keys == [(32, 0, False)]


def test_active_level_is_not_advanced():
    app = App(None)
    assert not advance_completed_level(app)
    assert app.keys == []


def test_delta_cache_reports_only_real_changes():
    cache = DeltaCache()
    assert cache.changed("health", 64) is True
    assert cache.changed("health", 64) is False
    assert cache.changed("health", 63) is True
    assert cache.changed("armor", 63) is True  # a different key is independent
    cache.reset("health")
    assert cache.changed("health", 63) is True


def test_meter_threshold_colours_by_danger_and_blinks_when_critical():
    assert _threshold_color(GREEN, 80, 70, 35, 0) == GREEN
    assert _threshold_color(GREEN, 50, 70, 35, 0) == AMBER
    assert _threshold_color(GREEN, 20, 70, 35, 0) == "#7a2020"
    assert _threshold_color(GREEN, 20, 70, 35, 1) == RED
    # No thresholds at all keeps the base colour (armor above its warning line).
    assert _threshold_color(GREEN, 200, None, None, 0) == GREEN


def test_percentile_is_nearest_rank_and_safe_on_empty():
    assert _percentile([], 0.5) is None
    assert _percentile([40, 10, 30, 20], 0.50) == 20
    assert _percentile([40, 10, 30, 20], 0.95) == 30
    assert _percentile([7], 0.99) == 7


def test_questions_text_summarizes_the_request_shape():
    questions = {
        "movement": {
            "type": "choice",
            "instructions": "Choose the safest useful immediate movement.",
            "criteria": {"forward": "advance", "hold": "stay"},
        }
    }
    text = _questions_text(questions)
    assert "MOVEMENT" in text
    assert "forward = advance" in text
    assert "hold = stay" in text
    assert _questions_text(None) == "—"
