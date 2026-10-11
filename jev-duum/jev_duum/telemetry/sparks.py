"""The two sparklines: decision latency and per-head confidence."""

from __future__ import annotations

from ..theme import BG, FONTS, OFF, STATIC, VALUE, WARN
from .canvas import _SMALL, _caption, _set_caption


class LatencySpark:
    """Decision latency over the last N decisions, with p50 and p95 references."""

    def __init__(self, tkinter, parent, *, height=34):
        self.height = int(height)
        self.caption = _caption(tkinter, parent, width=44)
        self.canvas = tkinter.Canvas(
            parent, width=220, height=self.height, bg=BG, highlightthickness=0, bd=0
        )
        self.canvas.pack(fill="x")
        self._sig = None

    def render(self, series, p50, p95):
        series = [float(value) for value in series]
        width = self.canvas.winfo_width() or 240
        signature = (tuple(series), p50, p95, width)
        if signature == self._sig:
            return
        self._sig = signature
        canvas = self.canvas
        canvas.delete("all")
        h = self.height
        _set_caption(
            self.caption,
            f"LATENCIA ms   p50 {p50:.0f}  p95 {p95:.0f}  n {len(series)}"
            if p50 is not None and p95 is not None
            else "LATENCIA ms   sin serie",
        )
        if len(series) < 2 or p95 is None:
            canvas.create_text(
                3, h / 2, text="sin serie todavía", anchor="w", fill=OFF,
                font=(FONTS["mono"], _SMALL),
            )
            return
        ceiling = max(max(series), p95) * 1.15 or 1.0
        count = len(series)

        def px(index):
            return 1 + (index / (count - 1)) * (width - 2)

        def py(value):
            return h - 2 - (value / ceiling) * (h - 4)

        canvas.create_line(0, py(p95), width, py(p95), fill=WARN, dash=(4, 3))
        canvas.create_line(0, py(p50), width, py(p50), fill=OFF, dash=(1, 3))
        points = []
        for index, value in enumerate(series):
            points.extend((px(index), py(value)))
        canvas.create_line(*points, fill=VALUE, width=1)
        for index, value in enumerate(series):
            if value > p95:
                canvas.create_rectangle(
                    px(index) - 1, py(value) - 1, px(index) + 1, py(value) + 1,
                    fill=WARN, outline="",
                )


class ConfidenceSpark:
    """One thin confidence trace per typed head (MOV / APU / ACC)."""

    ROWS = (("movement", "MOV"), ("aim", "APU"), ("interaction", "ACC"))

    def __init__(self, tkinter, parent, *, height=40):
        self.height = int(height)
        self.caption = _caption(tkinter, parent, width=24)
        self.canvas = tkinter.Canvas(
            parent, width=160, height=self.height, bg=BG, highlightthickness=0, bd=0
        )
        self.canvas.pack(fill="x")
        self._sig = None

    def render(self, series_by_axis):
        width = self.canvas.winfo_width() or 240
        rows = [(tag, series_by_axis.get(axis, ())) for axis, tag in self.ROWS]
        signature = (tuple((tag, tuple(values)) for tag, values in rows), width)
        if signature == self._sig:
            return
        self._sig = signature
        canvas = self.canvas
        canvas.delete("all")
        h = self.height
        count = max((len(values) for _tag, values in rows), default=0)
        _set_caption(self.caption, f"CONFIANZA POR CABEZA\nn={count}")
        if count < 2:
            canvas.create_text(
                3, h / 2, text="sin serie todavía", anchor="w", fill=OFF,
                font=(FONTS["mono"], _SMALL),
            )
            return
        track = max(2, (h - 2) // len(rows))
        for row_index, (tag, values) in enumerate(rows):
            top = 1 + row_index * track
            bottom = top + track - 2
            canvas.create_text(
                1, (top + bottom) / 2, text=tag, anchor="w", fill=STATIC,
                font=(FONTS["mono"], _SMALL),
            )
            if len(values) < 2:
                continue
            left = 30
            span = max(1, width - left - 24)
            points = []
            for index, value in enumerate(values):
                x = left + (index / (len(values) - 1)) * span
                y = bottom - max(0.0, min(1.0, float(value))) * (bottom - top)
                points.extend((x, y))
            canvas.create_line(*points, fill=VALUE if row_index == 0 else OFF, width=1)
            last = max(0.0, min(1.0, float(values[-1])))
            canvas.create_text(
                width - 1, (top + bottom) / 2, text=f"{last:.2f}", anchor="e",
                fill=WARN if last < 0.40 else VALUE, font=(FONTS["mono"], _SMALL),
            )
