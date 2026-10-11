"""Display-only read of the schematic map layer for the Tk panel.

``map/sense.py`` and ``map/heuristics.py`` already answer the questions the
engine's myopic snapshot cannot: which foes are hidden, what is underfoot, how
many rooms remain to the exit.  ``world_model`` exposes that knowledge as the
JSON block the model *may* receive with ``v3w``.

The panel wants the same numbers whether or not they travel to the model, so
this module turns one snapshot into a small frozen readout the widgets can
render.  It is pure and fail-soft: a missing or broken schematic yields an
``available=False`` readout and the panel simply shows less.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .snapshot import DuumSnapshot
from .world_model import build_world_model, svg_heading_degrees


def _round(value, digits: int = 1):
    return round(float(value), digits)


@dataclass(frozen=True, slots=True)
class WorldReadout:
    """Everything the panel needs to paint the world without touching the model."""

    available: bool
    heading_deg: float
    position_px: tuple[float, float] | None = None
    sector_values: tuple[float, ...] = ()
    room: str | None = None
    room_kind: str | None = None
    floor: str | None = None
    standing_on: str | None = None
    nukage: bool = False
    route_steps: int | None = None
    route_rooms: tuple[str, ...] = ()
    hidden_foes: int | None = None
    foes_total: int | None = None
    foes_in_sight: int | None = None
    worst_risk: float | None = None
    worst_sector: int | None = None
    overall_risk: float | None = None
    recommended_bearing_degrees: float | None = None
    recommended_target: str | None = None
    top_threats: tuple[dict, ...] = ()
    top_aspirations: tuple[dict, ...] = ()
    raw: dict | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "heading_deg": self.heading_deg,
            "position_px": list(self.position_px) if self.position_px else None,
            "sector_values": list(self.sector_values),
            "room": self.room,
            "room_kind": self.room_kind,
            "floor": self.floor,
            "standing_on": self.standing_on,
            "nukage": self.nukage,
            "route_steps": self.route_steps,
            "route_rooms": list(self.route_rooms),
            "hidden_foes": self.hidden_foes,
            "foes_total": self.foes_total,
            "foes_in_sight": self.foes_in_sight,
            "worst_risk": self.worst_risk,
            "worst_sector": self.worst_sector,
            "overall_risk": self.overall_risk,
            "recommended_bearing_degrees": self.recommended_bearing_degrees,
            "recommended_target": self.recommended_target,
            "top_threats": list(self.top_threats),
            "top_aspirations": list(self.top_aspirations),
        }


def read_world(snapshot: DuumSnapshot) -> WorldReadout:
    """Build the schematic readout for ``snapshot``; never raises."""

    heading = svg_heading_degrees(snapshot.player.angle)
    model = build_world_model(snapshot)
    if model is None:
        return WorldReadout(available=False, heading_deg=heading)
    risk = model.get("sector_risk") or {}
    hidden = model.get("hidden_foes") or {}
    route = model.get("route") or {}
    hazards = model.get("hazards") or {}
    items = model.get("hidden_items") or {}
    position = model.get("position_px")
    return WorldReadout(
        available=True,
        heading_deg=heading,
        position_px=(float(position[0]), float(position[1])) if position else None,
        sector_values=tuple(float(value) for value in risk.get("sector_values", ())),
        room=model.get("room"),
        room_kind=model.get("room_kind"),
        floor=model.get("floor"),
        standing_on=hazards.get("standing_on"),
        nukage=bool(hazards.get("nukage")),
        route_steps=route.get("steps_remaining"),
        route_rooms=tuple(route.get("rooms", ())),
        hidden_foes=hidden.get("hidden"),
        foes_total=hidden.get("total"),
        foes_in_sight=hidden.get("in_sight"),
        worst_risk=risk.get("worst_risk"),
        worst_sector=risk.get("worst_sector"),
        overall_risk=risk.get("overall_risk"),
        recommended_bearing_degrees=risk.get("recommended_bearing_degrees"),
        recommended_target=items.get("recommended_target"),
        top_threats=tuple(hidden.get("top_threats", ())),
        top_aspirations=tuple(items.get("top_aspirations", ())),
        raw=model,
    )
