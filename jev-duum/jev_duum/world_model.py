"""Schematic level knowledge for Jev: the gameplay layer the snapshot cannot see.

Duum's canonical snapshot is *tactical and myopic*: enemies in sight,
projectiles in flight, pickups on screen.  ``map/sense.py`` and
``map/heuristics.py`` already solve the layer the engine cannot know by design
— hidden foes, 360-degree sector risk, nukage underfoot, route to the exit —
against a schematic automap of Freedoom E1M1.

This adapter bridges the two coordinate systems and returns one JSON-safe
block.  It is **informative, not authoritative**: the snapshot and the
deterministic guard always win, and every failure returns ``None`` so gameplay
survives without it.

Calibration (measured, not guessed)
-----------------------------------
The schematic SVG is *not* a faithful projection of the WAD: the WAD's vertex
bounds are 3952x3400 units (aspect 1.16) while the SVG's wall bounds are
730x407 px (aspect 1.79).  No single similarity transform can be exact, so the
mapping is anchored at the player spawn — the one correspondence we can measure
without ambiguity — with an independent scale per axis and the Y axis flipped
(Doom's Y grows north, the SVG's grows south).

    spawn in Duum units: (-416.0, 256.0)   ->   SVG pixel (140.0, 168.0)

Local accuracy near the spawn is exact and error grows with distance from it.
``calibration`` travels inside the block so the approximation is auditable.
"""

from __future__ import annotations

import math

from .snapshot import DuumSnapshot

# WAD vertex bounds (all linedefs, Freedoom E1M1) and the SVG wall bounds
# (``_map.sense.WALL_SEGMENTS``).  Re-measure these two lines if the map or the
# schematic is ever regenerated.
WAD_BOUNDS = (-704.0, 3248.0, -1064.0, 2336.0)
SVG_BOUNDS = (70.0, 800.0, 105.0, 512.0)

DUUM_SPAWN = (-416.0, 256.0)
SVG_SPAWN = (140.0, 168.0)

SCALE_X = (SVG_BOUNDS[1] - SVG_BOUNDS[0]) / (WAD_BOUNDS[1] - WAD_BOUNDS[0])
SCALE_Y = (SVG_BOUNDS[3] - SVG_BOUNDS[2]) / (WAD_BOUNDS[3] - WAD_BOUNDS[2])

_playbook = None


def _load_playbook():
    """Import the vendored map layer once (building its grid is not free)."""

    global _playbook
    if _playbook is None:
        from ._map import heuristics

        _playbook = heuristics
    return _playbook


def duum_to_svg(x: float, y: float) -> tuple[float, float]:
    """Map one Duum map position to schematic SVG pixels."""

    px = SVG_SPAWN[0] + (float(x) - DUUM_SPAWN[0]) * SCALE_X
    py = SVG_SPAWN[1] - (float(y) - DUUM_SPAWN[1]) * SCALE_Y
    return px, py


def svg_heading_degrees(angle_radians: float) -> float:
    """Player heading in the SVG frame (0 = east, clockwise on screen)."""

    return -math.degrees(float(angle_radians)) % 360.0


# Kept as the internal alias it grew up as; the panel imports the public name.
_svg_heading_degrees = svg_heading_degrees


def _relative_bearing_degrees(px: float, py: float, tx: float, ty: float, heading_deg: float):
    """Signed degrees to turn, using the prompt convention: positive = LEFT.

    The SVG's Y axis points down, so a clockwise screen angle is *right*; the
    sign is flipped to match ``prompts.CONVENTIONS`` (and the snapshot's own
    ``_bearing_word``, where positive is left).
    """

    dx, dy = float(tx) - float(px), float(ty) - float(py)
    if dx == 0.0 and dy == 0.0:
        return 0.0
    heading = math.radians(heading_deg)
    fx, fy = math.cos(heading), math.sin(heading)
    length = math.hypot(dx, dy)
    vx, vy = dx / length, dy / length
    clockwise = math.degrees(math.atan2(fx * vy - fy * vx, fx * vx + fy * vy))
    bearing = -clockwise
    if bearing > 180.0:
        bearing -= 360.0
    elif bearing < -180.0:
        bearing += 360.0
    return bearing


def _round(value, digits: int = 1):
    return round(float(value), digits)


def _hazards(location: dict, danger: dict) -> dict:
    adjacent = [
        {"offset": list(entry["offset_cells"]), "kind": entry["kind"]}
        for entry in danger.get("adjacent_cells", [])
    ]
    return {
        "standing_on": danger.get("standing_on", "floor"),
        "nukage": bool(location.get("hazards", {}).get("nukage")),
        "nukage_damage_per_tick": int(danger.get("nukage_damage_per_tick", 0)),
        "adjacent": adjacent,
        "on_teleporter": bool(location.get("on_teleporter")),
        "on_stairs": bool(location.get("on_stairs")),
    }


