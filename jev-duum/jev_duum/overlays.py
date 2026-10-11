"""Tk overlays for the game view: schematic mini-automap and the stale HUD.

Both widgets are pure presentation.  They read the canonical snapshot (and,
when available, the schematic readout from ``world_readout``) and draw; they
never touch the decision loop, the model state, or the game canvas pixels.
"""

from __future__ import annotations

import math

from .theme import (
    MAP_BACKDROP,
    MAP_DOOR,
    MAP_ENEMY,
    MAP_EXIT,
    MAP_GUIDE,
    MAP_MUTED,
    MAP_NUKAGE,
    MAP_PLAYER,
    MAP_PROJECTILE,
    MAP_ROOM_FILL,
    MAP_ROOM_LINE,
    MAP_STALE_ERROR_BG,
    MAP_STALE_TEXT,
    MAP_STALE_WARN_BG,
    MAP_TARGET,
    MAP_TARGET_ASSISTED,
    MAP_TARGET_TURN,
    MAP_WALL,
    MAP_WATER,
)
from .world_model import SVG_BOUNDS, duum_to_svg, svg_heading_degrees

_GEOMETRY = None


def _geometry():
    """Import the vendored schematic once and cache it (grid build is not free)."""

    global _GEOMETRY
    if _GEOMETRY is None:
        from ._map import sense

        _GEOMETRY = sense
    return _GEOMETRY


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _risk_color(intensity: float) -> str:
    """Green → amber → red ramp for a risk in ``0..1``."""

    t = max(0.0, min(1.0, float(intensity)))
    if t < 0.5:
        lo, hi, k = (46, 125, 50), (249, 168, 37), t / 0.5
    else:
        lo, hi, k = (249, 168, 37), (229, 57, 53), (t - 0.5) / 0.5
    rgb = tuple(int(round(_lerp(lo[i], hi[i], k))) for i in range(3))
    return "#%02x%02x%02x" % rgb


