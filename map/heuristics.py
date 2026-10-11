#!/usr/bin/env python3
"""
heuristics.py — Eurística del juego: los cálculos que el protagonista NO
puede hacer (ni conocer) por sí solo.

Entendiendo "eurística" como lo que el agente no sabe / no puede calcular
en pleno juego, este script se lo resuelve y lo arroja como un .json:

 1. FOES FUERA DE VISTA      → amenaza real de cada enemigo: daño esperado,
                               tiempo aprox. de muerte del jugador, si está
                               en línea de vista (el agente no lo sabe).
 2. RIESGO POR SECTOR        → mapa de riesgo a 360° (16 sectores); suma de
                               amenazas ponderadas por distancia.
 3. PELIGRO BAJO LOS PIES    → nukage/agua/teleporter en la celda actual y
                               en las adyacentes (el agente lo ignora hasta
                               toxicarse).
 4. ASPIRACIÓN / GRADIENTES  → qué es lo más valioso cerca según contexto:
                               salud baja → medikits pesan más; salud alta
                               → salida pesa más.
 5. INFORMACIÓN OCULTA       → items/foes/secrets no visibles desde la
                               posición (los que el agente NO conoce).
 6. RUTA A LA SALIDA         → BFS sobre la rejilla (puertas y salida
                               cuentan como pasables), con el primer paso
                               concreto a dar.
"""

from __future__ import annotations

import json
import math
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sense import (
    CELL, COLS, ROWS, GRID,
    ROOMS, DOORS, EXITS, ITEMS, FOES, NUKAGE_POOLS, WATER_POOL, TELEPORTER,
    room_at, cell_at, inside_nukage, inside_water,
    on_teleporter, on_stairs, nearest_room,
)

# ─────────────────────────────────────────────────────────────────────────────
#  Parámetros de simulación (Balance del DOOM clásico, aproximado)
# ─────────────────────────────────────────────────────────────────────────────

PLAYER_HEALTH = 100          # hp del protagonista por defecto
PLAYER_ARMOR = 0             # armadura actual
NUKAGE_DPS = 8               # daño por punto de vida que saca el nukage/tick
FOE_DAMAGE_PER_HIT = 14      # daño medio de un imp/grunt por disparo
FOE_RANGE_LIMIT = 260.0      # más allá de esto un foe no amenaza
SIGHT_LIMIT = 300.0          # alcance máximo de visión
SECTORS = 16                 # sectores de riesgo a 360°
HEALTH_LOW = 35              # umbral de salud "baja" para aspiraciones

WEAPON_PRIORITY = {
    "berserk": 1.0, "rocket": 0.9, "shotgun": 0.75, "chaingun": 0.7,
}

ROOM_SECRET = {r.name: r.secrets for r in ROOMS}


def _dist(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x2 - x1, y2 - y1)


def has_line_of_sight(x1: float, y1: float, x2: float, y2: float,
                      step: float = 6.0) -> bool:
    """Marcha por segmentos entre dos puntos; si cruza un muro, no hay LOS.
    Puertas y exit cuentan como pasables visualmente (agente los ve)."""
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    steps = max(1, int(dist / step))
    for i in range(1, steps):
        t = i / steps
        x, y = x1 + dx * t, y1 + dy * t
        if cell_at(x, y) == "wall":
            return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
#  1. Amenazas: foes con daño esperado — el agente no conoce esto
# ─────────────────────────────────────────────────────────────────────────────


