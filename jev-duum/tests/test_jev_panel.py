from jev_duum.panel import advance_completed_level


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
