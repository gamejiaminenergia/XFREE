"""The two frequency bars: guard interventions and the applied actions."""

from __future__ import annotations

from ..theme import BG, FONTS, STATIC, TITLE, TRACK, VALUE, WARN
from .canvas import _SMALL, _caption, _clip, _set_caption


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
