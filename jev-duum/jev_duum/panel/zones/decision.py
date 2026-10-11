"""Decision zone: the typed axes, the guard, the why and the strategy."""

from __future__ import annotations

from ...telemetry import LatencySpark
from ...theme import FONTS, OFF, PANEL, RULE, STATIC, VALUE, WARN
from ..format import _clip, _controls_text
from ..layout import AXES, AXIS_ORDER, GUARD_H, STRATEGY_H, WHY_H
from ..render import label
from ..widgets import DecidRow, Flag, Panel, _table


class DecisionSection:
    # -- centre column: the decision ----------------------------------------
    def _build_decision(self):
        tk = self.tk
        panel = Panel(tk, self.center, "Decisión de la IA", expand=True)
        self.decision_panel = panel
        self.decision_flag = Flag(tk, panel.flag_holder, width=15)
        self.decision_flag.label.pack(side="right", pady=(2, 0))
        self.axes: dict = {}
        # The axes share the decision box's slack, so the only flexible box on
        # the screen spends its extra height instead of collecting a gap.
        self.axes_body = tk.Frame(panel.body, bg=PANEL)
        self.axes_body.pack(fill="both", expand=True)
        # The decision's own telemetry lives in the slack the bars would leave
        # blank: latency and confidence at decision rate, directly under them.
        tk.Frame(panel.body, bg=RULE, height=1).pack(fill="x", pady=(6, 0))
        tk.Label(
            panel.body, text="TELEMETRÍA · ÚLTIMAS 60 DECISIONES", anchor="w",
            bg=PANEL, fg=STATIC, font=(FONTS["mono"], 9, "bold"),
        ).pack(fill="x", pady=(4, 2))
        self.decision_telemetry = tk.Frame(panel.body, bg=PANEL)
        self.decision_telemetry.pack(fill="x")
        self.latency_hold = tk.Frame(self.decision_telemetry, bg=PANEL)
        self.latency_hold.pack(fill="x")
        self.latency_spark = LatencySpark(tk, self.latency_hold)

        guard = Panel(tk, self.center, "Guardia determinista")
        guard.set_height(GUARD_H)
        self.guard_panel = guard
        self.guard_flag = Flag(tk, guard.flag_holder, width=16)
        self.guard_flag.label.pack(side="right", pady=(2, 0))
        self._guard_table, self.guard_fields = _table(
            tk, guard.body,
            (("PROPUESTO", "prop"), ("APLICADO", "appl")),
            size=10, value_width=30,
        )
        self.guard_body = tk.Frame(guard.body, bg=PANEL)
        self.guard_body.pack(fill="x", pady=(3, 0))

        why = Panel(tk, self.center, "Por qué · respuesta del modelo")
        why.set_height(WHY_H)
        self.why_panel = why
        # One clipped line per axis: a wrapped value would change the box.
        self._why_table, self.observations = _table(
            tk, why.body, [(title, axis) for axis, title, _ in AXES],
            size=9, value_width=42,
        )

        strategy = Panel(tk, self.center, "Estrategia")
        strategy.set_height(STRATEGY_H)
        self.strategy_panel = strategy
        self.strategy_head = tk.Label(
            strategy.body, text="", anchor="w", justify="left", bg=PANEL, fg=VALUE,
            font=(FONTS["mono"], 9), wraplength=420,
        )
        self.strategy_head.pack(fill="x")
        self.strategy_plan = tk.Frame(strategy.body, bg=PANEL)
        self.strategy_plan.pack(fill="x", pady=(3, 0))

    # -- axes are built from what the model was actually asked ---------------
    def _ensure_axes(self, names):
        """One row per typed question the decision carries.

        The panel reads the axes off the response instead of hard-coding three,
        so a prompt that asks a fourth question shows it without a code change.
        """

        signature = tuple(sorted(names))
        if signature == self._axes_sig:
            return
        self._axes_sig = signature
        ordered = sorted(names, key=lambda name: AXIS_ORDER.get(name, len(AXES)))
        for name in ordered:
            if name in self.axes:
                continue
            title = next((title for key, title, _ in AXES if key == name), name.upper())
            tag = next((tag for key, _, tag in AXES if key == name), name[:3].upper())
            row = DecidRow(self.tk, self.axes_body, tag, title)
            row.frame.pack(fill="both", expand=True, pady=(0, 8))
            self.axes[name] = row
        for name, row in self.axes.items():
            if name not in ordered:
                row.frame.pack_forget()

    # -- the decision, axis by axis ------------------------------------------
    def _update_axes(self, decision):
        if decision is None:
            for row in self.axes.values():
                row.reset()
            return
        self._ensure_axes(decision.probabilities.keys())
        for name, row in self.axes.items():
            row.set(
                decision.probabilities.get(name, {}),
                decision.confidence.get(name),
                muted=self._muted,
            )

    def _update_guard(self, decision):
        events = decision.assistance_events if decision is not None else ()
        proposed = decision.proposed_controls if decision is not None else None
        applied = decision.applied_controls if decision is not None else None
        proposed_text = _controls_text(proposed)
        applied_text = _controls_text(applied)
        corrected = bool(proposed_text and applied_text and proposed_text != applied_text)
        label(self.cache, "guard-prop", self.guard_fields["prop"],
                    proposed_text or "sin dato", fg=VALUE if proposed_text else OFF)
        label(self.cache, "guard-appl", self.guard_fields["appl"],
                    applied_text or "sin dato",
                    fg=WARN if corrected else (VALUE if applied_text else OFF))
        self.guard_flag.level(
            f"INTERVINO ×{len(events)}" if events else "SIN INTERVENCIÓN",
            "warn" if events else "ok",
        )
        self.guard_panel.set_title(
            "Guardia determinista · interviniente" if events
            else "Guardia determinista · sin intervención"
        )
        signature = tuple(
            (event.kind, event.proposed, event.applied, event.reason) for event in events
        )
        if not self.cache.changed("guard", signature):
            return
        for child in self.guard_body.winfo_children():
            child.destroy()
        if not events:
            self.tk.Label(
                self.guard_body,
                text="se aplicó exactamente lo que propuso el modelo",
                bg=PANEL, fg=STATIC, font=(FONTS["mono"], 9), anchor="w",
            ).pack(anchor="w")
            return
        for event in events[:3]:
            row = self.tk.Frame(self.guard_body, bg=PANEL)
            row.pack(fill="x", pady=1)
            self.tk.Label(
                row, text=event.kind, bg=PANEL, fg=WARN,
                font=(FONTS["mono"], 9, "bold"), anchor="w",
            ).pack(side="left", padx=(0, 6))
            self.tk.Label(
                row, text=_clip(event.reason, 40),
                anchor="w", bg=PANEL, fg=STATIC, font=(FONTS["mono"], 9),
            ).pack(side="left")

    def _update_why(self, decision):
        for axis, widget in self.observations.items():
            text = "sin dato" if decision is None else decision.observations.get(axis, "—")
            label(self.cache, f"why-{axis}", widget, str(text).replace(">", "="))
        strategy = getattr(decision, "strategy", None) if decision is not None else None
        if strategy:
            head = (
                _clip(f"{strategy['mission']} · prioridad {strategy['priority']}", 54) + "\n"
                + _clip(
                    f"avanzar={strategy['must_move']}  sostener "
                    f"{strategy['hold_streak']}/{strategy['max_hold_streak']}  "
                    f"{strategy['status']}", 54
                )
            )
        else:
            head = "sin estrategia en este prompt"
        label(self.cache, "strategy-head", self.strategy_head, head)
        plan_sig = tuple(strategy.get("plan", ())) if strategy else ()
        if plan_sig != self._strategy_sig:
            self._strategy_sig = plan_sig
            for child in self.strategy_plan.winfo_children():
                child.destroy()
            for step in plan_sig[:3]:
                self.tk.Label(
                    self.strategy_plan, text=_clip(f"· {step}", 48), anchor="w",
                    bg=PANEL, fg=STATIC, font=(FONTS["mono"], 9),
                ).pack(fill="x")

    def _update_warmup(self, error):
        self.guard_flag.level("SIN DATO", "off")
        self.guard_panel.set_title("Guardia determinista · sin intervención")
        message = f"sin respuesta aún · {error}" if error else "esperando la primera decisión"
        if self.cache.changed("guard", ("warmup", message)):
            for child in self.guard_body.winfo_children():
                child.destroy()
            self.tk.Label(
                self.guard_body, text=message, anchor="w", bg=PANEL, fg=OFF,
                font=(FONTS["mono"], 9), wraplength=420,
            ).pack(anchor="w")
