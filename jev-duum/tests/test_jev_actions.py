import pytest

from jev_duum.actions import (
    A_BACK,
    A_FIRE,
    A_FORWARD,
    A_STRAFE_LEFT,
    A_STRAFE_RIGHT,
    A_TURN_LEFT,
    A_TURN_RIGHT,
    A_USE,
    MOVEMENT_MASKS,
    SyntheticInput,
    controls_to_mask,
    ensure_usable_weapon,
)
from jev_duum.types import MOVEMENTS, DuumControls


@pytest.mark.parametrize(
    ("controls", "expected"),
    [
        (DuumControls("forward"), A_FORWARD),
        (DuumControls("back"), A_BACK),
        (DuumControls("strafe_left"), A_STRAFE_LEFT),
        (DuumControls("strafe_right"), A_STRAFE_RIGHT),
        (DuumControls("forward_left"), A_FORWARD | A_STRAFE_LEFT),
        (DuumControls("forward_right"), A_FORWARD | A_STRAFE_RIGHT),
        (DuumControls("back_left"), A_BACK | A_STRAFE_LEFT),
        (DuumControls("back_right"), A_BACK | A_STRAFE_RIGHT),
        (DuumControls(aim="left"), A_TURN_LEFT),
        (DuumControls(aim="right"), A_TURN_RIGHT),
        (DuumControls(interaction="fire"), A_FIRE),
        (DuumControls(interaction="use"), A_USE),
        (DuumControls(), 0),
    ],
)
def test_each_semantic_control_maps_to_documented_host_bit(controls, expected):
    assert controls_to_mask(controls) == expected


def test_control_dimensions_combine_as_a_bitmap():
    controls = DuumControls("strafe_left", "right", "fire")
    assert controls_to_mask(controls) == A_STRAFE_LEFT | A_TURN_RIGHT | A_FIRE


def test_every_movement_token_has_a_host_mask():
    assert set(MOVEMENT_MASKS) == set(MOVEMENTS)


def test_a_diagonal_holds_both_movement_axes_at_once():
    # The whole point of the extra tokens: the mask carries two movement bits,
    # which is what let Duum corner before the adapter could only send one.
    for diagonal, forward_axis, strafe_axis in (
        ("forward_left", "forward", "strafe_left"),
        ("forward_right", "forward", "strafe_right"),
        ("back_left", "back", "strafe_left"),
        ("back_right", "back", "strafe_right"),
    ):
        mask = controls_to_mask(DuumControls(diagonal))
        assert mask == MOVEMENT_MASKS[forward_axis] | MOVEMENT_MASKS[strafe_axis]
        assert mask != MOVEMENT_MASKS[forward_axis]
        assert mask != MOVEMENT_MASKS[strafe_axis]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"movement": "teleport"},
        {"aim": "behind"},
        {"interaction": "jump"},
    ],
)
def test_unknown_controls_are_rejected(kwargs):
    with pytest.raises(ValueError):
        DuumControls(**kwargs)


def test_synthetic_input_owns_and_releases_held_state():
    class Host:
        def __init__(self):
            self.values = []

        def set_keys(self, mask):
            self.values.append(mask)

    host = Host()
    inputs = SyntheticInput(host)
    mask = inputs.apply(DuumControls("forward", "left", "fire"))
    assert mask == A_FORWARD | A_TURN_LEFT | A_FIRE
    assert inputs.mask == mask
    inputs.release()
    assert inputs.mask == 0
    assert host.values == [mask, 0]


def test_dry_gun_falls_back_to_fist_and_collected_ammo_restores_a_gun():
    class Engine:
        WEAP = {
            1: (b"Fist", None, None, 0.55, 0, 0),
            2: (b"Pistol", None, None, 0.42, 1, 1),
            3: (b"Shotgun", None, None, 1.05, 2, 1),
        }

    class App:
        def __init__(self):
            self.weapon = 2
            self.owned = {1, 2, 3}
            self.ammo = [0, 0, 0]
            self.selected = []

        def key(self, uni, scan, ctrl):
            self.selected.append(chr(uni))
            self.weapon = int(chr(uni))

    app = App()
    assert ensure_usable_weapon(app, Engine)
    assert app.weapon == 1
    assert app.selected == ["1"]

    app.ammo[1] = 10
    assert ensure_usable_weapon(app, Engine)
    assert app.weapon == 2
    assert app.selected == ["1", "2"]


def test_weapon_recovery_prefers_non_explosive_weapon():
    class Engine:
        WEAP = {
            1: (b"Fist", None, None, 0.55, 0, 0),
            2: (b"Pistol", None, None, 0.42, 1, 1),
            5: (b"Rockets", None, None, 1.0, 3, 1),
            6: (b"Plasma", None, None, 0.1, 4, 1),
        }

    class App:
        weapon = 1
        owned = {1, 2, 5, 6}
        ammo = [0, 10, 0, 5, 0]

        def __init__(self):
            self.selected = []

        def key(self, uni, scan, ctrl):
            self.selected.append(chr(uni))

    app = App()
    assert ensure_usable_weapon(app, Engine)
    assert app.selected == ["2"]
