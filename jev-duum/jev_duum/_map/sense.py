#!/usr/bin/env python3
"""
mundo_doom.py — Modelo del mundo del mapa DOOM E1M1 (Hangar) para el protagonista.

Mantiene una rejilla de ocupación derivada del SVG automapa (map/doom_map.svg)
y expone dos primitivas sin dependencias externas:

  * locate(x, y)          -> sala en la que está el protagonista, con ángulo / celda.
  * survey(x, y, heading) -> estructura cercana (muros por raycast, puertas,
                             ítems, foes, pozos de nukage, teleporter, stairs)
                             listo para serializar.

La geometría se toma literalmente del SVG ya creado: `map/doom_map.svg`
(celdas de 20 px, muros verdes = sólido, azul = puerta, rojo = salida).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

Grid = List[List[Optional[str]]]  # None=aire, "wall"=muro, "door", "exit", ...

CELL = 20  # px por celda (coincide con la grilla del SVG)
MAP_W, MAP_H = 1000, 750
COLS, ROWS = MAP_W // CELL, MAP_H // CELL
LEGEND = ("center_x", "center_y")  # celda -> punto central

# ─────────────────────────────────────────────────────────────────────────────
#  Salas (dataclass) — coordenadas en celdas de 20 px, coherentes con el SVG
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Room:
    name: str
    # rectángulo (c1, r1, c2, r2) en celdas, inclusivo
    x1: int
    y1: int
    x2: int
    y2: int
    kind: str = "normal"          # normal / secret / exit-side
    secrets: int = 0
    neighbors: Tuple[str, ...] = ()

    def contains(self, col: int, row: int) -> bool:
        return self.x1 <= col <= self.x2 and self.y1 <= row <= self.y2

    @property
    def center(self) -> Tuple[float, float]:
        cx = (self.x1 + self.x2) / 2 * CELL + CELL / 2
        cy = (self.y1 + self.y2) / 2 * CELL + CELL / 2
        return (round(cx, 1), round(cy, 1))


ROOMS: Tuple[Room, ...] = (
    Room("START",         3,  5, 13, 10),   # 70..290 x 100..220
    Room("NUKAGE YARD",  20, 11, 28, 13),   # paso exterior, al sur
    Room("TELEPORT",      11, 16, 14, 18),   # teleporter morado
    Room("ARENA",        17, 17, 33, 26),   # sala sur grande
    Room("EXIT",         27, 23, 32, 25),   # sala de salida SE
    Room("COMPUTER ROOM",34, 10, 39, 14),   # sala este con columnas
    Room("SECRET",       36, 21, 39, 25, kind="secret"),
)

ROOM_BY_NAME: Dict[str, Room] = {r.name: r for r in ROOMS}

# ─────────────────────────────────────────────────────────────────────────────
#  Puertas, salidas, teleporter, escaleras (en metros de la rejilla)
# ─────────────────────────────────────────────────────────────────────────────

DOORS: Tuple[Dict, ...] = (
    {"x": 300, "y": 157, "w": 6, "h": 21, "label": "START->zigzag"},
    {"x": 520, "y": 143, "w": 6, "h": 34, "label": "patio->COMPUTER ROOM"},
    {"x": 447, "y": 300, "w": 30, "h": 6, "label": "ARENA->patio"},
    {"x": 486, "y": 242, "w": 6, "h": 25, "label": "zigzag->ARENA"},
    {"x": 650, "y": 187, "w": 6, "h": 15, "label": "COMPUTER ROOM->pasillo"},
)

EXITS: Tuple[Dict, ...] = (
    # Doble línea roja de salida en (675..695, 512..517)
    {"x": 675, "y": 512, "w": 20, "h": 5, "label": "EXIT door"},
)

TELEPORTER = {"x": 260, "y": 365, "r": 14}
STAIR_MARKS: Tuple[Tuple[float, float], ...] = ((445, 279), (465, 287), (485, 295))

# ────────────────────────────────────────────────────		                        ─────
#  Ítems y criaturas, extraídos del dibujo original
# ─────────────────────────────────────────────────────────────────────────────

ITEMS: Tuple[Dict, ...] = (
    {"kind": "medikit",      "x": 108, "y": 223},
    {"kind": "medikit",      "x": 548, "y": 308},
    {"kind": "medikit",      "x": 413, "y": 478},
    {"kind": "stimpack",     "x": 230, "y": 130},
    {"kind": "stimpack",     "x": 670, "y": 135},
    {"kind": "stimpack",     "x": 485, "y": 505},
    {"kind": "stimpack",     "x": 775, "y": 145},
    {"kind": "green_armor",  "x":  92, "y": 137},
    {"kind": "blue_armor",   "x": 229, "y": 360},
    {"kind": "soul_sphere",  "x": 745, "y": 350},
    {"kind": "megasphere",   "x": 765, "y": 465},
    {"kind": "shotgun",      "x": 715, "y": 140},
    {"kind": "chaingun",     "x": 392, "y": 118},
    {"kind": "rocket",       "x": 605, "y": 463},
    {"kind": "ammo_box",     "x": 156, "y": 177},
    {"kind": "ammo_box",     "x": 536, "y": 133},
    {"kind": "ammo_box",     "x": 461, "y": 425},
    {"kind": "ammo_box",     "x": 681, "y": 133},
    {"kind": "berserk",      "x": 624, "y": 261},
    {"kind": "barrels",      "x": 259, "y": 156},
    {"kind": "barrels",      "x": 430, "y": 458},
    {"kind": "barrels",      "x": 712, "y": 278},
    {"kind": "invisibility", "x": 340, "y": 310},
)

FOES: Tuple[Dict, ...] = (
    {"x": 120, "y": 140, "size": 7},  {"x": 185, "y": 185, "size": 7},
    {"x": 330, "y": 150, "size": 6},  {"x": 392, "y": 190, "size": 6},
    {"x": 498, "y": 132, "size": 5},  {"x": 540, "y": 210, "size": 6},
    {"x": 605, "y": 120, "size": 7},  {"x": 280, "y": 360, "size": 7},
    {"x": 230, "y": 352, "size": 6},  {"x": 435, "y": 380, "size": 7},
    {"x": 505, "y": 430, "size": 7},  {"x": 460, "y": 465, "size": 6},
    {"x": 620, "y": 480, "size": 7},  {"x": 705, "y": 435, "size": 6},
    {"x": 690, "y": 215, "size": 7}, {"x": 725, "y": 260, "size": 6},
    {"x": 365, "y": 260, "size": 10}, # Barón
)

# ─────────────────────────────────────────────────────────────────────────────
#  Muros: trazados de contorno del SVG convertidos a rejilla de ocupación.
#  Cada elemento es un segmento ortogonal (x1, y1, x2, y2) en pixeles SVG.
# ─────────────────────────────────────────────────────────────────────────────

WALL_SEGMENTS: Tuple[Tuple[float, float, float, float], ...] = (
    # SALA DE INICIO (muro exterior con nichos)
    (70, 110, 280, 110), (280, 110, 280, 140), (255, 140, 280, 140),
    (255, 140, 255, 175), (255, 175, 280, 175), (280, 175, 280, 235),
    (70, 235, 280, 235), (70, 110, 70, 235),
    # Pilares sala inicio
    (105, 145, 135, 145), (190, 145, 220, 145), (105, 200, 150, 200),
    # PASILLO ZIGZAG este
    (280, 140, 340, 140), (340, 125, 340, 175), (340, 125, 395, 125),
    (395, 125, 395, 180), (395, 125, 490, 125), (490, 125, 490, 180),
    (280, 170, 330, 170), (330, 170, 330, 190),
    (395, 165, 425, 165), (395, 165, 395, 200),
    # PATIO EXTERIOR (nukage yard)
    (520, 105, 650, 105), (650, 105, 650, 130),
    (650, 185, 650, 200), (650, 200, 630, 200),
    (520, 105, 520, 235), (520, 190, 558, 225),
    # Placeta del patio
    (555, 155, 610, 155), (555, 155, 555, 200), (555, 200, 610, 200),
    (610, 155, 610, 200), (567, 167, 598, 167), (567, 180, 598, 180),
    # ZIGZAG SUR
    (582, 215, 582, 240), (582, 240, 542, 240), (542, 240, 542, 270),
    (542, 270, 527, 270), (520, 235, 520, 275), (485, 270, 485, 315),
    (485, 315, 445, 315), (445, 315, 445, 345), (425, 345, 445, 315),
    # SALA OESTE (armadura azul + teleporter)
    (360, 345, 315, 345), (315, 345, 315, 370), (245, 370, 315, 370),
    (245, 370, 245, 310), (245, 310, 205, 310), (205, 310, 205, 335),
    # Nicho armadura azul
    (205, 335, 160, 335), (160, 335, 160, 380), (160, 380, 205, 380),
    # SALA SUR GRANDE (ARENA)
    (360, 345, 490, 345), (490, 345, 490, 330), (565, 330, 565, 350),
    (565, 350, 655, 350), (655, 350, 655, 375),
    (415, 395, 545, 395), (415, 395, 415, 480), (545, 395, 545, 445),
    # Nichos arena
    (430, 440, 470, 440), (430, 440, 430, 470), (470, 440, 470, 470),
    (480, 450, 520, 450), (520, 450, 520, 490), (480, 450, 480, 490),
    # SALA EXIT SE
    (560, 445, 655, 445), (655, 445, 655, 510), (560, 445, 560, 510),
    (560, 510, 585, 510), (585, 510, 585, 470), (630, 470, 630, 512),
    (630, 470, 585, 470), (630, 512, 655, 512),
    # Pasillo a EXIT / room NE
    (655, 465, 685, 465), (685, 465, 685, 425), (685, 425, 730, 425),
    # SALA SECRETA
    (730, 425, 800, 425), (800, 425, 800, 505), (730, 425, 730, 505),
    (730, 505, 800, 505), (745, 445, 785, 445), (770, 445, 770, 495),
    # CORREDOR ESTE
    (650, 105, 650, 105), (650, 130, 745, 130), (745, 130, 745, 200),
    (790, 200, 745, 200),
    # COMPUTER ROOM (sala este con columnas)
    (650, 200, 745, 200), (745, 200, 745, 285), (650, 200, 650, 285),
    (650, 285, 745, 285), (675, 230, 720, 230), (675, 230, 675, 255),
    (675, 255, 720, 255), (697, 230, 697, 255),
    # Columnas sueltas del mapa
    (430, 140, 446, 140), (430, 140, 430, 156), (446, 140, 446, 156),
    (430, 156, 446, 156),
    (470, 180, 486, 180), (470, 180, 470, 196), (486, 180, 486, 196),
    (470, 196, 486, 196),
    (360, 170, 374, 170), (360, 170, 360, 184), (374, 170, 374, 184),
    (360, 184, 374, 184),
    (620, 420, 634, 420), (620, 420, 620, 434), (634, 420, 634, 434),
    (620, 434, 634, 434),
    (675, 425, 689, 425), (675, 425, 675, 439), (689, 425, 689, 439),
    (675, 439, 689, 439),
)

# Pozos de nukage y agua (elipses del SVG)
NUKAGE_POOLS: Tuple[Dict, ...] = (
    {"cx": 582, "cy": 180, "rx": 55, "ry": 32},
    {"cx": 480, "cy": 140, "rx": 28, "ry": 16},
)
WATER_POOL = {"cx": 300, "cy": 278, "rx": 32, "ry": 20}

# ─────────────────────────────────────────────────────────────────────────────
#  Construcción de la rejilla de ocupación
# ─────────────────────────────────────────────────────────────────────────────


def build_grid() -> Grid:
    grid: Grid = [[None] * COLS for _ in range(ROWS)]

    def put(px: float, py: float, val: str) -> None:
        c, r = int(px) // CELL, int(py) // CELL
        if 0 <= c < COLS and 0 <= r < ROWS:
            if grid[r][c] in (None, "wall"):  # puerta > muro en prioridad
                grid[r][c] = val

    for seg in WALL_SEGMENTS:
        x1, y1, x2, y2 = seg
        # rasterizar el segmento suavemente (step the cell way)
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length / (CELL / 2)))
        for i in range(steps + 1):
            t = i / steps
            put(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, "wall")

    for door in DOORS:
        cx = door["x"] + door["w"] / 2
        cy = door["y"] + door["h"] / 2
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                put(cx + dx * CELL / 2, cy + dy * CELL / 2, "door")
    for ex in EXITS:
        cx = ex["x"] + ex["w"] / 2
        cy = ex["y"] + ex["h"] / 2
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                put(cx + dx * CELL / 2, cy + dy * CELL / 2, "exit")
    return grid


GRID: Grid = build_grid()


def cell_at(px: float, py: float) -> Optional[str]:
    c, r = int(px) // CELL, int(py) // CELL
    if 0 <= r < ROWS and 0 <= c < COLS:
        return GRID[r][c]
    return "wall"  # fuera del mapa = muro


def room_at(px: float, py: float) -> Optional[Room]:
    c, r = int(px) // CELL, int(py) // CELL
    for room in ROOMS:
        if room.contains(c, r):
            return room
    return None


def nearest_room(px: float, py: float) -> Tuple[Room, float]:
    p = (px, py)
    best, best_d = None, float("inf")
    for room in ROOMS:
        cx, cy = room.center
        d = math.hypot(cx - p[0], cy - p[1])
        if d < best_d:
            best, best_d = room, d
    return best, best_d  # type: ignore[return-value]


# ─────────────────────────────────────────────────────────────────────────────
#  Raycast DDA contra la rejilla (persistente, barato: COLS x ROWS = 50x37)
# ─────────────────────────────────────────────────────────────────────────────


def cast_ray(px: float, py: float, angle_rad: float,
             max_dist: float = 400.0) -> Dict:
    """Toma un rayo desde (px, py) en dirección angle_rad y devuelve lo
    primero que golpea: muro / puerta / exit, junto con la distancia."""
    step = 2.0  # px
    dx, dy = math.cos(angle_rad), math.sin(angle_rad)
    x, y = px, py
    traveled = 0.0
    while traveled < max_dist:
        x += dx * step
        y += dy * step
        traveled += step
        c = cell_at(x, y)
        if c == "wall":
            return {
                "kind": "wall",
                "distance_px": round(traveled, 1),
                "hit": [round(x, 1), round(y, 1)],
            }
        if c == "door":
            label = min(DOORS, key=lambda d: math.hypot(d["x"] - x, d["y"] - y))["label"]
            return {"kind": "door", "label": label,
                    "distance_px": round(traveled, 1),
                    "hit": [round(x, 1), round(y, 1)]}
        if c == "exit":
            return {"kind": "exit_door", "label": "EXIT",
                    "distance_px": round(traveled, 1),
                    "hit": [round(x, 1), round(y, 1)]}
    return {"kind": "none", "distance_px": round(max_dist, 1), "hit": None}


def raycast_fan(px: float, py: float, heading: float, n: int = 32,
                fov_deg: float = 360.0, max_dist: float = 400.0) -> List[Dict]:
    """Sondeo estructural alrededor del protagonista (heading en grados).
    Con fov 360 mapea todo el perímetro; con fov menor, solo lo visible."""
    rays = []
    fov = math.radians(fov_deg)
    for i in range(n):
        if fov_deg >= 359:
            a = 2 * math.pi * i / n + math.radians(heading)
        else:
            a = heading + fov * (i / (n - 1) - 0.5)
        rays.append(cast_ray(px, py, a, max_dist))
    return rays


# ─────────────────────────────────────────────────────────────────────────────
#  API de alto nivel para el protagonista
# ─────────────────────────────────────────────────────────────────────────────


def inside_nukage(px: float, py: float) -> bool:
    for pool in NUKAGE_POOLS:
        nx = (px - pool["cx"]) / pool["rx"]
        ny = (py - pool["cy"]) / pool["ry"]
        if nx * nx + ny * ny <= 1:
            return True
    return False


def inside_water(px: float, py: float) -> bool:
    nx = (px - WATER_POOL["cx"]) / WATER_POOL["rx"]
    ny = (py - WATER_POOL["cy"]) / WATER_POOL["ry"]
    return nx * nx + ny * ny <= 1


def nearby_entities(px: float, py: float, radius_px: float = 120.0,
                    source: Iterable[Dict] = ITEMS) -> List[Dict]:
    found = []
    for ent in source:
        d = math.hypot(ent["x"] - px, ent["y"] - py)
        if d <= radius_px:
            found.append({
                **{k: v for k, v in ent.items() if k != "x" and k != "y"},
                "distance_px": round(d, 1),
                "bearing_deg": round(
                    (math.degrees(math.atan2(ent["y"] - py, ent["x"] - px)) + 360) % 360, 1
                ),
            })
    return sorted(found, key=lambda e: e["distance_px"])


def on_teleporter(px: float, py: float) -> bool:
    return math.hypot(px - TELEPORTER["x"], py - TELEPORTER["y"]) <= TELEPORTER["r"]


def on_stairs(px: float, py: float, tol: float = 20.0) -> bool:
    return any(math.hypot(px - sx, py - sy) <= tol for sx, sy in STAIR_MARKS)


def locate(x: float, y: float) -> Dict:
    """¿Dónde estoy ahora mismo? — estado de ubicación del protagonista."""
    room = room_at(x, y)
    near, near_d = nearest_room(x, y)
    floor = cell_at(x, y)
    return {
        "position_px": [round(x, 1), round(y, 1)],
        "cell": [int(x) // CELL, int(y) // CELL],
        "room": room.name if room else None,
        "room_kind": room.kind if room else "corridor",
        "nearest_room": near.name,
        "nearest_room_distance_px": round(near_d, 1),
        "floor": floor or "floor",
        "hazards": {
            "nukage": inside_nukage(x, y),
            "water": inside_water(x, y),
        },
        "on_teleporter": on_teleporter(x, y),
        "on_stairs": on_stairs(x, y),
    }


def survey(x: float, y: float, heading_deg: float = 0.0,
           fov_deg: float = 360.0, radius_px: float = 120.0) -> Dict:
    """¿Qué estructura me rodea? — sondeo de raycast + entidades cercanas."""
    payload = {
        "where": locate(x, y),
        "heading_deg": heading_deg % 360,
        "nearby_items": nearby_entities(x, y, radius_px, ITEMS),
        "nearby_foes": nearby_entities(x, y, radius_px, FOES),
        "walls": raycast_fan(x, y, heading_deg, n=32, fov_deg=fov_deg),
    }
    return payload


def to_json(payload: Dict, indent: int = 2) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True)


# ─────────────────────────────────────────────────────────────────────────────
#  CLI: ejecutar el script arroja un .json
# ─────────────────────────────────────────────────────────────────────────────


def _load_player() -> Tuple[float, float]:
    """Posición del protagonista. Si existe map/player.json se usa esa
    posición (se actualiza cada tick); si no, el punto de inicio."""
    player_file = Path(__file__).resolve().parent.parent / "map" / "player.json"
    if player_file.exists():
        try:
            data = json.loads(player_file.read_text(encoding="utf-8"))
            return float(data["x"]), float(data["y"])
        except (ValueError, KeyError, OSError):
            pass
    return 140.0, 168.0  # punto de inicio del SVG (flecha blanca del jugador)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Ubicación y estructura cercana del protagonista en E1M1.")
    parser.add_argument("--x", type=float, default=None,
                        help="posición X del protagonista en px del SVG")
    parser.add_argument("--y", type=float, default=None,
                        help="posición Y del protagonista en px del SVG")
    parser.add_argument("--heading", type=float, default=0.0,
                        help="rumbo en grados (0 = este)")
    parser.add_argument("--fov", type=float, default=360.0,
                        help="campo de visión en grados (default 360)")
    parser.add_argument("--radius", type=float, default=120.0,
                        help="radio de entidades cercanas en px")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="archivo .json de salida (default: stdout)")
    args = parser.parse_args()

    if args.x is not None and args.y is not None:
        x, y = args.x, args.y
    else:
        x, y = _load_player()

    payload = survey(x, y, heading_deg=args.heading, fov_deg=args.fov,
                     radius_px=args.radius)
    text = to_json(payload)

    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"JSON written to {args.output}", file=__import__("sys").stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