class MiniMap:
    """Schematic automap: walls, sector risk, the agent and its targets."""

    def __init__(self, tkinter, parent, *, width: int = 336, height: int = 232):
        self.width = int(width)
        self.height = int(height)
        self.canvas = tkinter.Canvas(
            parent,
            width=self.width,
            height=self.height,
            bg=MAP_BACKDROP,
            highlightthickness=1,
            highlightbackground=MAP_ROOM_LINE,
        )
        self._last = None
        self._recompute_projection()

    def resize(self, width: int, height: int) -> None:
        """Fit the automap into a new box, keeping the schematic aspect ratio."""

        self.fit(width, height)
        self.canvas.configure(width=self.width, height=self.height)

    def fit(self, width: int, height: int) -> None:
        """Reproject for a box the geometry manager already stretched us to.

        Separate from ``resize`` on purpose: ``resize`` asks the canvas to
        change size, and calling it from the canvas's own ``<Configure>`` made
        the request grow the cell that grew the request until Tk died with
        ``X Error: BadAlloc``.  ``fit`` only redraws.
        """

        width = max(180, int(width))
        height = max(120, int(height))
        if (width, height) == (self.width, self.height):
            return
        self.width = width
        self.height = height
        self._recompute_projection()
        if self._last is not None:
            snapshot, readout, aim_assisted = self._last
            self.render(snapshot, readout, aim_assisted=aim_assisted)

    def _recompute_projection(self):
        """Project the schematic into the canvas's real size.

        The canvas is stretched by its geometry manager, so the widget's own
        size is the truth; ``self.width`` is only a fallback for a canvas that
        has not been mapped yet.  Trusting the stored value drew a map laid out
        for an older, wider box and cropped it.
        """

        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width > 1 and height > 1:
            self.width = width
            self.height = height
        minx, maxx, miny, maxy = SVG_BOUNDS
        pad = 8
        span_x, span_y = maxx - minx, maxy - miny
        scale = min((self.width - 2 * pad) / span_x, (self.height - 2 * pad - 18) / span_y)
        self.scale = scale
        self._minx, self._miny = minx, miny
        self._ox = pad + ((self.width - 2 * pad) - span_x * scale) / 2
        self._oy = pad + ((self.height - 2 * pad - 18) - span_y * scale) / 2

    # -- projection ----------------------------------------------------------
    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return (
            self._ox + (float(x) - self._minx) * self.scale,
            self._oy + (float(y) - self._miny) * self.scale,
        )

    # -- rendering -----------------------------------------------------------
    def render(self, snapshot, readout, *, aim_assisted: bool = False) -> None:
        self._last = (snapshot, readout, bool(aim_assisted))
        canvas = self.canvas
        canvas.delete("all")
        try:
            sense = _geometry()
        except Exception:  # pragma: no cover - schematic is optional
            sense = None
        if sense is not None:
            self._draw_rooms(canvas, sense)
            self._draw_pools(canvas, sense)
            self._draw_walls(canvas, sense)
            self._draw_markers(canvas, sense)

        player = snapshot.player
        px, py = duum_to_svg(player.x, player.y)
        heading = svg_heading_degrees(player.angle)
        cx, cy = self.to_canvas(px, py)

        if readout is not None and readout.sector_values:
            self._draw_sector_risk(canvas, cx, cy, readout)
        self._draw_entities(canvas, snapshot, aim_assisted=aim_assisted)
        self._draw_player(canvas, cx, cy, heading)
        if readout is not None and readout.recommended_bearing_degrees is not None:
            self._draw_guide(canvas, cx, cy, heading, readout.recommended_bearing_degrees)
        self._draw_caption(canvas, readout)

    def _draw_rooms(self, canvas, sense):
        cell = sense.CELL
        for room in sense.ROOMS:
            x1, y1 = self.to_canvas(room.x1 * cell, room.y1 * cell)
            x2, y2 = self.to_canvas((room.x2 + 1) * cell, (room.y2 + 1) * cell)
            canvas.create_rectangle(x1, y1, x2, y2, fill=MAP_ROOM_FILL, outline=MAP_ROOM_LINE)

    def _draw_pools(self, canvas, sense):
        for pool in sense.NUKAGE_POOLS:
            self._oval(canvas, pool["cx"], pool["cy"], pool["rx"], pool["ry"], MAP_NUKAGE)
        water = getattr(sense, "WATER_POOL", None)
        if water:
            self._oval(canvas, water["cx"], water["cy"], water["rx"], water["ry"], MAP_WATER)

    def _oval(self, canvas, cx, cy, rx, ry, color):
        x1, y1 = self.to_canvas(cx - rx, cy - ry)
        x2, y2 = self.to_canvas(cx + rx, cy + ry)
        canvas.create_oval(x1, y1, x2, y2, fill=color, outline="", stipple="gray50")

    def _draw_walls(self, canvas, sense):
        for x1, y1, x2, y2 in sense.WALL_SEGMENTS:
            ax, ay = self.to_canvas(x1, y1)
            bx, by = self.to_canvas(x2, y2)
            canvas.create_line(ax, ay, bx, by, fill=MAP_WALL, width=1)

    def _draw_markers(self, canvas, sense):
        for door in sense.DOORS:
            cx, cy = self.to_canvas(door["x"] + door["w"] / 2, door["y"] + door["h"] / 2)
            canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=MAP_DOOR, outline="")
        for exit_mark in sense.EXITS:
            cx, cy = self.to_canvas(
                exit_mark["x"] + exit_mark["w"] / 2, exit_mark["y"] + exit_mark["h"] / 2
            )
            canvas.create_rectangle(cx - 3, cy - 3, cx + 3, cy + 3, fill=MAP_EXIT, outline="")

    def _draw_sector_risk(self, canvas, cx, cy, readout):
        values = list(readout.sector_values)
        if not values:
            return
        peak = max(values) or 1.0
        sectors = len(values)
        step = 360.0 / sectors
        inner, outer = 13.0, 66.0
        for index, value in enumerate(values):
            intensity = value / peak if peak > 0 else 0.0
            if intensity < 0.15:
                continue
            start = index * step
            points = []
            for sample in range(5):
                theta = math.radians(start + step * sample / 4)
                points.extend((cx + inner * math.cos(theta), cy + inner * math.sin(theta)))
            for sample in range(4, -1, -1):
                theta = math.radians(start + step * sample / 4)
                points.extend((cx + outer * math.cos(theta), cy + outer * math.sin(theta)))
            canvas.create_polygon(
                points,
                fill=_risk_color(intensity),
                outline="",
                stipple="gray50" if intensity < 0.85 else "gray75",
            )

    def _draw_entities(self, canvas, snapshot, *, aim_assisted: bool):
        player = snapshot.player
        placed = []
        for enemy in snapshot.visible_enemies:
            world_angle = player.angle + enemy.bearing
            ex, ey = duum_to_svg(
                player.x + enemy.distance * math.cos(world_angle),
                player.y + enemy.distance * math.sin(world_angle),
            )
            placed.append((enemy, self.to_canvas(ex, ey)))
        target = min(
            snapshot.visible_enemies,
            key=lambda enemy: (abs(enemy.bearing), enemy.distance),
            default=None,
        )
        for enemy, (ex, ey) in placed:
            if enemy is target:
                continue
            radius = 2.5
            canvas.create_oval(
                ex - radius, ey - radius, ex + radius, ey + radius,
                fill=MAP_ENEMY if enemy.attacking else MAP_MUTED, outline="",
            )
        for projectile in snapshot.incoming_projectiles:
            world_angle = player.angle + projectile.bearing
            px, py = duum_to_svg(
                player.x + projectile.distance * math.cos(world_angle),
                player.y + projectile.distance * math.sin(world_angle),
            )
            x, y = self.to_canvas(px, py)
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=MAP_PROJECTILE, outline="")
        if target is not None:
            x, y = next(position for item, position in placed if item is target)
            color = (
                MAP_TARGET_ASSISTED
                if aim_assisted
                else MAP_TARGET
                if target.aligned
                else MAP_TARGET_TURN
            )
            canvas.create_oval(x - 6, y - 6, x + 6, y + 6, outline=color, width=2)
            canvas.create_line(x - 10, y, x - 6, y, fill=color)
            canvas.create_line(x + 6, y, x + 10, y, fill=color)
            canvas.create_line(x, y - 10, x, y - 6, fill=color)
            canvas.create_line(x, y + 6, x, y + 10, fill=color)

    def _draw_player(self, canvas, cx, cy, heading):
        theta = math.radians(heading)
        dx, dy = math.cos(theta), math.sin(theta)
        nx, ny = -dy, dx
        canvas.create_polygon(
            cx + 10 * dx, cy + 10 * dy,
            cx - 5 * dx + 5 * nx, cy - 5 * dy + 5 * ny,
            cx - 5 * dx - 5 * nx, cy - 5 * dy - 5 * ny,
            fill=MAP_PLAYER, outline=MAP_BACKDROP,
        )

    def _draw_guide(self, canvas, cx, cy, heading, bearing_degrees):
        theta = math.radians(heading - float(bearing_degrees))
        dx, dy = math.cos(theta), math.sin(theta)
        nx, ny = -dy, dx
        px, py = cx + 40 * dx, cy + 40 * dy
        canvas.create_polygon(
            px + 5 * dx, py + 5 * dy,
            px - 3 * dx + 4 * nx, py - 3 * dy + 4 * ny,
            px - 3 * dx - 4 * nx, py - 3 * dy - 4 * ny,
            outline=MAP_GUIDE, fill="", width=1,
        )

    def _draw_caption(self, canvas, readout):
        band = self.height - 18
        canvas.create_rectangle(1, band, self.width - 1, self.height - 1, fill=MAP_BACKDROP,
                                outline="")
        if readout is None or not readout.available:
            canvas.create_text(
                8, self.height - 8, anchor="sw", fill=MAP_MUTED,
                text="sin modelo del mundo", font=("DejaVu Sans Mono", 8),
            )
            return
        parts = [readout.room or "?"]
        if readout.standing_on and readout.standing_on != "floor":
            parts.append(readout.standing_on)
        if readout.route_steps is not None:
            parts.append(f"ruta {readout.route_steps}")
        canvas.create_text(
            8, self.height - 8, anchor="sw", fill=MAP_MUTED,
            text=" · ".join(parts), font=("DejaVu Sans Mono", 8),
        )
        self._draw_legend(canvas, band)

    def _draw_legend(self, canvas, band):
        """The map's key, drawn with the marks the map itself uses.

        Unicode arrows and circles standing in for an icon system read as
        decoration; an operator legend shows the actual symbol.
        """

        y = band + 9
        x = self.width - 8
        entries = (
            ("rumbo", MAP_GUIDE),
            ("objetivo", MAP_TARGET),
            ("agente", MAP_PLAYER),
        )
        for label, color in entries:
            text = canvas.create_text(
                x, y, anchor="se", fill=MAP_MUTED, text=label,
                font=("DejaVu Sans Mono", 8),
            )
            left = canvas.bbox(text)[0] - 4
            if label == "agente":
                canvas.create_polygon(
                    left - 8, y - 3, left - 2, y, left - 8, y + 3, fill=color, outline=""
                )
            elif label == "objetivo":
                canvas.create_oval(left - 8, y - 3, left - 2, y + 3, outline=color, width=1)
            else:
                canvas.create_line(left - 8, y, left - 2, y, fill=color)
                canvas.create_line(left - 5, y - 3, left - 2, y, left - 5, y + 3, fill=color)
            x = left - 12