def _top_threats(foe_analysis: dict, px: float, py: float, heading: float) -> list:
    ranked = [foe for foe in foe_analysis.get("threats", []) if foe.get("threat_score", 0) > 0]
    ranked.sort(key=lambda foe: -foe["threat_score"])
    top = []
    for foe in ranked[:3]:
        fx, fy = foe["position_px"]
        top.append(
            {
                "bearing_degrees": _round(_relative_bearing_degrees(px, py, fx, fy, heading)),
                "distance_px": _round(foe["distance_px"]),
                "threat_score": _round(foe["threat_score"], 3),
                "line_of_sight": bool(foe["line_of_sight"]),
                "expected_damage_per_hit": _round(foe["expected_damage_per_hit"]),
            }
        )
    return top


def _top_aspirations(aspirations: dict, px: float, py: float, heading: float) -> list:
    top = []
    for item in aspirations.get("top_aspirations", [])[:3]:
        ix, iy = item["position_px"]
        top.append(
            {
                "kind": item["kind"],
                "bearing_degrees": _round(_relative_bearing_degrees(px, py, ix, iy, heading)),
                "distance_px": _round(item["distance_px"]),
                "aspiration_score": _round(item["aspiration_score"], 3),
            }
        )
    return top


def build_world_model(snapshot: DuumSnapshot) -> dict | None:
    """Return the schematic world model, or ``None`` when it cannot be built."""

    try:
        player = snapshot.player
        heuristics = _load_playbook()
        px, py = duum_to_svg(player.x, player.y)
        heading = _svg_heading_degrees(player.angle)
        playbook = heuristics.compute_playbook(
            px, py, heading, int(player.health), int(player.armor)
        )
        location = playbook["location"]
        foes = playbook["foe_analysis"]
        risk = playbook["sector_risk"]
        danger = playbook["terrain_danger"]
        aspiration = playbook["aspirations"]
        hidden = playbook["hidden_information"]
        route = playbook["room_route"]
        model = {
            "map": snapshot.map_name,
            "position_px": [_round(px), _round(py)],
            "cell": list(location["cell"]),
            "room": location["room"],
            "room_kind": location["room_kind"],
            "nearest": {
                "room": location["nearest_room"],
                "distance_px": _round(location["nearest_room_distance_px"]),
            },
            "floor": location["floor"],
            "hazards": _hazards(location, danger),
            "route": {
                "rooms": list(route.get("rooms", [])),
                "doors": list(route.get("doors", [])),
                "steps_remaining": int(route.get("steps_remaining", 0)),
                "first_step": route.get("first_step"),
                "status": route.get("status"),
            },
            "sector_risk": {
                "sector_values": [_round(value, 3) for value in risk["sector_values"]],
                "worst_sector": int(risk["worst_sector"]),
                "worst_risk": _round(risk["worst_risk"], 3),
                "safest_sector": int(risk["safest_sector"]),
                "recommended_bearing_degrees": _round(
                    _relative_bearing_degrees(
                        px,
                        py,
                        px + math.cos(math.radians(risk["recommended_heading_deg"])),
                        py + math.sin(math.radians(risk["recommended_heading_deg"])),
                        heading,
                    )
                ),
                "avoid_bearing_degrees": _round(
                    _relative_bearing_degrees(
                        px,
                        py,
                        px + math.cos(math.radians(risk["avoid_heading_deg"])),
                        py + math.sin(math.radians(risk["avoid_heading_deg"])),
                        heading,
                    )
                ),
                "overall_risk": _round(risk["overall_risk"], 3),
            },
            "hidden_foes": {
                "total": int(foes["foes_total"]),
                "in_sight": int(foes["foes_in_sight"]),
                "hidden": int(foes["foes_hidden"]),
                "top_threats": _top_threats(foes, px, py, heading),
            },
            "hidden_items": {
                "count": int(hidden["items_hidden_count"]),
                "secrets_remaining": int(hidden["secrets_count"]),
                "top_aspirations": _top_aspirations(aspiration, px, py, heading),
                "recommended_target": aspiration.get("recommended_target"),
                "health_context": aspiration.get("health_context"),
            },
            "calibration": {
                "src": "svg-approx",
                "scale_x": _round(SCALE_X, 5),
                "scale_y": _round(SCALE_Y, 5),
                "anchor_duum": list(DUUM_SPAWN),
                "anchor_svg": list(SVG_SPAWN),
            },
        }
        return model
    except Exception:
        # Fail soft: a missing or broken schematic must never stop the agent.
        return None
