"""Session telemetry for the decision HMI: fixed-size canvases, bounded series.

Everything here is presentation, exactly like ``panel.py``.  Two rules shape it:

* **No box follows its data.**  Every widget owns a canvas whose height is fixed
  at construction and whose width comes from the fixed grid cell, so the HMI
  invariant (``tests/test_jev_hmi.py``: a section never moves when the data
  changes) holds by construction.  What does not fit is clipped.
* **The loop is never touched.**  These widgets hold no buffers and no clocks of
  their own: the dashboard owns bounded ``deque`` history and calls ``render``
  with a snapshot of it, throttled.  A widget that did not change draws nothing.

The palette is ``theme.py``; colour is still reserved for the abnormal — normal
traces are white/grey, and amber only marks a value over p95 or the guard acting
— and every coloured mark travels with its word in the caption above it.
"""

from __future__ import annotations

from .theme import BG, FONTS, OFF, PANEL, STATIC, TITLE, TRACK, VALUE, WARN

_SMALL = 9  # the guide's floor: nothing on this screen is smaller than 9 pt


def _caption(tkinter, parent, width=0):
    """A fixed-width caption row: the widget's word travels with its value."""

    label = tkinter.Label(
        parent, text="", width=width, anchor="w", justify="left", bg=PANEL,
        fg=STATIC, font=(FONTS["mono"], _SMALL),
    )
    label.pack(fill="x")
    return label


def _set_caption(label, text):
    """Set a caption, clipped to its fixed width like every other HMI cell."""

    try:
        width = int(label.cget("width"))
    except Exception:  # pragma: no cover - defensive
        width = 0
    if width:
        text = "\n".join(_clip(line, width) for line in str(text).split("\n"))
    if label.cget("text") != text:
        label.configure(text=text)


def _clip(text, width):
    text = str(text)
    if width and len(text) > width:
        return text[: max(1, width - 1)] + "…"
    return text


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


