"""The walkable mesh: subsector connectivity, the grid route and the nav graph."""

from __future__ import annotations

import heapq
import math


class MeshSection:
    def _subsector_internal_edges(self):
        """Connect BSP subsectors that share traversable space in one sector."""

        if self._subsector_internal is not None:
            return self._subsector_internal
        level = self.app.lvl
        edges = {index: set() for index in range(len(level.ssectors))}
        sectors = self.app.ss_sectors()
        bounds = []
        by_sector = {}
        for subsector, (count, first) in enumerate(level.ssectors):
            vertices = []
            for seg_index in range(first, first + count):
                seg = level.segs[seg_index]
                vertices.extend((level.verts[seg[0]], level.verts[seg[1]]))
            sx = [point[0] for point in vertices]
            sy = [point[1] for point in vertices]
            bounds.append((min(sx), min(sy), max(sx), max(sy)))
            by_sector.setdefault(sectors[subsector], []).append(subsector)
        for subsectors in by_sector.values():
            for offset, first in enumerate(subsectors):
                ax0, ay0, ax1, ay1 = bounds[first]
                for second in subsectors[offset + 1 :]:
                    bx0, by0, bx1, by1 = bounds[second]
                    x_gap = max(0, ax0 - bx1, bx0 - ax1)
                    y_gap = max(0, ay0 - by1, by0 - ay1)
                    if x_gap <= 1 and y_gap <= 1:
                        edges[first].add(second)
                        edges[second].add(first)
        step = 16.0
        xs = [vertex[0] for vertex in level.verts]
        ys = [vertex[1] for vertex in level.verts]
        points = {}
        ix = 0
        x = min(xs) + step / 2
        while x <= max(xs) - step / 2:
            iy = 0
            y = min(ys) + step / 2
            while y <= max(ys) - step / 2:
                if not self._geometry_blocked(x, y, x, y):
                    points[(ix, iy)] = (x, y, self._point_subsector(x, y))
                iy += 1
                y += step
            ix += 1
            x += step
        for (ix, iy), (x, y, subsector) in points.items():
            for neighbor_key in ((ix + 1, iy), (ix, iy + 1), (ix + 1, iy + 1)):
                neighbor = points.get(neighbor_key)
                if neighbor is None:
                    continue
                nx, ny, next_subsector = neighbor
                if (
                    subsector != next_subsector
                    and sectors[subsector] == sectors[next_subsector]
                    and not self._geometry_blocked(x, y, nx, ny)
                ):
                    edges[subsector].add(next_subsector)
                    edges[next_subsector].add(subsector)
        self._subsector_internal = edges
        return edges

    def _grid_route(self, goal: tuple[float, float]):
        start = (float(self.app.px), float(self.app.py))
        if not self._geometry_blocked(start[0], start[1], goal[0], goal[1]):
            return [goal]
        step = 32.0
        level = self.app.lvl
        xs = [vertex[0] for vertex in level.verts]
        ys = [vertex[1] for vertex in level.verts]
        min_x, max_x = min(xs) - step, max(xs) + step
        min_y, max_y = min(ys) - step, max(ys) + step

        def point(node):
            return level.gx0 + node[0] * step, level.gy0 + node[1] * step

        def node_for(x, y):
            return round((x - level.gx0) / step), round((y - level.gy0) / step)

        center = node_for(*start)
        open_heap = []
        costs = {}
        previous = {}
        serial = 0
        for ix in range(center[0] - 2, center[0] + 3):
            for iy in range(center[1] - 2, center[1] + 3):
                node = (ix, iy)
                candidate = point(node)
                if self._geometry_blocked(*start, *candidate):
                    continue
                cost = math.dist(start, candidate)
                costs[node] = cost
                previous[node] = None
                serial += 1
                heapq.heappush(
                    open_heap, (cost + math.dist(candidate, goal), cost, serial, node)
                )
        found = None
        directions = (
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
        )
        visited = 0
        while open_heap and visited < 20_000:
            _, cost, _, node = heapq.heappop(open_heap)
            if cost != costs.get(node):
                continue
            visited += 1
            here = point(node)
            if math.dist(here, goal) <= step * 1.5 and not self._geometry_blocked(
                *here, *goal
            ):
                found = node
                break
            for ox, oy in directions:
                neighbor = (node[0] + ox, node[1] + oy)
                there = point(neighbor)
                if not (min_x <= there[0] <= max_x and min_y <= there[1] <= max_y):
                    continue
                if self._geometry_blocked(*here, *there):
                    continue
                next_cost = cost + math.dist(here, there)
                if next_cost >= costs.get(neighbor, math.inf):
                    continue
                costs[neighbor] = next_cost
                previous[neighbor] = node
                serial += 1
                heapq.heappush(
                    open_heap,
                    (next_cost + math.dist(there, goal), next_cost, serial, neighbor),
                )
        if found is None:
            return [goal]
        route = [goal]
        cursor = found
        while cursor is not None:
            route.append(point(cursor))
            cursor = previous[cursor]
        route.reverse()
        # Remove grid zig-zags whenever exact Duum collision geometry permits
        # a longer direct segment.
        smoothed = []
        origin = start
        index = 0
        while index < len(route):
            farthest = index
            for candidate_index in range(len(route) - 1, index - 1, -1):
                candidate = route[candidate_index]
                if not self._geometry_blocked(*origin, *candidate):
                    farthest = candidate_index
                    break
            smoothed.append(route[farthest])
            origin = route[farthest]
            index = farthest + 1
        return smoothed

    def _nav_graph(self):
        """The subsector traversal graph: portals, doors, keys and exits.

        ``_navigation`` and ``_hunt_route`` share it so the way to the exit and
        the way to a monster can never disagree about what is passable.
        """

        level = self.app.lvl
        exits = []
        graph = {
            index: list(neighbors)
            for index, neighbors in self._subsector_internal_edges().items()
        }
        connecting_line = {}
        line_subsectors = {}
        for subsector, (count, first) in enumerate(level.ssectors):
            for seg_index in range(first, first + count):
                seg = level.segs[seg_index]
                line_index = int(seg[3])
                if line_index != 0xFFFF:
                    line_subsectors.setdefault(line_index, []).append(
                        (subsector, int(seg[4]))
                    )
        for line_index, line in enumerate(level.lines):
            sectors = self._line_sectors(level, line)
            subsectors = line_subsectors.get(line_index, ())
            action = self.engine.ACT.get(line[3])
            if action is not None and action[0] in (4, 5):
                exits.append((line_index, subsectors, action[1] == 0))
            if len(sectors) != 2 or line[2] & self.engine.ML_BLOCKING:
                continue
            door = self.engine.DOOR_USE.get(line[3])
            if door is not None and door[0] and not (self.app.keys & door[0]):
                continue
            left, right = sectors
            left_sector = level.sectors[left]
            right_sector = level.sectors[right]
            opening = min(left_sector[1], right_sector[1]) - max(
                left_sector[0], right_sector[0]
            )
            tagged_action = self.engine.ACT.get(line[3])
            tagged_sectors = level.tagsec.get(line[4], ())
            can_change_geometry = door is not None or (
                tagged_action is not None and tagged_action[0] in (0, 1, 2, 3, 7)
                and any(sector in tagged_sectors for sector in sectors)
            )
            if not can_change_geometry and (
                abs(left_sector[0] - right_sector[0]) > self.engine.MAXSTEP
                or opening < self.engine.MINHEAD
            ):
                continue
            for first_node, first_side in subsectors:
                for second_node, second_side in subsectors:
                    if first_node == second_node or first_side == second_side:
                        continue
                    if second_node not in graph[first_node]:
                        graph[first_node].append(second_node)
                    connecting_line.setdefault((first_node, second_node), line_index)
        return level, exits, graph, connecting_line, line_subsectors