class StaleOverlay:
    """A banner drawn over the game canvas when decisions go stale or fail."""

    def __init__(self, tkinter, canvas, *, height: int = 24):
        self.canvas = canvas
        self.height = int(height)
        self._cached: tuple | None = None

    def update(self, *, stale: int, error: str | None) -> None:
        if error:
            state = ("error", error)
        elif stale > 3:
            state = ("stale", int(stale))
        else:
            state = ("ok",)
        if state == self._cached:
            return
        self._cached = state
        canvas = self.canvas
        canvas.delete("hud")
        if state[0] == "ok":
            return
        width = int(float(canvas["width"]))
        if state[0] == "error":
            color, text = MAP_STALE_ERROR_BG, f"SIN MODELO · {error}"[:80]
        else:
            color, text = MAP_STALE_WARN_BG, f"DECISIONES OBSOLETAS ×{stale}"
        # Solid, not ``stipple="gray50"``: a one-pixel checkerboard shimmers on
        # a projector and reads as texture rather than as an alert.
        canvas.create_rectangle(
            0, 0, width, self.height, fill=color, outline="", tags="hud"
        )
        canvas.create_text(
            width / 2, self.height / 2, text=text, fill=MAP_STALE_TEXT,
            font=("DejaVu Sans Mono", 10, "bold"), tags="hud",
        )
