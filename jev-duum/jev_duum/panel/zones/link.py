"""Link zone: request, response, counters and what the request costs."""

from __future__ import annotations

import json

from ...telemetry import ConfidenceSpark, ConsumptionPanel, PolicyDelta
from ...theme import BG, FONTS, OFF, PANEL, RULE, STATIC, VALUE
from ..format import _percentile, _questions_summary, _state_index
from ..render import label, render_json, render_text
from ..widgets import Panel, _plain_text, _table


class LinkSection:
    # -- right column: the link, request and response ------------------------
    def _build_link(self):
        tk = self.tk
        counters = tk.Frame(self.right, bg=BG)
        counters.pack(fill="x", pady=(0, 6))
        self._tiles = {}
        self._tile_captions = {}
        for column, (key, caption, unit) in enumerate(
            (
                ("decisions", "DECISIONES", ""), ("p50", "p50", "ms"),
                ("p95", "p95", "ms"), ("tokens", "TOKENS ENV.", ""),
            )
        ):
            cell = tk.Frame(counters, bg=PANEL, highlightbackground=RULE, highlightthickness=1)
            cell.grid(row=0, column=column, sticky="nsew", padx=(0, 5))
            counters.grid_columnconfigure(column, weight=1)
            value = tk.Label(
                cell, text="—", width=9, anchor="w", bg=PANEL, fg=VALUE,
                font=(FONTS["mono"], 11, "bold"),
            )
            value.pack(anchor="w", padx=6, pady=(4, 0))
            # The sample count travels with the percentile: a p95 over one
            # measurement is that measurement, and it used to look like a bug.
            label = tk.Label(
                cell, text=f"{caption} {unit}".strip(), width=18, anchor="w",
                bg=PANEL, fg=STATIC, font=(FONTS["mono"], 9),
            )
            label.pack(anchor="w", padx=6, pady=(0, 4))
            self._tiles[key] = value
            self._tile_captions[key] = (label, f"{caption} {unit}".strip())
        self.cost_label = tk.Label(
            self.right, text="", width=30, anchor="w", bg=BG, fg=STATIC,
            font=(FONTS["mono"], 9),
        )
        self.cost_label.pack(fill="x", pady=(0, 6))

        columns = tk.Frame(self.right, bg=BG)
        columns.pack(fill="both", expand=True)
        columns.grid_columnconfigure(0, weight=1, uniform="io")
        columns.grid_columnconfigure(1, weight=1, uniform="io")
        columns.grid_rowconfigure(0, weight=1)
        self._build_request(columns)
        self._build_response(columns)

    def _build_request(self, parent):
        tk = self.tk
        panel = Panel(tk, parent, "Enlace · petición", expand=True, manage=False)
        panel.frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._request_table, self.request_fields = _table(
            tk, panel.body,
            (
                ("MODELO", "model"), ("PROMPT", "prompt"), ("TOKENS", "tokens"),
                ("TAMAÑO", "bytes"), ("CLAVES", "keys"), ("PREGUNTAS", "questions"),
            ),
            size=9, value_width=18,
        )
        tk.Label(
            panel.body, text="ÍNDICE DEL ESTADO", anchor="w", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 9, "bold"),
        ).pack(fill="x", pady=(6, 0))
        self.state_index_text = _plain_text(tk, panel.body, height=6, size=9, width=24,
                                           wrap="none")
        self.state_index_text.pack(fill="both", expand=True, pady=(2, 4))
        tk.Label(
            panel.body, text="PREGUNTAS TIPADAS", anchor="w", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 9, "bold"),
        ).pack(fill="x")
        self.questions_text = _plain_text(tk, panel.body, height=6, size=9, width=24)
        self.questions_text.pack(fill="both", expand=True, pady=(2, 0))
        # The lower slack of the request panel carries what the request costs.
        tk.Frame(panel.body, bg=RULE, height=1).pack(fill="x", pady=(6, 2))
        self.consumption = ConsumptionPanel(tk, panel.body)

    def _build_response(self, parent):
        tk = self.tk
        panel = Panel(tk, parent, "Enlace · respuesta", expand=True, manage=False)
        panel.frame.grid(row=0, column=1, sticky="nsew")
        self._response_table, self.response_fields = _table(
            tk, panel.body,
            (
                ("MODELO", "model"), ("PROMPT", "prompt"), ("PETICIÓN", "request"),
                ("DECISIÓN", "decision"), ("EDAD", "age"), ("LLAMADAS", "exec"),
                ("BITÁCORA", "log"),
            ),
            size=9, value_width=26,
        )
        tk.Label(
            panel.body, text="RESPUESTA CRUDA", anchor="w", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 9, "bold"),
        ).pack(fill="x", pady=(6, 0))
        self.response_raw_text = _plain_text(tk, panel.body, height=10, size=9, width=24,
                                             wrap="char")
        self.response_raw_text.pack(fill="both", expand=True, pady=(2, 0))
        # Stability of the policy: what the previous decision and this one share,
        # and the model's confidence per head over the session.
        tk.Frame(panel.body, bg=RULE, height=1).pack(fill="x", pady=(6, 2))
        self.confidence_spark = ConfidenceSpark(tk, panel.body)
        self.policy_delta = PolicyDelta(tk, panel.body, width=28)

    def _update_counters(self):
        p50 = _percentile(self.session.latencies, 0.50)
        p95 = _percentile(self.session.latencies, 0.95)
        samples = len(self.session.latencies)
        tiles = {
            "decisions": str(self.session.decisions),
            "p50": f"{p50:.0f}" if p50 is not None else "—",
            "p95": f"{p95:.0f}" if p95 is not None else "—",
            "tokens": str(self.session.tokens),
        }
        for key, value in tiles.items():
            label(self.cache, f"tile-{key}", self._tiles[key], value)
        for key in ("p50", "p95"):
            caption_widget, caption = self._tile_captions[key]
            label(self.cache, f"caption-{key}", caption_widget, f"{caption} n={samples}")
        label(self.cache, "cost", self.cost_label, f"COSTE ACUMULADO  ${self.session.cost:.5f}")

    # -- request and response, always visible --------------------------------
    def _update_request(self, decision):
        if decision is None:
            for key, widget in self.request_fields.items():
                label(self.cache, f"req-{key}", widget, "sin dato", fg=OFF)
            render_text(self.cache, "state-index", self.state_index_text, "sin dato")
            render_text(self.cache, "questions", self.questions_text, "sin dato")
            return
        state = decision.request_state
        fields = {
            "model": decision.model_id,
            "prompt": decision.prompt_version,
            "tokens": str((decision.input_tokens or {}).get("request", 0)),
            "bytes": f"{len(json.dumps(state, default=str).encode('utf-8'))} B",
            "keys": str(len(state) if isinstance(state, dict) else 0),
            "questions": str(len(decision.request_questions or {})),
        }
        for key, value in fields.items():
            label(self.cache, f"req-{key}", self.request_fields[key], value, fg=VALUE)
        render_text(self.cache, "state-index", self.state_index_text, _state_index(state))
        render_text(self.cache, 
            "questions", self.questions_text, _questions_summary(decision.request_questions)
        )

    def _update_response(self, decision, snapshot, log_stats):
        if decision is None:
            for key, widget in self.response_fields.items():
                label(self.cache, f"resp-{key}", widget, "sin dato", fg=OFF)
            render_json(self.cache, "response-raw", self.response_raw_text, None)
            return
        age = snapshot.tick - decision.observation_tick
        fields = {
            "model": decision.model_id,
            "prompt": decision.prompt_version,
            "request": f"{decision.request_ms:.0f} ms",
            "decision": f"{decision.decision_ms:.0f} ms",
            "age": f"{age} ticks",
            "exec": f"{decision.prediction_calls} llamada · {decision.execution}",
            "log": (
                f"{log_stats['sent']} enviados / {log_stats['dropped']} caídos"
                if log_stats
                else "desactivada"
            ),
        }
        for key, value in fields.items():
            label(self.cache, f"resp-{key}", self.response_fields[key], value, fg=VALUE)
        render_json(self.cache, 
            "response-raw", self.response_raw_text, getattr(decision, "response_raw", None)
        )
