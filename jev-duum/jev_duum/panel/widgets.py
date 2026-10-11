"""The primitive HMI widgets: a titled box, a state flag, a bargraph and the
typed-question row, plus the fixed-width table and read-only text helpers.

Every widget owns a fixed width or a fixed height: nothing here grows with
its data, the invariant ``tests/test_jev_hmi.py`` enforces."""

from __future__ import annotations

from ..theme import (
    ALARM,
    BG,
    FONTS,
    INFO,
    OFF,
    PANEL,
    RULE,
    STATIC,
    TITLE,
    TRACK,
    VALUE,
    WARN,
)
from .format import (
    _clip,
    _confidence_level,
    _threshold_color,
)


class Panel:
    """A titled box: heading row, one hairline, body.  No accent, no shadow."""

    def __init__(self, tkinter, parent, title, *, pady=0, expand=False, manage=True):
        self.tk = tkinter
        self.frame = tkinter.Frame(
            parent, bg=PANEL, highlightbackground=RULE, highlightthickness=1
        )
        if manage:
            self.frame.pack(fill="both" if expand else "x", expand=expand, pady=pady)
        head = tkinter.Frame(self.frame, bg=PANEL)
        head.pack(fill="x", padx=8, pady=(5, 0))
        self.header = head
        # Grid, not pack: the heading's cell takes the slack (weight 1) and the
        # state block's cell keeps its exact request.  Packed side by side, a
        # longer heading squeezed the block and the block's width followed the
        # data, which is exactly what the fixed widths everywhere else prevent.
        head.grid_columnconfigure(0, weight=1)
        self.title = tkinter.Label(
            head, text=title.upper(), bg=PANEL, fg=TITLE,
            font=(FONTS["mono"], 10, "bold"), anchor="w",
        )
        self.title.grid(row=0, column=0, sticky="ew")
        self.flag_holder = tkinter.Frame(head, bg=PANEL)
        # Column 1 is where a panel may place a middle note; the state
        # block always lives in the last column.
        self.flag_holder.grid(row=0, column=2, sticky="e")
        tkinter.Frame(self.frame, bg=RULE, height=1).pack(fill="x", padx=8, pady=(4, 0))
        self.body = tkinter.Frame(self.frame, bg=PANEL)
        self.body.pack(fill="both", expand=expand, padx=8, pady=(5, 7))

    def set_title(self, text):
        if self.title.cget("text") != text.upper():
            self.title.configure(text=text.upper())

    def set_height(self, pixels):
        """Pin the box to an exact height.

        A section is a fixed piece of the screen: if its height followed its
        content, every panel below it would move on every refresh and the
        operator would have to re-find everything.  What does not fit in the
        box is clipped, and the event list is where the full history lives.
        """

        pixels = int(pixels)
        if pixels == getattr(self, "_height", None):
            return
        self._height = pixels
        self.frame.configure(height=pixels)
        self.frame.pack_propagate(False)
        self.frame.grid_propagate(False)

class Flag:
    """A flat block carrying one word, filled only when something is wrong.

    ISA-101 in one widget: a normal state is grey text on the panel, a
    deviation gets the amber fill, an alarm the red one.  A screen where every
    state is a bright block is a screen where none of them stands out.
    """

    LEVELS = {
        "ok": (STATIC, PANEL),      # in service, normal, applied as proposed
        "off": (OFF, PANEL),        # out of service / no data / not scanned
        "warn": (BG, WARN),         # above a limit, stale, guard intervention
        "alarm": (BG, ALARM),       # no link, critical, low confidence
    }

    def __init__(self, tkinter, parent, *, width=None):
        self.label = tkinter.Label(
            parent, text="", bg=PANEL, fg=STATIC, font=(FONTS["mono"], 9, "bold"),
            padx=6, pady=1, width=width,
        )
        self._last = None

    def level(self, text, level):
        fg, bg = self.LEVELS.get(level, self.LEVELS["off"])
        key = (text, fg, bg)
        if key == self._last:
            return
        self._last = key
        self.label.configure(text=text, fg=fg, bg=bg)

