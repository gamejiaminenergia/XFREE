"""Game zone: the engine canvas, the agent measurements and the diagram."""

from __future__ import annotations

from ...overlays import MiniMap, StaleOverlay
from ...telemetry import VitalTrace
from ...theme import BG, FONTS, OFF, PANEL, RULE, STATIC, VALUE
from ..format import _target_text, _threat_block
from ..render import label
from ..widgets import Bar, Panel, _table


class GameSection:
    # -- left column: the game, the measurements and the diagram ------------
    def _build_game(self, window):
        tk = self.tk
        root = window.root
        window.tkcv.configure(highlightthickness=1, highlightbackground=RULE, bg=BG)
        window.tkcv.grid(row=1, column=0, sticky="nw", padx=(0, 6), pady=(0, 6))
        self.stale_overlay = StaleOverlay(tk, window.tkcv)

        measurements = Panel(tk, root, "Medidas del agente", manage=False)
        measurements.frame.grid(row=2, column=0, sticky="ew", padx=(0, 6), pady=(0, 6))
        self.health = Bar(tk, measurements.body, "SALUD", unit="hp")
        self.armor = Bar(tk, measurements.body, "ARMADURA")
        self.ammo = Bar(tk, measurements.body, "MUNICIÓN")
        self._measures, self.measure_fields = _table(
            tk, measurements.body,
            (
                ("ARMA", "weapon"), ("PUNTOS", "kills"), ("OBJETOS", "items"),
                ("DAÑO", "damage"), ("SECTORES", "sectors"), ("PARADO", "stuck"),
            ),
            size=9, pairs=2, value_width=14,
        )

        diagram = Panel(tk, root, "Diagrama · amenazas y ruta", expand=True, manage=False)
        diagram.frame.grid(row=3, column=0, sticky="nsew", padx=(0, 6))
        body = diagram.body
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.map_holder = tk.Frame(body, bg=PANEL)
        self.map_holder.grid(row=0, column=0, sticky="nsew")
        self.minimap = MiniMap(tk, self.map_holder, width=300, height=120)
        self.minimap.canvas.pack(fill="both", expand=True)
        # ``fit`` reprojects without asking for a new size: ``resize`` here made
        # the cell grow the request that grew the cell until X ran out of pixmaps.
        self.minimap.canvas.bind(
            "<Configure>", lambda event: self.minimap.fit(event.width, event.height)
        )
        # The tags sit beside the diagram, not under it: a letterboxed map is
        # worth less than a square one, and the column has width to spare.
        side = tk.Frame(body, bg=PANEL)
        side.grid(row=0, column=1, sticky="new", padx=(10, 0))
        self._situation, self.world_fields = _table(
            tk, side,
            (
                ("SALA", "room"), ("PISO", "floor"), ("RUTA", "route"),
                ("ENEMIGOS", "foes"), ("RIESGO", "risk"), ("OBJETIVO", "target"),
            ),
            size=9, pairs=1, value_width=24,
        )
        self.world_threats = tk.Label(
            side, text="", anchor="w", justify="left", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 9),
        )
        self.world_threats.pack(fill="x", pady=(4, 0))
        # The lower slack beside the diagram carries the two vital traces with a
        # mark on every tick the guard intervened.
        self.vital_trace = VitalTrace(tk, side, width=190, height=44)

    def _build_situation(self):
        """The situational table lives inside the diagram panel.

        Kept as a named no-op so the build order in ``__init__`` still reads as
        the screen's zones: banner, game, situation, decision, link, events.
        """

    # -- situation: diagram tags, threats and route --------------------------
    def _update_situation(self, readout):
        if readout is None or not readout.available:
            for key, widget in self.world_fields.items():
                label(self.cache, f"world-{key}", widget, "sin dato", fg=OFF)
            label(self.cache, "world-threats", self.world_threats,
                        _threat_block(["sin modelo del mundo"]), fg=OFF)
            return
        route = f"{readout.route_steps} salas"
        if readout.route_rooms:
            route += "  " + "→".join(readout.route_rooms[:2])
        fields = {
            "room": f"{readout.room or '?'}"
            + (f" ({readout.room_kind})" if readout.room_kind else ""),
            "floor": f"{readout.floor or '—'}" + ("  NUKAGE" if readout.nukage else ""),
            "route": route,
            "foes": f"{readout.foes_in_sight} vis  {readout.hidden_foes} ocu"
            f"  {readout.foes_total} tot",
            "risk": f"p{readout.worst_sector} {readout.worst_risk}"
            f"  medio {readout.overall_risk}",
            "target": _target_text(readout.recommended_target),
        }
        for key, value in fields.items():
            label(self.cache, f"world-{key}", self.world_fields[key], value, fg=VALUE)
        # Every threat line is formatted to a fixed width, then clipped and
        # padded to the same cell: the diagram beside it is sized by this box,
        # so a wide number used to shrink the map.
        lines = [
            f"{threat['bearing_degrees']:>6.0f}° {threat['distance_px']:>6.0f}px"
            f"  AMEN {threat['threat_score']:>4.2f}"
            f"  {'LOS' if threat['line_of_sight'] else 'SIN LOS'}"
            for threat in readout.top_threats[:3]
        ]
        label(self.cache, "world-threats", self.world_threats, _threat_block(lines), fg=STATIC)
