"""Entity extraction: stable ids, the visible/hunt monster views, the projectiles, the pickups and the one usable interaction."""

from __future__ import annotations

import math

from .. import adversary
from .geometry import _angle, _bearing_word, _distance_word
from .models import (
    MAX_HUNT_TARGETS,
    EnemySnapshot,
    InteractionSnapshot,
    MonsterSnapshot,
    PickupSnapshot,
    ProjectileSnapshot,
)


class EntitySection:
    def _thing_id(self, thing) -> int:
        key = id(thing)
        if key not in self._thing_ids:
            self._thing_ids[key] = self._next_thing_id
            self._next_thing_id += 1
        return self._thing_ids[key]

    def _projectile_id(self, projectile) -> int:
        key = id(projectile)
        if key not in self._projectile_ids:
            self._projectile_ids[key] = self._next_projectile_id
            self._next_projectile_id += 1
        return self._projectile_ids[key]

    def _relative(self, x: float, y: float) -> tuple[float, float]:
        dx = x - self.app.px
        dy = y - self.app.py
        return math.hypot(dx, dy), _angle(math.atan2(dy, dx) - self.app.pa)

    def _enemy_category(self, thing) -> str:
        return adversary.monster_category(self.engine, thing[3])

    def _monsters(self):
        """One pass over every live monster: visible top-3 plus the hunt catalogue.

        Both views share the same sight check and the same stable ids, so the
        prompt can name a hunt target that is also visible as a threat, and the
        engine is only raycast once per monster per tick.
        """

        visible = []
        catalogue = []
        live = 0
        awake = 0
        weapon = int(self.app.weapon)
        for thing in self.app.things_live:
            if thing[3] not in self.engine.MONST or thing[9] <= 0 or thing[10] >= 4:
                continue
            live += 1
            distance, bearing = self._relative(thing[0], thing[1])
            line_of_sight = distance <= 1400 and self.app.sight_clear(
                self.app.px, self.app.py, thing[0], thing[1]
            )
            state = int(thing[10])
            active = state != 0
            attacking = state == 2
            if active:
                awake += 1
            profile = adversary.monster_profile(self.engine, thing[3])
            thing_id = self._thing_id(thing)
            if profile is not None:
                direct_path = not self._geometry_blocked(
                    float(self.app.px),
                    float(self.app.py),
                    float(thing[0]),
                    float(thing[1]),
                    radius=0,
                )
                catalogue.append(
                    MonsterSnapshot(
                        id=thing_id,
                        kind=int(thing[3]),
                        category=profile.category,
                        x=round(float(thing[0]), 3),
                        y=round(float(thing[1]), 3),
                        bearing=round(bearing, 6),
                        bearing_word=_bearing_word(bearing),
                        distance=round(distance, 3),
                        distance_word=_distance_word(distance),
                        hp=int(thing[9]),
                        hp_fraction=round(min(1.0, max(0.0, thing[9] / profile.hp)), 3),
                        awake=active,
                        attacking=attacking,
                        has_los=bool(line_of_sight),
                        direct_path=direct_path,
                        aligned=abs(bearing)
                        <= max(0.025, math.atan2(float(thing[12]) + 6.0, max(distance, 1.0))),
                        shots_to_kill=adversary.shots_to_kill(self.engine, thing[3], weapon),
                        kill_seconds=adversary.kill_seconds(self.engine, thing[3], weapon),
                        arrival_seconds=adversary.arrival_seconds(distance),
                        kills_per_second=adversary.kills_per_second(
                            self.engine,
                            thing[3],
                            weapon,
                            distance,
                            awake=active,
                            has_los=bool(line_of_sight),
                            direct_path=direct_path,
                        ),
                    )
                )
            if not line_of_sight:
                continue
            melee_reachable = not self._geometry_blocked(
                float(self.app.px),
                float(self.app.py),
                float(thing[0]),
                float(thing[1]),
                radius=0,
            )
            speed = self.engine.MONST[thing[3]][1] if state == 1 else 0.0
            vx = math.cos(thing[2]) * speed
            vy = math.sin(thing[2]) * speed
            radial = 0.0
            if distance:
                radial = ((thing[0] - self.app.px) * vx + (thing[1] - self.app.py) * vy) / distance
            motion = "closing" if radial < -10 else "receding" if radial > 10 else "steady"
            threat = (
                (500 if attacking else 0)
                + (180 if active else 0)
                + max(0.0, 700 - distance)
                + (100 if abs(bearing) < math.pi / 3 else 0)
            )
            visible.append(
                EnemySnapshot(
                    id=thing_id,
                    category=self._enemy_category(thing),
                    bearing=round(bearing, 6),
                    bearing_word=_bearing_word(bearing),
                    distance=round(distance, 3),
                    distance_word=_distance_word(distance),
                    visible=True,
                    attacking=attacking,
                    active=active,
                    melee_reachable=melee_reachable,
                    aligned=abs(bearing)
                    <= max(0.025, math.atan2(float(thing[12]) + 6.0, max(distance, 1.0))),
                    motion=motion,
                    threat=round(threat, 3),
                )
            )
        visible.sort(key=lambda enemy: (-enemy.threat, enemy.id))
        kept = tuple(visible[:3])
        catalogue.sort(
            key=lambda monster: (
                -monster.kills_per_second,
                not monster.awake,
                monster.distance,
                monster.id,
            )
        )
        return (
            kept,
            max(0, len(visible) - len(kept)),
            live,
            tuple(catalogue[:MAX_HUNT_TARGETS]),
            awake,
        )

    def _projectiles(self) -> tuple[ProjectileSnapshot, ...]:
        result = []
        for projectile in self.app.proj:
            if projectile[7] != 1:
                continue
            rx = projectile[0] - self.app.px
            ry = projectile[1] - self.app.py
            vx, vy = projectile[3], projectile[4]
            speed2 = vx * vx + vy * vy
            closest_time = max(0.0, min(2.0, -(rx * vx + ry * vy) / speed2)) if speed2 else 2.0
            cx = rx + vx * closest_time
            cy = ry + vy * closest_time
            closest = math.hypot(cx, cy)
            distance, bearing = self._relative(projectile[0], projectile[1])
            impact = closest <= 24 and closest_time <= 1.5
            dodge = "strafe_left" if bearing <= 0 else "strafe_right"
            threat = (1000 if impact else 0) + max(0.0, 2.0 - closest_time) * 100 - closest
            result.append(
                ProjectileSnapshot(
                    id=self._projectile_id(projectile),
                    bearing=round(bearing, 6),
                    bearing_word=_bearing_word(bearing),
                    distance=round(distance, 3),
                    distance_word=_distance_word(distance),
                    impact_time=round(closest_time, 3),
                    impact=impact,
                    dodge=dodge,
                    threat=round(threat, 3),
                )
            )
        result.sort(key=lambda projectile: (-projectile.threat, projectile.id))
        return tuple(result[:2])

    def _pickups(self) -> tuple[PickupSnapshot, ...]:
        result = []
        categories = ("health", "armor", "armor", "ammo", "weapon", "key", "ammo", "powerup")
        for thing in self.app.things_live:
            definition = self.engine.PICKUP.get(thing[3])
            if definition is None or thing[10] != 0:
                continue
            distance, bearing = self._relative(thing[0], thing[1])
            if distance > 650 or not self.app.sight_clear(
                self.app.px, self.app.py, thing[0], thing[1]
            ):
                continue
            if self._geometry_blocked(
                float(self.app.px),
                float(self.app.py),
                float(thing[0]),
                float(thing[1]),
                radius=0,
            ):
                continue
            category = categories[definition[0]]
            need = "useful"
            if category == "health":
                need = "critical" if self.app.health < 25 else "urgent"
                if self.app.health >= 45:
                    need = "useful"
            elif category == "ammo":
                need = self._ammo_need(int(definition[1]))
            elif category == "weapon" and not self._has_usable_ranged_weapon():
                need = "critical"
            result.append(
                PickupSnapshot(
                    id=self._thing_id(thing),
                    category=category,
                    bearing=round(bearing, 6),
                    bearing_word=_bearing_word(bearing),
                    distance=round(distance, 3),
                    distance_word=_distance_word(distance),
                    need=need,
                )
            )
        priority = {"critical": 0, "urgent": 1, "useful": 2}
        result.sort(key=lambda pickup: (priority[pickup.need], pickup.distance, pickup.id))
        return tuple(result[:1])

    def _interaction(self) -> tuple[InteractionSnapshot, ...]:
        ux, uy = math.cos(self.app.pa), math.sin(self.app.pa)
        best = None
        best_distance = 65.0
        level = self.app.lvl
        for index, line in enumerate(level.lines):
            special = line[3]
            if special == 0:
                continue
            x1, y1 = level.verts[line[0]]
            x2, y2 = level.verts[line[1]]
            ex, ey = x2 - x1, y2 - y1
            denominator = ux * ey - uy * ex
            if denominator == 0:
                continue
            distance = ((x1 - self.app.px) * ey - (y1 - self.app.py) * ex) / denominator
            if distance <= 0 or distance >= best_distance:
                continue
            along = (
                (self.app.px + distance * ux - x1) / ex
                if abs(ex) >= abs(ey) and ex
                else (self.app.py + distance * uy - y1) / ey
                if ey
                else -1
            )
            if 0 <= along <= 1:
                best = (index, special, line)
                best_distance = distance
        if best is None:
            return ()
        _, special, line = best
        door = self.engine.DOOR_USE.get(special)
        if door is not None and line[6] != 0xFFFF:
            front = level.sectors[level.sides[line[5]][5]]
            back = level.sectors[level.sides[line[6]][5]]
            opening = min(front[1], back[1]) - max(front[0], back[0])
            if opening >= self.engine.MINHEAD:
                return ()
            required = door[0]
            key_name = {1: "blue", 2: "red", 4: "yellow"}.get(required)
            return (
                InteractionSnapshot(
                    "door",
                    round(best_distance, 3),
                    bool(required and not (self.app.keys & required)),
                    key_name,
                ),
            )
        action = self.engine.ACT.get(special)
        if action is not None and (not action[1] or action[0] in (4, 5)):
            return (InteractionSnapshot("switch", round(best_distance, 3), False, None),)
        return ()

    def _current_ammo(self) -> int:
        ammo_kind = self.engine.WEAP[self.app.weapon][4]
        return int(self.app.ammo[ammo_kind]) if ammo_kind else 999

    def _has_usable_ranged_weapon(self) -> bool:
        for slot in self.app.owned:
            weapon = self.engine.WEAP[slot]
            ammo_kind, per_shot = int(weapon[4]), int(weapon[5])
            if ammo_kind and self.app.ammo[ammo_kind] >= per_shot:
                return True
        return False

    def _ammo_need(self, ammo_kind: int) -> str:
        compatible = [
            slot
            for slot in self.app.owned
            if int(self.engine.WEAP[slot][4]) == ammo_kind
        ]
        if not compatible:
            return "useful"
        remaining = int(self.app.ammo[ammo_kind])
        current_kind = int(self.engine.WEAP[self.app.weapon][4])
        if (current_kind == ammo_kind and remaining <= 1) or (
            not self._has_usable_ranged_weapon() and remaining == 0
        ):
            return "critical"
        per_shot = min(int(self.engine.WEAP[slot][5]) for slot in compatible)
        return "urgent" if remaining < max(5 * per_shot, 5) else "useful"
