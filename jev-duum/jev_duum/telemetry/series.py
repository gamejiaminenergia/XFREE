"""The two bounded series: vitals over time and token consumption."""

from __future__ import annotations

from ..theme import BG, FONTS, OFF, VALUE, WARN
from .canvas import _SMALL, _caption, _set_caption


class VitalTrace:
    """Health and ammo over time, with a vertical mark per guard intervention."""

    def __init__(self, tkinter, parent, *, width=190, height=44):
        self.height = int(height)
        self.caption = _caption(tkinter, parent, width=24)
        self.canvas = tkinter.Canvas(
            parent, width=int(width), height=self.height, bg=BG,
            highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="x")
        self._sig = None

    def render(self, health, ammo, marks, max_health):
        health = [float(value) for value in health]
        ammo = [float(value) for value in ammo]
        marks = [bool(value) for value in marks]
        width = self.canvas.winfo_width() or 190
        signature = (tuple(health), tuple(ammo), tuple(marks), max_health, width)
        if signature == self._sig:
            return
        self._sig = signature
        canvas = self.canvas
        canvas.delete("all")
        h = self.height
        count = max(len(health), len(ammo))
        _set_caption(self.caption, "VIDA / MUNICIÓN")
        if count < 2:
            canvas.create_text(3, h / 2, text="sin serie todavía", anchor="w",
                               fill=OFF, font=(FONTS["mono"], _SMALL))
            return
        ceiling = max(1.0, float(max_health), max(ammo or [1.0]))
        span = max(1, width - 2)

        def px(index):
            return 1 + (index / (count - 1)) * span

        def py(value):
            return h - 2 - (value / ceiling) * (h - 4)

        for index, flag in enumerate(marks[:count]):
            if flag:
                canvas.create_line(px(index), 0, px(index), h, fill=WARN, dash=(2, 3))
        for series, colour in ((ammo, OFF), (health, VALUE)):
            if len(series) < 2:
                continue
            points = []
            for index, value in enumerate(series):
                points.extend((px(index), py(value)))
            canvas.create_line(*points, fill=colour, width=1)


class ConsumptionPanel:
    """Tokens per decision (tiny bars) plus the running and average cost."""

    def __init__(self, tkinter, parent, *, height=22):
        self.height = int(height)
        self.caption = _caption(tkinter, parent, width=24)
        self.canvas = tkinter.Canvas(
            parent, width=160, height=self.height, bg=BG, highlightthickness=0, bd=0
        )
        self.canvas.pack(fill="x")
        self._sig = None

    def render(self, tokens_in, tokens_out, cost, decisions):
        tokens_in = [float(value) for value in tokens_in]
        tokens_out = [float(value) for value in tokens_out]
        width = self.canvas.winfo_width() or 240
        signature = (tuple(tokens_in), tuple(tokens_out), round(cost, 8), decisions, width)
        if signature == self._sig:
            return
        self._sig = signature
        canvas = self.canvas
        canvas.delete("all")
        average = (cost / decisions) if decisions else 0.0
        _set_caption(
            self.caption,
            f"COSTE ${cost:.5f}\nMEDIA ${average:.5f}",
        )
        combined = tokens_in + tokens_out
        if len(combined) < 2:
            return
        peak = max(combined) or 1.0
        step = max(1.0, width / max(1, len(tokens_in)))
        base = self.height - 1
        for index, value in enumerate(tokens_in):
            x = index * step
            canvas.create_rectangle(
                x, base - (value / peak) * (base - 1), x + step - 1, base,
                fill=VALUE, outline="",
            )
        for index, value in enumerate(tokens_out):
            x = index * step
            canvas.create_rectangle(
                x, base - (value / peak) * (base - 1) * 0.6, x + step - 1, base,
                fill=OFF, outline="",
            )