def analyze_foes(px: float, py: float) -> Dict:
    visible_count = 0
    threats: List[Dict] = []
    for foe in FOES:
        d = _dist(px, py, foe["x"], foe["y"])
        in_range = d <= FOE_RANGE_LIMIT
        los = False
        if in_range:
            los = has_line_of_sight(px, py, foe["x"], foe["y"])

        # daño esperado: proporcional a proximidad y a si me ve
        if los and in_range:
            visibility = max(0.0, 1.0 - d / FOE_RANGE_LIMIT)
            expected_dmg = round(FOE_DAMAGE_PER_HIT * visibility, 1)
            ttg = (PLAYER_HEALTH / FOE_DAMAGE_PER_HIT) if expected_dmg > 0 else None
            threat = round(expected_dmg / 30.0, 3)  # normalizado ~0..1
            visible_count += 1
        else:
            expected_dmg = 0.0
            ttg = None
            threat = 0.0

        if foe["size"] >= 10:  # Barón: el más duro, el agente lo nota igual
            threat = round(max(threat, 0.9), 3)
            expected_dmg = max(expected_dmg, FOE_DAMAGE_PER_HIT * 2)

        threats.append({
            "position_px": [foe["x"], foe["y"]],
            "distance_px": round(d, 1),
            "line_of_sight": los,
            "in_range": in_range,
            "expected_damage_per_hit": expected_dmg,
            "time_to_die_ticks": ttg,
            "threat_score": threat,
        })
    return {
        "foes_total": len(FOES),
        "foes_in_sight": visible_count,
        "foes_hidden": len(FOES) - visible_count,   # agente NO los ve
        "threats": threats,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  2. Riesgo sectorial: mapa de riesgo 360° en 16 sectores
# ─────────────────────────────────────────────────────────────────────────────


def sector_risk(px: float, py: float) -> Dict:
    sectors = [0.0] * SECTORS
    for foe_data in analyze_foes(px, py)["threats"]:
        active = foe_data["threat_score"] > 0.0
        if not active:
            continue
        # riesgo desde el punto del foe hacia el AGENTE
        f = foe_data["position_px"]
        ang = math.atan2(py - f[1], px - f[0])
        idx = int((ang % (2 * math.pi)) / (2 * math.pi) * SECTORS) % SECTORS
        d = foe_data["distance_px"]
        # peso: cubo de la distancia (cercanía pesa mucho), cap 0..1
        weight = max(0.0, 1.0 - d / FOE_RANGE_LIMIT) ** 3
        s = foe_data["threat_score"] * weight
        sectors[idx] += s
        sectors[(idx - 1) % SECTORS] += s * 0.5
        sectors[(idx + 1) % SECTORS] += s * 0.5
    # Nukage vecino también genera riesgo (aunque el agente no lo vea aún)
    for pool in NUKAGE_POOLS:
        d = _dist(px, py, pool["cx"], pool["cy"])
        if d < max(pool["rx"], pool["ry"]) + CELL * 2:
            ang = math.atan2(pool["cy"] - py, pool["cx"] - px)
            idx = int((ang % (2 * math.pi)) / (2 * math.pi) * SECTORS) % SECTORS
            sectors[idx] += 0.4

    # sector más peligroso y sector más seguro
    max_idx = max(range(SECTORS), key=lambda i: sectors[i])
    min_idx = max(range(SECTORS), key=lambda i: -sectors[i])
    return {
        "sector_values": [round(v, 3) for v in sectors],
        "worst_sector": max_idx,
        "worst_risk": round(sectors[max_idx], 3),
        "safest_sector": min_idx,
        "safest_risk": round(sectors[min_idx], 3),
        "recommended_heading_deg": round(
            (min_idx * 360.0 / SECTORS), 1
        ),
        "avoid_heading_deg": round((max_idx * 360.0 / SECTORS), 1),
        "overall_risk": round(sum(sectors) / SECTORS, 3),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  3. Peligro inmediato bajo los pies / adyacentes
# ─────────────────────────────────────────────────────────────────────────────


def terrain_danger(px: float, py: float) -> Dict:
    neighbor = []
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nx, ny = px + dx * CELL, py + dy * CELL
        if inside_nukage(nx, ny) or inside_water(nx, ny) or cell_at(nx, ny) == "wall":
            neighbor.append({
                "offset_cells": [dx, dy],
                "kind": "nukage" if inside_nukage(nx, ny)
                else "water" if inside_water(nx, ny) else "wall",
            })
    return {
        "standing_on": "nukage" if inside_nukage(px, py) else
                       "water" if inside_water(px, py) else
                       "teleporter" if on_teleporter(px, py) else "floor",
        "nukage_damage_per_tick": NUKAGE_DPS if inside_nukage(px, py) else 0,
        "adjacent_cells": neighbor,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  4. Aspiración / gradientes de valor — qué es lo máximo cerca según contexto
# ─────────────────────────────────────────────────────────────────────────────


def aspirations(px: float, py: float, health: int = PLAYER_HEALTH) -> Dict:
    def score_item(kind: str, d: float) -> float:
        base = {
            "medikit": 0.85, "stimpack": 0.45, "soul_sphere": 1.0,
            "megasphere": 1.0, "green_armor": 0.6, "blue_armor": 0.75,
            "ammo_box": 0.4, "berserk": 0.9, "barrels": 0.15,
            "invisibility": 0.5,
        }.get(kind, 0.5)
        # armas más valiosas si no las tengo (aprox: nadie las tiene al inicio)
        base = max(base, WEAPON_PRIORITY.get(kind, 0.3))
        # salud LOW triplica medikits y soul sphere
        if kind in ("medikit", "soul_sphere", "megasphere", "stimpack"):
            if health <= HEALTH_LOW:
                base *= 2.0
        return base

    candidates: List[Dict] = []
    for it in ITEMS:
        d = _dist(px, py, it["x"], it["y"])
        if d < CELL or d > 400:
            continue
        candidates.append({
            "kind": it["kind"],
            "position_px": [it["x"], it["y"]],
            "distance_px": round(d, 1),
            "aspiration_score": round(score_item(it["kind"], d) / (1.0 + d / 200), 3),
        })
    candidates.sort(key=lambda c: -c["aspiration_score"])

    # aspiración de salida
    exit_d = min(_dist(px, py, e["x"], e["y"]) for e in EXITS)
    exit_score = (1.0 / (1.0 + exit_d / 300))

    return {
        "health_context": "low" if health <= HEALTH_LOW else "ok",
        "top_aspirations": candidates[:6],
        "exit_distance_px": round(exit_d, 1),
        "exit_aspiration": round(exit_score, 3),
        "recommended_target": (
            {"kind": candidates[0]["kind"], "position_px": candidates[0]["position_px"]}
            if candidates and candidates[0]["aspiration_score"] > exit_score
            else {"kind": "EXIT", "position_px": [EXITS[0]["x"], EXITS[0]["y"]]}
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  5. Información oculta: lo que el protagonista NO ve desde aquí
# ─────────────────────────────────────────────────────────────────────────────


def hidden_information(px: float, py: float) -> Dict:
    def visible(x: float, y: float) -> bool:
        d = _dist(px, py, x, y)
        if d > SIGHT_LIMIT:
            return False
        return has_line_of_sight(px, py, x, y)

    hidden_items = [
        {"kind": i["kind"], "position_px": [i["x"], i["y"]]}
        for i in ITEMS if not visible(i["x"], i["y"])
    ]
    visible_items = [
        {"kind": i["kind"], "distance_px": round(_dist(px, py, i["x"], i["y"]), 1)}
        for i in ITEMS if visible(i["x"], i["y"])
    ]
    room = room_at(px, py)
    # secrets del mapa: el agente no los conoce, cuenta por sala
    secrets_map = {r.name: r.secrets for r in ROOMS}
    secrets_map.update({"ARENA": 1, "SECRET": 1})  # reglas del nivel
    details = {
        "item": hidden_items,
        "secrets_count": sum(secrets_map.values()),
        "secrets_by_room": secrets_map,
        "items_visible": visible_items,
        "items_hidden_count": len(hidden_items),
    }
    return details


# ─────────────────────────────────────────────────────────────────────────────
#  6. Ruta a la salida.
#  Capa 1 (robusta): grafo de salas — conocimiento estructural del nivel que
#  ningún agente podría derivar de lo que ve. Capa 2 (best-effort): BFS por
#  celdas, solo si la rasterización de la rejilla da conectividad limpia.
# ─────────────────────────────────────────────────────────────────────────────

# Adyacencias reales del nivel (derivadas de las puertas del SVG)
ROOM_EDGES: Tuple[Tuple[str, str, str], ...] = (
    ("START", "NUKAGE YARD", "START->zigzag"),
    ("NUKAGE YARD", "COMPUTER ROOM", "patio->COMPUTER ROOM"),
    ("NUKAGE YARD", "ARENA", "ARENA->patio"),
    ("COMPUTER ROOM", "ARENA", "zigzag->ARENA"),
    ("COMPUTER ROOM", "SECRET", "COMPUTER ROOM->pasillo"),
    ("TELEPORT", "ARENA", "stairs"),
    ("ARENA", "EXIT", "pasillo sur"),
    ("SECRET", "EXIT", "pasillo este"),
)


def _compass(dx: float, dy: float) -> str:
    if abs(dx) >= abs(dy):
        return "east" if dx > 0 else "west"
    return "south" if dy > 0 else "north"


def _room_centroid(name: str) -> Tuple[float, float]:
    room = next(r for r in ROOMS if r.name == name)
    return room.center


def room_route(px: float, py: float, current_room: Optional[str]) -> Dict:
    """Camino más corto por salas desde la sala actual hasta EXIT (BFS
    sobre ROOM_EDGES). Siempre resuelve: es conocimiento del mapa."""
    if current_room is None:
        near, _ = nearest_room(px, py)
        current_room = near.name
    if current_room == "EXIT":
        return {"rooms": [], "doors": [], "steps_remaining": 0,
                "status": "already_at_exit"}
    adjacency: Dict[str, List[Tuple[str, str]]] = {}
    for a, b, door in ROOM_EDGES:
        adjacency.setdefault(a, []).append((b, door))
        adjacency.setdefault(b, []).append((a, door))
    prev: Dict[str, Optional[str]] = {current_room: None}
    prev_door: Dict[str, str] = {}
    queue = deque([current_room])
    while queue:
        cur = queue.popleft()
        if cur == "EXIT":
            break
        for nxt, door in adjacency.get(cur, []):
            if nxt not in prev:
                prev[nxt] = cur
                prev_door[nxt] = door
                queue.append(nxt)
    if "EXIT" not in prev:
        return {"rooms": [], "doors": [], "steps_remaining": 0,
                "status": "exit_not_on_room_graph"}
    rooms, doors = [], []
    node = "EXIT"
    while node is not None:
        rooms.append(node)
        if node in prev_door:
            doors.append(prev_door[node])
        node = prev[node]
    rooms.reverse()
    doors.reverse()
    cx, cy = _room_centroid(rooms[1]) if len(rooms) > 1 else (px, py)
    return {
        "rooms": rooms,
        "doors": doors,
        "steps_remaining": len(rooms) - 1,
        "next_room_centroid_px": [round(cx, 1), round(cy, 1)],
        "first_step": _compass(cx - px, cy - py),
        "status": "ok",
    }


def bfs_route(px: float, py: float) -> Dict:
    """Best-effort a nivel de celda. Si la rasterización del SVG deja el
    bolsillo de la EXIT sellado, reporta el bloqueo sin mentir con hitos."""
    exit_cell = (EXITS[0]["x"] // CELL, EXITS[0]["y"] // CELL)
    start = (int(px) // CELL, int(py) // CELL)

    def passable(c: int, r: int) -> bool:
        if not (0 <= c < COLS and 0 <= r < ROWS):
            return False
        v = GRID[r][c]
        return v in (None, "door", "exit")

    prev: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {start: None}
    queue = deque([start])
    found = False
    while queue:
        cur = queue.popleft()
        if cur == exit_cell:
            found = True
            break
        c, r = cur
        for nc, nr in ((c - 1, r), (c + 1, r), (c, r - 1), (c, r + 1)):
            if (nc, nr) not in prev and passable(nc, nr):
                prev[(nc, nr)] = cur
                queue.append((nc, nr))
    if not found:
        return {"route_found": False, "reason": "exit unreachable from here"}

    path = []
    node: Optional[Tuple[int, int]] = exit_cell
    while node is not None:
        path.append(node)
        node = prev[node]  # type: ignore[assignment]
    path.reverse()
    steps = [
        {"cell": list(c), "px": [c[0] * CELL + CELL // 2, c[1] * CELL + CELL // 2]}
        for c in path
    ]
    step_dir = None
    if len(path) >= 2:
        step_dir = _compass(path[1][0] - path[0][0], path[1][1] - path[0][1])
    return {
        "route_found": True,
        "route_length_cells": len(path),
        "first_step": step_dir,
        "path_sample": steps[:8] + (
            [{"...": f"({len(path) - 8} more cells)"}] if len(path) > 8 else []
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Consolidado
# ─────────────────────────────────────────────────────────────────────────────


def compute_playbook(x: float, y: float, heading_deg: float = 0.0,
                     health: int = PLAYER_HEALTH, armor: int = PLAYER_ARMOR) -> Dict:
    from sense import locate, survey  # reutiliza el "dónde estoy" previo

    payload = {
        "heuristic_version": "1.0",
        "player_state": {
            "position_px": [x, y],
            "health": health,
            "armor": armor,
            "heading_deg": heading_deg,
        },
        "location": locate(x, y),
        "micro_perception": survey(x, y, heading_deg=heading_deg, fov_deg=360.0),
        "foe_analysis": analyze_foes(x, y),
        "sector_risk": sector_risk(x, y),
        "terrain_danger": terrain_danger(x, y),
        "aspirations": aspirations(x, y, health),
        "hidden_information": hidden_information(x, y),
        "room_route": room_route(x, y, locate(x, y)["room"]),
        "route_to_exit": bfs_route(x, y),
    }
    return payload


def to_json(payload: Dict, indent: int = 2) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True)


def _load_player() -> Tuple[float, float]:
    player_file = Path(__file__).resolve().parent.parent / "map" / "player.json"
    if player_file.exists():
        try:
            data = json.loads(player_file.read_text(encoding="utf-8"))
            return float(data["x"]), float(data["y"])
        except (ValueError, KeyError, OSError):
            pass
    return 140.0, 168.0


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Eurística completa que el protagonista no puede calcular solo.")
    parser.add_argument("--x", type=float, default=None)
    parser.add_argument("--y", type=float, default=None)
    parser.add_argument("--heading", type=float, default=0.0)
    parser.add_argument("--health", type=int, default=PLAYER_HEALTH)
    parser.add_argument("--armor", type=int, default=PLAYER_ARMOR)
    parser.add_argument("--output", "-o", type=str, default=None)
    args = parser.parse_args()

    x, y = (args.x, args.y) if (args.x is not None and args.y is not None) \
        else _load_player()
    payload = compute_playbook(x, y, args.heading, args.health, args.armor)
    text = to_json(payload)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"JSON written to {args.output}", file=__import__("sys").stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