class InterventionPanel:
    """How often the deterministic guard intervened, and with which rules."""

    def __init__(self, tkinter, parent, *, height=54, rules=3):
        self.height = int(height)
        self.rules = int(rules)
        self.caption = _caption(tkinter, parent, width=38)
        self.canvas = tkinter.Canvas(
            parent, width=220, height=self.height, bg=BG, highlightthickness=0, bd=0
        )
        self.canvas.pack(fill="x")
        self._sig = None

    def render(self, flags, rule_counts):
        flags = [bool(value) for value in flags]
        top = tuple(
            sorted(rule_counts.items(), key=lambda item: (-item[1], item[0]))[: self.rules]
        )
        width = self.canvas.winfo_width() or 240
        signature = (tuple(flags), top, width)
        if signature == self._sig:
            return
        self._sig = signature
        canvas = self.canvas
        canvas.delete("all")
        total = len(flags)
        hit = sum(flags)
        rate = (hit / total) if total else 0.0
        _set_caption(
            self.caption,
            f"GUARDIA   intervino {hit}/{total}"
            + (f"  {rate * 100:.0f}%" if total else ""),
        )
        bar_h = 12
        canvas.create_rectangle(0, 0, width, bar_h, fill=TRACK, outline="")
        canvas.create_rectangle(
            0, 0, width * rate, bar_h, fill=WARN if hit else TRACK, outline=""
        )
        canvas.create_text(
            width - 2, bar_h / 2, text=f"{rate * 100:.0f}%" if total else "sin dato",
            anchor="e", fill=BG if rate > 0.5 else STATIC,
            font=(FONTS["mono"], _SMALL, "bold"),
        )
        row_h = max(10, (self.height - bar_h - 4) // max(1, self.rules))
        widest = max((value for _kind, value in top), default=0) or 1
        for index, (kind, count) in enumerate(top):
            y = bar_h + 3 + index * row_h
            canvas.create_text(0, y + row_h / 2, text=_clip(kind, 20), anchor="w",
                               fill=STATIC, font=(FONTS["mono"], _SMALL))
            bar_left = 132
            span = max(1, width - bar_left - 26)
            canvas.create_rectangle(
                bar_left, y + 1, bar_left + span * (count / widest), y + row_h - 2,
                fill=WARN, outline="",
            )
            canvas.create_text(width - 1, y + row_h / 2, text=str(count), anchor="e",
                               fill=VALUE, font=(FONTS["mono"], _SMALL))


class ActionBars:
    """Frequency of each applied movement and of each action (fire/use/neither)."""

    def __init__(self, tkinter, parent, *, height=64, rows=6):
        self.height = int(height)
        self.rows = int(rows)
        self.caption = _caption(tkinter, parent, width=38)
        self.canvas = tkinter.Canvas(
            parent, width=220, height=self.height, bg=BG, highlightthickness=0, bd=0
        )
        self.canvas.pack(fill="x")
        self._sig = None

    def render(self, movements, interactions):
        def top(counter):
            return tuple(
                sorted(counter.items(), key=lambda item: (-item[1], item[0]))[: self.rows]
            )

        mov = top(movements)
        act = top(interactions)
        width = self.canvas.winfo_width() or 240
        signature = (mov, act, width)
        if signature == self._sig:
            return
        self._sig = signature
        canvas = self.canvas
        canvas.delete("all")
        _set_caption(self.caption, "DISTRIBUCIÓN DE ACCIONES   aplicadas")
        half = width / 2
        for origin, (title, items) in enumerate((("MOV", mov), ("ACC", act))):
            x = origin * half
            canvas.create_text(x, 0, text=title, anchor="nw", fill=TITLE,
                               font=(FONTS["mono"], _SMALL, "bold"))
            if not items:
                continue
            widest = max(value for _name, value in items) or 1
            row_h = max(9, (self.height - 12) // max(1, self.rows))
            for index, (name, count) in enumerate(items):
                y = 12 + index * row_h
                canvas.create_text(x, y, text=_clip(name, 12), anchor="nw",
                                   fill=STATIC, font=(FONTS["mono"], _SMALL))
                bar_left = x + 76
                span = max(1, half - 76 - 20)
                canvas.create_rectangle(
                    bar_left, y + 1, bar_left + span * (count / widest), y + row_h - 2,
                    fill=VALUE, outline="",
                )
                canvas.create_text(x + half - 18, y, text=str(count), anchor="nw",
                                   fill=STATIC, font=(FONTS["mono"], _SMALL))


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


class PolicyDelta:
    """What changed between the previous decision and this one, on one line."""

    def __init__(self, tkinter, parent, *, width=24):
        self.caption = _caption(tkinter, parent, width=22)
        self.value = tkinter.Label(
            parent, text="", width=width, anchor="w", justify="left", bg=PANEL,
            fg=VALUE, font=(FONTS["mono"], _SMALL),
        )
        self.value.pack(fill="x")
        self._last = None

    def render(self, previous, current):
        if previous is None or current is None:
            text, fg = "sin referencia todavía", OFF
        else:
            changed = False
            lines = []
            for label, before, after in (
                ("MOV", previous.movement, current.movement),
                ("APU", previous.aim, current.aim),
                ("ACC", previous.interaction, current.interaction),
            ):
                if before != after:
                    changed = True
                    lines.append(f"{label} {before}→{after}")
                else:
                    lines.append(f"{label} = {before}")
            text = "\n".join(lines)
            fg = WARN if changed else STATIC
        signature = (text, fg)
        if signature == self._last:
            return
        self._last = signature
        try:
            width = int(self.value.cget("width"))
        except Exception:  # pragma: no cover - defensive
            width = 0
        if width:
            text = "\n".join(_clip(line, width) for line in text.split("\n"))
        self.value.configure(text=text, fg=fg)