class Bar:
    """An operator bargraph: tag, bar, value and unit on one line."""

    def __init__(self, tkinter, parent, tag, *, unit="", height=12):
        self.height = height
        self.unit = unit
        self.frame = tkinter.Frame(parent, bg=PANEL)
        self.frame.pack(fill="x", pady=2)
        tkinter.Label(
            self.frame, text=tag, width=10, anchor="w", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 10),
        ).pack(side="left")
        self.canvas = tkinter.Canvas(
            self.frame, height=height, bg=TRACK, highlightthickness=0
        )
        self.canvas.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.fill = self.canvas.create_rectangle(0, 0, 0, height, fill=VALUE, outline="")
        self.limit = self.canvas.create_line(0, 0, 0, height, fill=STATIC)
        self.value = tkinter.Label(
            self.frame, text="—", width=11, anchor="e", bg=PANEL, fg=VALUE,
            font=(FONTS["mono"], 11, "bold"),
        )
        self.value.pack(side="left")
        self._last = None

    def set(self, value, maximum, text=None, *, warn_at=None, crit_at=None):
        fraction = 0.0 if maximum <= 0 else min(1.0, max(0.0, value / maximum))
        color = _threshold_color(VALUE, value, warn_at, crit_at)
        display = str(value) if text is None else str(text)
        canvas = self.canvas
        width = canvas.winfo_width()
        if width <= 1:
            width = 200
        limit = 0.0 if not warn_at or maximum <= 0 else min(1.0, warn_at / maximum)
        key = (width, round(fraction, 4), round(limit, 4), color, display)
        if key == self._last:
            return
        self._last = key
        canvas.coords(self.fill, 0, 0, width * fraction, self.height)
        canvas.itemconfigure(self.fill, fill=color)
        if limit > 0:
            canvas.coords(self.limit, width * limit, 0, width * limit, self.height)
            canvas.itemconfigure(self.limit, fill=INFO if color == VALUE else color)
        else:
            canvas.itemconfigure(self.limit, fill=TRACK)
        suffix = f" {self.unit}" if self.unit else ""
        self.value.configure(text=f"{display}{suffix}", fg=color)

    def refresh(self):
        self._last = None

