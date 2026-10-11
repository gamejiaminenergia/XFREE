"""Pure geometry helpers of the mini-automap overlay."""

import math

from jev_duum.overlays import _risk_color
from jev_duum.world_model import SVG_BOUNDS, duum_to_svg


def test_risk_color_ramps_green_to_red_and_clamps():
    assert _risk_color(0.0) == "#2e7d32"
    assert _risk_color(1.0) == "#e53935"
    assert _risk_color(-3.0) == _risk_color(0.0)
    assert _risk_color(9.0) == _risk_color(1.0)
    mid = _risk_color(0.5)
    assert mid == "#f9a825"


def test_spawn_maps_into_the_svg_bounds_the_overlay_scales():
    minx, maxx, miny, maxy = SVG_BOUNDS
    px, py = duum_to_svg(-416.0, 256.0)
    assert minx <= px <= maxx
    assert miny <= py <= maxy
    assert math.isclose(px, 140.0, abs_tol=0.5)
    assert math.isclose(py, 168.0, abs_tol=0.5)
