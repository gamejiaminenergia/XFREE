"""Geometry and the two routes the snapshot plans: to the objective and to the chosen hunt target.

This is the only place that knows about doors, keys, lifts and subsectors, so the policy only ever picks a destination."""

from __future__ import annotations

import heapq
import math

from .geometry import _bearing_word, _distance_word
from .models import MovementOptionSnapshot, NavigationSnapshot


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

    def _navigation(self, tick: int) -> NavigationSnapshot | None:
        level, exits, graph, connecting_line, line_subsectors = self._nav_graph()
        if not exits:
            return None
        start = self._point_subsector(self.app.px, self.app.py)
        queue = [start]
        previous = {start: None}
        selected = None
        objective = "exit"
        target_point = None
        target_line = None
        use_when_near = False
        exit_lookup = {}
        for line_index, subsectors, use_when_near in exits:
            for subsector, _ in subsectors:
                exit_lookup.setdefault(subsector, (line_index, use_when_near))
        for subsector in queue:
            if subsector in exit_lookup:
                selected = subsector
                break
            for neighbor in sorted(graph.get(subsector, ())):
                if neighbor not in previous:
                    previous[neighbor] = subsector
                    queue.append(neighbor)
        if selected is None:
            reachable_order = {subsector: index for index, subsector in enumerate(queue)}
            key_names = {1: "blue-key", 2: "red-key", 4: "yellow-key"}
            key_targets = []
            unavailable_keys = []
            for thing in self.app.things_live:
                pickup = self.engine.PICKUP.get(thing[3])
                if pickup is None or pickup[0] != 5 or thing[10] != 0:
                    continue
                key_bit = int(pickup[1])
                if self.app.keys & key_bit:
                    continue
                key_x, key_y = float(thing[0]), float(thing[1])
                key_subsector = self._point_subsector(key_x, key_y)
                key_sector = int(self.app.ss_sectors()[key_subsector])
                unavailable_keys.append(
                    (key_names.get(key_bit, "key"), int(level.sectors[key_sector][6]))
                )
                # Duum collects pickups inside a 40-unit axis-aligned box.
                # A key can therefore be reachable from beside or below a
                # platform even when its own sector cannot be entered.  Route
                # to a reachable collection point instead of inventing an
                # edge into the key's raised sector.
                for offset_x, offset_y in (
                    (0.0, 0.0),
                    (-36.0, 0.0),
                    (36.0, 0.0),
                    (0.0, -36.0),
                    (0.0, 36.0),
                    (-36.0, -36.0),
                    (-36.0, 36.0),
                    (36.0, -36.0),
                    (36.0, 36.0),
                ):
                    target = (key_x + offset_x, key_y + offset_y)
                    if self._geometry_blocked(*target, *target):
                        continue
                    key_subsector = self._point_subsector(*target)
                    if key_subsector not in reachable_order:
                        continue
                    key_targets.append(
                        (
                            reachable_order[key_subsector],
                            math.dist((float(self.app.px), float(self.app.py)), target),
                            key_subsector,
                            key_names.get(key_bit, "key"),
                            target,
                        )
                    )
            if key_targets:
                _, _, selected, objective, target_point = min(key_targets)
            else:
                switch_targets = []
                for key_name, key_tag in unavailable_keys:
                    if not key_tag:
                        continue
                    for line_index, line in enumerate(level.lines):
                        action = self.engine.ACT.get(line[3])
                        if (
                            action is None
                            or action[1] != 0
                            or action[0] not in (0, 1, 2, 3, 7)
                            or line[4] != key_tag
                        ):
                            continue
                        for switch_subsector, _ in line_subsectors.get(line_index, ()):
                            if switch_subsector not in reachable_order:
                                continue
                            approach = self._portal_goal_subsector(
                                line_index, switch_subsector
                            )
                            switch_targets.append(
                                (
                                    reachable_order[switch_subsector],
                                    math.dist(
                                        (float(self.app.px), float(self.app.py)), approach
                                    ),
                                    switch_subsector,
                                    f"{key_name}-switch",
                                    approach,
                                    line_index,
                                )
                            )
                if not switch_targets:
                    return NavigationSnapshot(
                        "exit", 0.0, "unknown", 0.0, "unknown", None, 0, False, False
                    )
                (
                    _,
                    _,
                    selected,
                    objective,
                    target_point,
                    target_line,
                ) = min(switch_targets)
                use_when_near = True
        path = []
        cursor = selected
        while cursor is not None:
            path.append(cursor)
            cursor = previous[cursor]
        path.reverse()
        exit_line = None
        if objective == "exit":
            exit_line, use_when_near = exit_lookup[selected]
        subsector_sectors = self.app.ss_sectors()
        current_subsector = path[0]
        transitions = [
            (index, connecting_line[(path[index], path[index + 1])])
            for index in range(len(path) - 1)
            if (path[index], path[index + 1]) in connecting_line
        ]
        internal_step = len(path) > 1 and (path[0], path[1]) not in connecting_line
        if internal_step:
            # A WAD can reuse one sector across a concave room.  The first
            # cross-sector portal may be behind a wall even though the BSP
            # route reaches it through adjacent subsectors of that same
            # sector.  Preserve that internal step instead of aiming through
            # the wall at the later portal (the E1M1 final-room stall).
            next_subsector = path[1]
            next_sector = int(subsector_sectors[next_subsector])
            line_index = None
            goal = self._subsector_center(next_subsector)
            count, first = level.ssectors[next_subsector]
            vertices = []
            for seg_index in range(first, first + count):
                seg = level.segs[seg_index]
                vertices.extend((level.verts[seg[0]], level.verts[seg[1]]))
            width = max(point[0] for point in vertices) - min(
                point[0] for point in vertices
            )
            height = max(point[1] for point in vertices) - min(
                point[1] for point in vertices
            )
            if min(width, height) < 32 and transitions:
                # Door sectors can be thinner than the player's diameter, so
                # their vertex-average center is not a standable destination.
                # Aim at the following portal's midpoint and let the existing
                # use interaction open the door before crossing.
                _, portal_line_index = transitions[0]
                portal = level.lines[portal_line_index]
                ax, ay = level.verts[portal[0]]
                bx, by = level.verts[portal[1]]
                goal = ((ax + bx) / 2.0, (ay + by) / 2.0)
        elif transitions:
            transition_index, line_index = transitions[0]
            next_subsector = path[transition_index + 1]
            next_sector = int(subsector_sectors[next_subsector])
            desired_subsector = next_subsector
            # A Doom doorway can contain a sector only one player-diameter
            # deep.  Its center is not a valid waypoint while the following
            # door is closed.  Look through that vestibule and approach the
            # actionable line from the current sector so `use` can open it.
            if len(transitions) > 1:
                lookahead_index, lookahead = transitions[1]
                lookahead_line = level.lines[lookahead]
                lookahead_action = self.engine.ACT.get(lookahead_line[3])
                needs_use = self.engine.DOOR_USE.get(lookahead_line[3]) is not None or (
                    lookahead_action is not None and lookahead_action[1] == 0
                )
                before_door = path[lookahead_index]
                after_door = path[lookahead_index + 1]
                approach = self._portal_goal_subsector(lookahead, before_door)
                beyond = self._portal_goal_subsector(lookahead, after_door)
                still_closed = self._geometry_blocked(*approach, *beyond)
                if (
                    needs_use
                    and still_closed
                    and self._point_subsector(*approach) == before_door
                ):
                    line_index = lookahead
                    desired_subsector = before_door
        else:
            next_sector = None
            if target_point is not None:
                line_index = target_line
                goal = target_point
            else:
                line_index = exit_line
                goal = self._portal_goal_subsector(line_index, current_subsector)
        if transitions and not internal_step:
            goal = self._portal_goal_subsector(line_index, desired_subsector)
        key = (objective, current_subsector, next_sector, line_index, goal)
        if key != self._nav_key or tick - self._nav_planned_tick >= 90:
            self._nav_points = self._grid_route(goal)
            self._nav_key = key
            self._nav_planned_tick = tick
        while self._nav_points and math.dist(
            (self.app.px, self.app.py), self._nav_points[0]
        ) < 18:
            self._nav_points.pop(0)
        waypoint_x, waypoint_y = self._nav_points[0] if self._nav_points else goal
        distance, bearing = self._relative(waypoint_x, waypoint_y)
        return NavigationSnapshot(
            objective=objective,
            bearing=round(bearing, 6),
            bearing_word=_bearing_word(bearing),
            distance=round(distance, 3),
            distance_word=_distance_word(distance),
            next_sector=next_sector,
            route_length=len(transitions),
            reachable=True,
            use_when_near=use_when_near and not transitions,
        )

    def _hunt_route(self, tick: int, target) -> NavigationSnapshot | None:
        """The way to one monster: same graph as the exit route, own cache.

        Chasing a raw bearing walks into walls and oscillates in corners.  This
        returns the first waypoint of the actual subsector path -- through
        doors and lifts when needed -- so ``guide_bearing`` always points at
        somewhere the player can stand.
        """

        if target is None:
            return None
        level, exits, graph, connecting_line, _ = self._nav_graph()
        start = self._point_subsector(self.app.px, self.app.py)
        previous = {start: None}
        queue = [start]
        for subsector in queue:
            for neighbor in sorted(graph.get(subsector, ())):
                if neighbor not in previous:
                    previous[neighbor] = subsector
                    queue.append(neighbor)
        goal = (float(target.x), float(target.y))
        goal_subsector = self._point_subsector(goal[0], goal[1])
        reachable = goal_subsector in previous and bool(previous)
        if reachable:
            selected = goal_subsector
        else:
            selected = min(
                previous,
                key=lambda subsector: math.dist(self._subsector_center(subsector), goal),
            )
        path = []
        cursor = selected
        while cursor is not None:
            path.append(cursor)
            cursor = previous[cursor]
        path.reverse()
        straight = not self._geometry_blocked(
            float(self.app.px), float(self.app.py), goal[0], goal[1]
        )
        if straight:
            waypoint = goal
        elif len(path) >= 2:
            line_index = connecting_line.get((path[0], path[1]))
            if line_index is None:
                waypoint = self._subsector_center(path[1])
            else:
                waypoint = self._portal_goal_subsector(line_index, path[1])
        else:
            waypoint = goal
        key = (self._hunt_target_hint, round(waypoint[0], 1), round(waypoint[1], 1))
        if key != self._hunt_key or tick - self._hunt_planned_tick >= 90:
            self._hunt_points = self._grid_route(waypoint)
            self._hunt_key = key
            self._hunt_planned_tick = tick
        while self._hunt_points and math.dist(
            (float(self.app.px), float(self.app.py)), self._hunt_points[0]
        ) < 18:
            self._hunt_points.pop(0)
        point = self._hunt_points[0] if self._hunt_points else waypoint
        distance, bearing = self._relative(point[0], point[1])
        return NavigationSnapshot(
            objective=f"monster-{target.id}",
            bearing=round(bearing, 6),
            bearing_word=_bearing_word(bearing),
            distance=round(distance, 3),
            distance_word=_distance_word(distance),
            next_sector=None,
            route_length=max(0, len(path) - 1),
            reachable=reachable,
            use_when_near=False,
        )