class DecidRow:
    """One typed question: the chosen answer, its distribution, its confidence.

    The distribution gets exactly one home.  It used to be drawn twice — a big
    hero bar here and a stack of rows behind a tab — which cost attention and
    put the alternatives out of sight.
    """

    def __init__(self, tkinter, parent, tag, title):
        self.tag = tag
        self.frame = tkinter.Frame(parent, bg=PANEL)
        head = tkinter.Frame(self.frame, bg=PANEL)
        head.pack(fill="x")
        tkinter.Label(
            head, text=tag, width=5, anchor="w", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 10, "bold"),
        ).pack(side="left")
        self.title = tkinter.Label(
            head, text=title, width=11, anchor="w", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 9),
        )
        self.title.pack(side="left")
        # Fixed width: the biggest word on screen must not resize its box when
        # the model changes its mind between `right` and `strafe_right`.
        self.choice = tkinter.Label(
            head, text="—", width=13, anchor="w", bg=PANEL, fg=VALUE,
            font=(FONTS["mono"], 20, "bold"),
        )
        self.choice.pack(side="left", padx=(4, 0))
        self.conf = Flag(tkinter, head, width=10)
        self.conf.label.pack(side="right")
        self.canvas = tkinter.Canvas(
            self.frame, height=20, bg=TRACK, highlightthickness=0, bd=0
        )
        self.canvas.pack(fill="x", pady=(3, 2))
        self.canvas.bind("<Configure>", self._on_configure)
        self.breakdown = tkinter.Label(
            self.frame, text="", width=44, anchor="w", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 9),
        )
        self.breakdown.pack(fill="x")
        self._values: dict = {}
        self._confidence = None
        self._muted = False
        self._drawn = 0

    def _on_configure(self, event):
        if abs(event.width - self._drawn) > 1:
            self._draw()

    def set(self, distribution, confidence, *, muted=False):
        self._values = dict(distribution or {})
        self._confidence = confidence
        self._muted = bool(muted)
        if not self._values:
            self.reset()
            return
        best = max(self._values, key=self._values.__getitem__)
        self.choice.configure(text=best.upper().replace("_", " "), fg=OFF if muted else VALUE)
        if muted:
            self.conf.level("SIN DATO", "off")
        else:
            word, level = _confidence_level(confidence)
            self.conf.level(
                f"{word} {confidence:.2f}" if confidence is not None else word, level
            )
        others = "  ".join(
            f"{name} {value:.2f}" for name, value in self._values.items() if name != best
        )
        self.breakdown.configure(
            text=_clip(f"ALTERNATIVAS   {others}", 44) if others else ""
        )
        self._draw()

    def reset(self):
        self._values = {}
        self.choice.configure(text="—", fg=OFF)
        self.conf.level("SIN DATO", "off")
        self.canvas.delete("all")
        self.breakdown.configure(text="")

    def refresh(self):
        self._drawn = 0
        self._draw()

    def _draw(self):
        canvas = self.canvas
        canvas.delete("all")
        values = self._values
        width = canvas.winfo_width()
        if not values or width <= 1:
            return
        self._drawn = width
        best = max(values, key=values.__getitem__)
        total = sum(max(0.0, float(value)) for value in values.values())
        x = 0.0
        for name, value in values.items():
            segment = width * max(0.0, float(value))
            # The chosen option is a bright block, the rest a mid grey: the
            # distribution is legible without colour carrying the meaning.
            fill = OFF if name != best else (OFF if self._muted else VALUE)
            canvas.create_rectangle(x, 0, x + segment, 20, fill=fill, outline=BG)
            if segment >= 44:
                canvas.create_text(
                    x + segment / 2, 10, text=f"{value:.2f}",
                    fill=BG if name == best and not self._muted else VALUE,
                    font=(FONTS["mono"], 9, "bold"),
                )
            x += segment
        if x < width - 1:
            canvas.create_rectangle(x, 0, width, 20, fill=TRACK, outline=BG)
            if width - x >= 44 and total < 0.995:
                canvas.create_text(
                    x + (width - x) / 2, 10, text=f"{1.0 - total:.2f}", fill=STATIC,
                    font=(FONTS["mono"], 9),
                )
        # The 50% reference, cut into the bar in screen black: it has to read
        # both against the bright winner block and against the grey remainder.
        canvas.create_line(width / 2, 0, width / 2, 20, fill=BG)

def _table(tkinter, parent, rows, *, keys=STATIC, size=10, pairs=1, value_width=None):
    """A TAG/value table; returns the labels by key.

    With ``pairs=2`` the rows are laid out in two side-by-side blocks, which
    halves the height of a six-row table without losing a field.
    """

    body = tkinter.Frame(parent, bg=PANEL)
    body.pack(fill="x")
    widgets = {}
    per_block = (len(rows) + pairs - 1) // pairs
    for index, (key, label) in enumerate(rows):
        block, line = divmod(index, per_block)
        key_column = block * 2
        tkinter.Label(
            body, text=str(key), anchor="w", bg=PANEL, fg=keys,
            font=(FONTS["mono"], size),
        ).grid(row=line, column=key_column, sticky="w", padx=(0 if block == 0 else 14, 6))
        value = tkinter.Label(
            body, text="—", anchor="w", bg=PANEL, fg=VALUE, font=(FONTS["mono"], size),
            width=value_width or 0,
        )
        value.grid(row=line, column=key_column + 1, sticky="w")
        widgets[label] = value
        if block == 0:
            body.grid_columnconfigure(1, weight=1)
    return body, widgets

def _plain_text(tkinter, parent, *, height, wrap="word", size=9, width=40):
    """Read-only text with no scrollbar: nothing here is meant to be scrolled."""

    return tkinter.Text(
        parent, height=height, width=width, wrap=wrap, bg=BG, fg=STATIC, relief="flat",
        font=(FONTS["mono"], size), padx=6, pady=4, insertbackground=STATIC,
        selectbackground=RULE, highlightthickness=0, state="disabled",
    )
