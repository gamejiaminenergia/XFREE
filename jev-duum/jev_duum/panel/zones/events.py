"""Event list zone: newest decision first, with the session balance beside it."""

from __future__ import annotations

from ...telemetry import ActionBars, InterventionPanel
from ...theme import ALARM, BG, FONTS, OFF, PANEL, STATIC, VALUE, WARN
from ..format import _confidence_level
from ..layout import EVENT_ROWS
from ..widgets import Panel


class EventsSection:
    # -- event list: newest first, one row per decision ---------------------
    def _build_events(self):
        """A real event list: full width, one column per field.

        The fields used to be packed left, so the strip spent two thirds of the
        screen on nothing.  The last column takes the slack instead, and it
        carries the thing that actually explains an event: why the guard moved.
        """

        tk = self.tk
        # The bottom strip is two panels now: the events table keeps its full
        # height on the left, and the session balance fills the space to its right.
        strip = tk.Frame(self.bottom, bg=BG)
        strip.pack(fill="both", expand=True)
        strip.grid_columnconfigure(0, weight=3)
        strip.grid_columnconfigure(1, weight=2)
        strip.grid_rowconfigure(0, weight=1)
        self._strip = strip
        panel = Panel(tk, strip, "Eventos · último arriba", manage=False)
        panel.frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._events_panel = panel
        # The loop's own telemetry sits in the header's blank right half rather
        # than on a line of its own.
        self._event_note = tk.Label(
            panel.header, text="", width=52, anchor="e", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 9),
        )
        self._event_note.grid(row=0, column=1, sticky="e", padx=(0, 10))
        # ``#  TICK  MOV  APU  ACC  OBJ  CONF  ms  ESTADO`` are fixed width;
        # ``MOTIVO`` is the column that grows with the window.
        self._event_columns = (
            ("#", 6), ("TICK", 8), ("MOV", 14), ("APU", 8), ("ACC", 9), ("OBJ", 8),
            ("CONF", 6), ("ms", 5), ("ESTADO", 12), ("MOTIVO / INTERVENCIÓN", 0),
        )
        body = tk.Frame(panel.body, bg=PANEL)
        body.pack(fill="x")
        header = tk.Frame(body, bg=PANEL)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        for index, (text, width) in enumerate(self._event_columns):
            label = tk.Label(
                header, text=text, width=width or 1, anchor="w", bg=PANEL, fg=STATIC,
                font=(FONTS["mono"], 9, "bold"),
            )
            label.grid(row=0, column=index, sticky="ew", padx=(0, 8))
            header.grid_columnconfigure(index, weight=1 if width == 0 else 0)
        for row_index in range(EVENT_ROWS):
            row = tk.Frame(body, bg=PANEL)
            row.grid(row=row_index + 1, column=0, sticky="ew")
            cells = []
            for index, (_text, width) in enumerate(self._event_columns):
                cell = tk.Label(
                    row, text="", width=width or 1, anchor="w", bg=PANEL, fg=VALUE,
                    font=(FONTS["mono"], 9),
                )
                cell.grid(row=0, column=index, sticky="ew", padx=(0, 8))
                row.grid_columnconfigure(index, weight=1 if width == 0 else 0)
                cells.append(cell)
            body.grid_columnconfigure(0, weight=1)
            self._event_cells.append(cells)

        balance = Panel(tk, strip, "Balance de sesión", manage=False)
        balance.frame.grid(row=0, column=1, sticky="nsew")
        self._balance_panel = balance
        body = balance.body
        self.balance_body = body
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.intervention_hold = tk.Frame(body, bg=PANEL)
        self.intervention_hold.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.action_hold = tk.Frame(body, bg=PANEL)
        self.action_hold.grid(row=0, column=1, sticky="nsew")
        self.intervention = InterventionPanel(tk, self.intervention_hold)
        self.action_bars = ActionBars(tk, self.action_hold)

    # -- event list ----------------------------------------------------------
    def _update_events(self):
        items = list(self.session.history)[:EVENT_ROWS]
        signature = tuple(item["n"] for item in items)
        if signature == self.session.history_signature:
            return
        self.session.history_signature = signature
        for index, cells in enumerate(self._event_cells):
            if index >= len(items):
                for cell in cells:
                    cell.configure(text="")
                continue
            item = items[index]
            confidence = item["confidence"]
            _word, level = _confidence_level(confidence)
            values = (
                f"#{item['n']:04d}",
                str(item["tick"]),
                item["movement"],
                item["aim"],
                item["interaction"],
                item["target"] or "—",
                f"{confidence:.2f}" if confidence is not None else "—",
                f"{item['ms']:.0f}",
            )
            for cell, value in zip(cells[:8], values):
                cell.configure(text=value)
            cells[6].configure(fg={"warn": WARN, "alarm": ALARM}.get(level, VALUE))
            state = cells[8]
            if item["guard"]:
                state.configure(text="INTERVINO", fg=BG, bg=WARN)
            else:
                state.configure(text="APLICADO", fg=STATIC, bg=PANEL)
            cells[9].configure(
                text=item["guard"] or "sin intervención, aplicado tal cual",
                fg=STATIC if item["guard"] else OFF,
            )
