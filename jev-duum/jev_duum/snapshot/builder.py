"""``SnapshotBuilder``: one stateful pass over the engine that yields one immutable snapshot per tick.

The entity and navigation passes live in their own modules; this class keeps the stable-id registry, the deltas and the one public ``build``."""

from __future__ import annotations

import math

from ..types import DuumControls
from .entities import EntitySection
from .mesh import MeshSection
from .models import (
    DuumSnapshot,
    EpisodeSnapshot,
    PlayerSnapshot,
)
from .navigation import NavigationSection
from .routes import RouteSection


class SnapshotBuilder(EntitySection, NavigationSection, MeshSection, RouteSection):
    def __init__(self, app, engine_module):
        self.app = app
        self.engine = engine_module
        self._thing_ids = {id(thing): index for index, thing in enumerate(app.things_live)}
        self._next_thing_id = len(self._thing_ids)
        self._projectile_ids = {}
        self._next_projectile_id = 0
        self._initial_monsters = sum(thing[3] in engine_module.MONST for thing in app.things_live)
        self._initial_pickups = sum(thing[3] in engine_module.PICKUP for thing in app.things_live)
        self._previous_health = int(app.health)
        self._previous_armor = int(app.armor)
        self._damage_received = 0
        self._previous_position = (float(app.px), float(app.py))
        self._last_controls = DuumControls()
        self._stuck_ticks = 0
        self._idle_ticks = 0
        self._last_tick = 0
        self._last_damage = 0
        self._sectors = {int(app.psec_i)}
        self._nav_key = None
        self._nav_points = []
        self._nav_planned_tick = -10_000
        self._hunt_target_hint: int | None = None
        self._hunt_points = []
        self._hunt_key = None
        self._hunt_planned_tick = -10_000
        self._subsector_internal = None

    def note_controls(self, controls: DuumControls) -> None:
        self._last_controls = controls

    def note_hunt_target(self, target_id: int | None) -> None:
        """Name the monster the policy currently wants dead.

        The route to it is computed here, with the same graph as the exit
        route, so the policy only has to pick a target; navigation stays in the
        one place that already knows about doors, keys and lifts.
        """

        hint = None if target_id is None else int(target_id)
        if hint != self._hunt_target_hint:
            self._hunt_target_hint = hint
            self._hunt_points = []
            self._hunt_key = None

    def build(self, tick: int) -> DuumSnapshot:
        current_health = int(self.app.health)
        current_armor = int(self.app.armor)
        position = (float(self.app.px), float(self.app.py))
        if tick != self._last_tick:
            damage = max(0, self._previous_health - current_health) + max(
                0, self._previous_armor - current_armor
            )
            self._last_damage = damage
            self._damage_received += damage
            self._previous_health = current_health
            self._previous_armor = current_armor
            moved = math.hypot(
                position[0] - self._previous_position[0],
                position[1] - self._previous_position[1],
            )
            if self._last_controls.movement != "hold" and moved < 0.25:
                self._stuck_ticks += 1
            else:
                self._stuck_ticks = 0
            if self._last_controls.movement == "hold":
                self._idle_ticks += 1
            else:
                self._idle_ticks = 0
            self._previous_position = position
            self._sectors.add(int(self.app.psec_i))
            self._last_tick = int(tick)
        damage = self._last_damage

        enemies, omitted, live_enemies, hunt, awake = self._monsters()
        hint = self._hunt_target_hint
        hunt_target = next(
            (monster for monster in hunt if monster.id == hint), None
        ) if hint is not None else None
        if hunt_target is None:
            hunt_target = hunt[0] if hunt else None
        hunt_route = self._hunt_route(int(tick), hunt_target)
        pickups = self._pickups()
        remaining_pickups = sum(
            thing[3] in self.engine.PICKUP and thing[10] == 0 for thing in self.app.things_live
        )
        weapon = self.engine.WEAP[self.app.weapon]
        player = PlayerSnapshot(
            x=round(position[0], 6),
            y=round(position[1], 6),
            angle=round(float(self.app.pa), 6),
            health=current_health,
            armor=current_armor,
            weapon=int(self.app.weapon),
            weapon_name=weapon[0].decode(errors="replace").lower(),
            ammo=self._current_ammo(),
            weapon_ready=self.app.now >= self.app.refire_at,
            keys=int(self.app.keys),
            damage_since_last=damage,
            max_health=int(getattr(self.engine, "PLAYER_MAXHEALTH", 100) or 100),
        )
        episode = EpisodeSnapshot(
            game_time=round(float(self.app.now), 6),
            kills=self._initial_monsters - live_enemies,
            items=self._initial_pickups - remaining_pickups,
            damage_received=self._damage_received,
            live_enemies=live_enemies,
            projectiles=len(self.app.proj),
            unique_sectors=len(self._sectors),
            stuck_ticks=self._stuck_ticks,
            idle_ticks=self._idle_ticks,
            dead=bool(self.app.dead),
            finished=self.app.finish is not None,
            monsters_remaining=live_enemies,
            monsters_awake=awake,
        )
        return DuumSnapshot(
            tick=int(tick),
            map_name=str(self.app.level),
            rng=int(self.app.rng),
            player=player,
            visible_enemies=enemies,
            incoming_projectiles=self._projectiles(),
            visible_pickups=pickups,
            nearby_interactions=self._interaction(),
            movement_options=self._movement_options(),
            navigation=self._navigation(int(tick)),
            omitted_enemies=omitted,
            episode=episode,
            hidden_enemies=hunt,
            hunt_route=hunt_route,
            hunt_route_target_id=hunt_target.id if hunt_target is not None else None,
        )
