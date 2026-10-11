"""Tk overlays for the game view: schematic mini-automap and the stale HUD.

Both widgets are pure presentation.  They read the canonical snapshot (and,
when available, the schematic readout from ``world_readout``) and draw; they
never touch the decision loop, the model state, or the game canvas pixels.
"""

from __future__ import annotations

import math

from .world_model import SVG_BOUNDS, duum_to_svg, svg_heading_degrees

# ── palette (kept local so the overlays travel without the panel) ─────────────
BACKDROP = "#0a0c11"
ROOM_FILL = "#111620"
ROOM_LINE = "#232d3d"
WALL = "#556077"
DOOR = "#c9a227"
EXIT = "#ef5350"
NUKAGE = "#2f6b3a"
WATER = "#1f4f6b"
PLAYER = "#65d8ff"
TARGET = "#8ee8a8"
TARGET_TURN = "#ffb74d"
TARGET_ASSISTED = "#ff7043"
ENEMY = "#ef5350"
PROJECTILE = "#ff8a80"
GUIDE = "#b388ff"
MUTED = "#8b93a7"

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
            bg=BACKDROP,
            highlightthickness=1,
            highlightbackground=ROOM_LINE,
        )
        minx, maxx, miny, maxy = SVG_BOUNDS
        pad = 8
        span_x, span_y = maxx - minx, maxy - miny
        scale = min((self.width - 2 * pad) / span_x, (self.height - 2 * pad) / span_y)
        self.scale = scale
        self._minx, self._miny = minx, miny
        self._ox = pad + ((self.width - 2 * pad) - span_x * scale) / 2
        self._oy = pad + ((self.height - 2 * pad) - span_y * scale) / 2

    # -- projection ----------------------------------------------------------
    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return (
            self._ox + (float(x) - self._minx) * self.scale,
            self._oy + (float(y) - self._miny) * self.scale,
        )

    # -- rendering -----------------------------------------------------------
    def render(self, snapshot, readout, *, aim_assisted: bool = False) -> None:
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
            canvas.create_rectangle(x1, y1, x2, y2, fill=ROOM_FILL, outline=ROOM_LINE)

    def _draw_pools(self, canvas, sense):
        for pool in sense.NUKAGE_POOLS:
            self._oval(canvas, pool["cx"], pool["cy"], pool["rx"], pool["ry"], NUKAGE)
        water = getattr(sense, "WATER_POOL", None)
        if water:
            self._oval(canvas, water["cx"], water["cy"], water["rx"], water["ry"], WATER)

    def _oval(self, canvas, cx, cy, rx, ry, color):
        x1, y1 = self.to_canvas(cx - rx, cy - ry)
        x2, y2 = self.to_canvas(cx + rx, cy + ry)
        canvas.create_oval(x1, y1, x2, y2, fill=color, outline="", stipple="gray50")

    def _draw_walls(self, canvas, sense):
        for x1, y1, x2, y2 in sense.WALL_SEGMENTS:
            ax, ay = self.to_canvas(x1, y1)
            bx, by = self.to_canvas(x2, y2)
            canvas.create_line(ax, ay, bx, by, fill=WALL, width=1)

    def _draw_markers(self, canvas, sense):
        for door in sense.DOORS:
            cx, cy = self.to_canvas(door["x"] + door["w"] / 2, door["y"] + door["h"] / 2)
            canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=DOOR, outline="")
        for exit_mark in sense.EXITS:
            cx, cy = self.to_canvas(
                exit_mark["x"] + exit_mark["w"] / 2, exit_mark["y"] + exit_mark["h"] / 2
            )
            canvas.create_rectangle(cx - 3, cy - 3, cx + 3, cy + 3, fill=EXIT, outline="")

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
                fill=ENEMY if enemy.attacking else MUTED, outline="",
            )
        for projectile in snapshot.incoming_projectiles:
            world_angle = player.angle + projectile.bearing
            px, py = duum_to_svg(
                player.x + projectile.distance * math.cos(world_angle),
                player.y + projectile.distance * math.sin(world_angle),
            )
            x, y = self.to_canvas(px, py)
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=PROJECTILE, outline="")
        if target is not None:
            x, y = next(position for item, position in placed if item is target)
            color = (
                TARGET_ASSISTED
                if aim_assisted
                else TARGET
                if target.aligned
                else TARGET_TURN
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
            fill=PLAYER, outline="#0a0c11",
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
            outline=GUIDE, fill="", width=1,
        )

    def _draw_caption(self, canvas, readout):
        canvas.create_rectangle(
            1, self.height - 18, self.width - 1, self.height - 1,
            fill=BACKDROP, outline="",
        )
        if readout is None or not readout.available:
            canvas.create_text(
                8, self.height - 8, anchor="sw", fill=MUTED,
                text="sin modelo del mundo", font=("DejaVu Sans Mono", 8),
            )
            return
        parts = [readout.room or "?"]
        if readout.standing_on and readout.standing_on != "floor":
            parts.append(readout.standing_on)
        if readout.route_steps is not None:
            parts.append(f"ruta {readout.route_steps}")
        canvas.create_text(
            8, self.height - 8, anchor="sw", fill=MUTED,
            text=" · ".join(parts), font=("DejaVu Sans Mono", 8),
        )
        canvas.create_text(
            self.width - 8, self.height - 8, anchor="se", fill=MUTED,
            text="▲ agente  ◎ objetivo  ▸ rumbo", font=("DejaVu Sans Mono", 7),
        )


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
            color, text = "#7f1d1d", f"MODEL ERROR · {error}"[:80]
        else:
            color, text = "#7a4a00", f"DECISIONES OBSOLETAS ×{stale}"
        canvas.create_rectangle(
            0, 0, width, self.height, fill=color, outline="", stipple="gray50",
            tags="hud",
        )
        canvas.create_text(
            width / 2, self.height / 2, text=text, fill="#ffe7c2",
            font=("DejaVu Sans Mono", 10, "bold"), tags="hud",
        )
