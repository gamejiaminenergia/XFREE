"""Pure geometry helpers of the mini-automap overlay."""

import math
from types import SimpleNamespace

import pytest

from jev_duum.overlays import MiniMap, _risk_color
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


def _player_snapshot(x=100.0, y=100.0):
    return SimpleNamespace(
        player=SimpleNamespace(x=x, y=y, angle=0.0),
        visible_enemies=(),
        incoming_projectiles=(),
    )


def test_every_render_resyncs_the_projection_with_the_canvas():
    """A mistimed ``<Configure>`` must not leave the diagram projected wrong.

    ``fit`` reprojects from the canvas's own size, but it only runs when the
    size Tk reports changes.  If a Configure fires while Tk still reports the
    old geometry, the map stays laid out for a box it no longer has and nothing
    redraws it until the next resize: the diagram looks frozen while the rest of
    the panel keeps updating.  ``render`` re-syncs instead of trusting the
    stored size.
    """

    tkinter = pytest.importorskip("tkinter")
    try:
        root = tkinter.Tk()
    except tkinter.TclError:  # pragma: no cover - headless build box
        pytest.skip("no display available for a Tk geometry test")
    try:
        holder = tkinter.Frame(root, width=320, height=220)
        holder.pack(fill="both", expand=True)
        minimap = MiniMap(tkinter, holder, width=320, height=220)
        minimap.canvas.pack(fill="both", expand=True)
        root.geometry("400x300")
        root.update()
        real = (minimap.canvas.winfo_width(), minimap.canvas.winfo_height())

        # The stale state a mistimed Configure leaves behind.
        minimap.width, minimap.height = 999, 777
        minimap.render(_player_snapshot(), None)
        assert (minimap.width, minimap.height) == real

        # And the projection actually follows the real box.
        assert minimap.to_canvas(0.0, 0.0) == (
            minimap._ox + (0.0 - minimap._minx) * minimap.scale,
            minimap._oy + (0.0 - minimap._miny) * minimap.scale,
        )
    finally:
        root.destroy()
