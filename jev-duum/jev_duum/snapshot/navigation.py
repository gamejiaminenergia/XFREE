"""Short-range geometry: which way is clear, and where a door or a lift actually leads."""

from __future__ import annotations

import math

from .models import MovementOptionSnapshot


class NavigationSection:
    def _movement_options(self) -> tuple[MovementOptionSnapshot, ...]:
        ca, sa = math.cos(self.app.pa), math.sin(self.app.pa)
        inv = 1.0 / math.sqrt(2.0)
        # The eight ways a Doom player can hold the movement keys: the four
        # cardinals and the four diagonals that combine forward/back with a
        # strafe.  Diagonals are unit-length, so their clearance is comparable
        # with the cardinals' even though Duum steps the raw sum of the axes.
        vectors = {
            "forward": (ca, sa),
            "back": (-ca, -sa),
            "strafe_left": (-sa, ca),
            "strafe_right": (sa, -ca),
            "forward_left": ((ca - sa) * inv, (sa + ca) * inv),
            "forward_right": ((ca + sa) * inv, (sa - ca) * inv),
            "back_left": ((-ca - sa) * inv, (-sa + ca) * inv),
            "back_right": ((-ca + sa) * inv, (-sa - ca) * inv),
        }
        options = []
        for name, (vx, vy) in vectors.items():
            clear = 0.0
            for distance in (5.5, 11.0, 16.0, 32.0, 48.0, 64.0, 80.0, 96.0):
                nx = self.app.px + vx * distance
                ny = self.app.py + vy * distance
                if self.app.blocked(self.app.px, self.app.py, nx, ny, 16, None):
                    break
                clear = distance
            options.append(MovementOptionSnapshot(name, clear, clear >= 32.0))
        return tuple(options)

    @staticmethod

    def _line_sectors(level, line):
        sectors = []
        for side_index in (line[5], line[6]):
            if side_index != 0xFFFF:
                sector = int(level.sides[side_index][5])
                if sector not in sectors:
                    sectors.append(sector)
        return tuple(sectors)

    def _portal_goal(self, line_index: int, desired_sector: int) -> tuple[float, float]:
        level = self.app.lvl
        line = level.lines[line_index]
        ax, ay = level.verts[line[0]]
        bx, by = level.verts[line[1]]
        midpoint = ((ax + bx) / 2.0, (ay + by) / 2.0)
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        for offset in (28.0, 20.0, 36.0, 44.0):
            candidates = (
                (midpoint[0] + nx * offset, midpoint[1] + ny * offset),
                (midpoint[0] - nx * offset, midpoint[1] - ny * offset),
            )
            for point in candidates:
                if self.app.point_secidx(point[0], point[1]) == desired_sector:
                    return point
        return midpoint

    def _point_subsector(self, x: float, y: float) -> int:
        level = self.app.lvl
        node = len(level.nodes) - 1
        while not (node & 0x8000):
            data = level.nodes[node]
            side = (x - data[0]) * data[3] - (y - data[1]) * data[2]
            node = data[-2] if side > 0 else data[-1]
        return node & 0x7FFF

    def _portal_goal_subsector(
        self, line_index: int, desired_subsector: int
    ) -> tuple[float, float]:
        level = self.app.lvl
        line = level.lines[line_index]
        ax, ay = level.verts[line[0]]
        bx, by = level.verts[line[1]]
        midpoint = ((ax + bx) / 2.0, (ay + by) / 2.0)
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        for offset in (28.0, 20.0, 36.0, 44.0, 56.0):
            for point in (
                (midpoint[0] + nx * offset, midpoint[1] + ny * offset),
                (midpoint[0] - nx * offset, midpoint[1] - ny * offset),
            ):
                if self._point_subsector(*point) == desired_subsector:
                    return point
        return midpoint

    def _subsector_center(self, subsector: int) -> tuple[float, float]:
        """Return an interior waypoint for one convex BSP subsector."""

        count, first = self.app.lvl.ssectors[subsector]
        vertices = []
        for seg_index in range(first, first + count):
            seg = self.app.lvl.segs[seg_index]
            vertices.extend(
                (self.app.lvl.verts[seg[0]], self.app.lvl.verts[seg[1]])
            )
        return (
            sum(point[0] for point in vertices) / len(vertices),
            sum(point[1] for point in vertices) / len(vertices),
        )

    def _geometry_blocked(self, ox, oy, nx, ny, radius=16) -> bool:
        """Test static/dynamic map geometry without treating actors as walls."""

        current = self.app.point_sector(ox, oy)
        if self.app.hits_wall(ox, oy, nx, ny, radius, False, current[0]):
            return True
        destination = self.app.point_sector(nx, ny)
        return (
            destination[0] - current[0] > self.engine.MAXSTEP
            or destination[1] - destination[0] < self.engine.MINHEAD
        )
