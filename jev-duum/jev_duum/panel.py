"""Tk gameplay loop and the live Jev decision inspector.

The window keeps Duum's own canvas untouched in the middle and answers two
questions on the sides: on the left, how the agent is doing; on the right, what
the model was asked and what it answered.  The right column is a small tabbed
inspector so the request, the response and the schematic world each get their
own space instead of sharing one running ``Text`` log.

Everything here is presentation.  The loop still calls ``panel.update`` every
few ticks; the panel remembers the last value it drew per widget and only
touches what actually changed, which removes the per-refresh flicker without
touching the 60 Hz loop or the decision worker.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import replace

from .actions import controls_to_mask, ensure_usable_weapon, settle_assisted_controls
from .overlays import MiniMap, StaleOverlay
from .snapshot import SnapshotBuilder
from .types import AIMS, INTERACTIONS, MOVEMENTS, DuumControls
from .worker import DecisionWorker
from .world_readout import read_world

# ── palette ──────────────────────────────────────────────────────────────────
BG = "#0b0d12"
PANEL = "#141823"
PANEL2 = "#10131b"
CARD = "#1a2030"
BG2 = "#0d1017"
BORDER = "#2a3244"
TRACK = "#232c3d"
INERT = "#39435a"
TEXT = "#e8ecf4"
MUTED = "#8b93a7"
ACCENT = "#65d8ff"
GREEN = "#8ee8a8"
AMBER = "#ffb74d"
RED = "#ef5350"
GOLD = "#ffca28"
BLUE = "#42a5f5"
VIOLET = "#b388ff"

FONTS = {"mono": "DejaVu Sans Mono", "ui": "DejaVu Sans"}

_KEY_RE = re.compile(r'^(\s*)("(?:[^"\\]|\\.)*")(\s*:.*)$')
_LITERAL_RE = re.compile(
    r'(?<![\w"])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|\btrue\b|\bfalse\b|\bnull\b'
)


def _pick_families(tkinter):
    try:
        from tkinter import font as tkfont

        families = set(tkfont.families())
    except Exception:  # pragma: no cover - headless fallback
        families = set()

    def pick(*candidates):
        for candidate in candidates:
            if candidate in families:
                return candidate
        return candidates[-1]

    mono = pick("Menlo", "DejaVu Sans Mono", "Noto Mono", "Courier")
    ui = pick("Menlo", "DejaVu Sans", "Noto Sans", "Helvetica")
    return mono, ui


def _percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def _threshold_color(base, value, warn_at, crit_at, phase):
    """Green → amber → red for a meter; critical values blink with ``phase``."""

    if crit_at is not None and value <= crit_at:
        return RED if phase else "#7a2020"
    if warn_at is not None and value <= warn_at:
        return AMBER
    return base


class DeltaCache:
    """Remember the last value drawn per key and report only real changes.

    The panel asks this before touching any widget, which is what removes the
    per-refresh flicker: a refresh that did not change a field is a no-op.
    """

    def __init__(self):
        self._values: dict = {}

    def changed(self, key, value) -> bool:
        if key in self._values and self._values[key] == value:
            return False
        self._values[key] = value
        return True

    def reset(self, key) -> None:
        self._values.pop(key, None)


def advance_completed_level(app) -> bool:
    """Advance Duum's intermission through the same public Space key as a player."""

    if app.finish is None:
        return False
    app.key(32, 0, False)
    return True


# ── small widgets ────────────────────────────────────────────────────────────


class Meter:
    """A labelled bar whose colour follows a warning / critical threshold."""

    def __init__(self, tkinter, parent, label, color, *, width=200, height=11):
        self.width = width
        self.height = height
        self.base = color
        self.frame = tkinter.Frame(parent, bg=PANEL)
        self.frame.pack(fill="x", padx=16, pady=(5, 3))
        head = tkinter.Frame(self.frame, bg=PANEL)
        head.pack(fill="x")
        tkinter.Label(
            head, text=label.upper(), bg=PANEL, fg=MUTED, font=(FONTS["mono"], 9, "bold")
        ).pack(side="left")
        self.value = tkinter.Label(
            head, text="0", bg=PANEL, fg=TEXT, font=(FONTS["mono"], 12, "bold")
        )
        self.value.pack(side="right")
        self.canvas = tkinter.Canvas(
            self.frame, width=width, height=height, bg=TRACK, highlightthickness=0
        )
        self.canvas.pack(fill="x")
        self.fill = self.canvas.create_rectangle(0, 0, 0, height, fill=color, outline="")
        self._last = None

    def set(self, value, maximum, text=None, *, warn_at=None, crit_at=None, phase=0):
        fraction = 0.0 if maximum <= 0 else min(1.0, max(0.0, value / maximum))
        color = _threshold_color(self.base, value, warn_at, crit_at, phase)
        display = str(value) if text is None else str(text)
        key = (round(fraction, 4), color, display)
        if key == self._last:
            return
        self._last = key
        self.canvas.coords(self.fill, 0, 0, self.width * fraction, self.height)
        self.canvas.itemconfigure(self.fill, fill=color)
        self.value.configure(text=display, fg=color)


class BarRow:
    """One labelled probability bar; the argmax row is highlighted."""

    def __init__(self, tkinter, parent, label, *, width=150, height=11, best_color=GREEN):
        self.width = width
        self.height = height
        self.best_color = best_color
        self.row = tkinter.Frame(parent, bg=CARD)
        self.row.pack(fill="x", pady=1)
        self.label = tkinter.Label(
            self.row, text=label, width=13, anchor="w", bg=CARD, fg=MUTED,
            font=(FONTS["mono"], 9),
        )
        self.label.pack(side="left")
        self.canvas = tkinter.Canvas(
            self.row, width=width, height=height, bg=TRACK, highlightthickness=0
        )
        self.canvas.pack(side="left", padx=(0, 8))
        self.fill = self.canvas.create_rectangle(0, 0, 0, height, fill=INERT, outline="")
        self.value = tkinter.Label(
            self.row, text="—", width=5, anchor="e", bg=CARD, fg=TEXT,
            font=(FONTS["mono"], 9),
        )
        self.value.pack(side="left")
        self._last = None

    def set(self, value, *, best=False):
        key = (round(float(value), 3), bool(best))
        if key == self._last:
            return
        self._last = key
        self.canvas.coords(
            self.fill, 0, 0, self.width * max(0.0, min(1.0, value)), self.height
        )
        self.canvas.itemconfigure(self.fill, fill=self.best_color if best else INERT)
        self.value.configure(text=f"{value:.2f}", fg=self.best_color if best else TEXT)
        self.label.configure(
            fg=self.best_color if best else MUTED,
            font=(FONTS["mono"], 9, "bold") if best else (FONTS["mono"], 9),
        )


class Pill:
    """A tiny label for a single compact value."""

    def __init__(self, tkinter, parent, *, bg=CARD, width=None):
        self.label = tkinter.Label(
            parent, text="—", bg=bg, fg=TEXT, font=(FONTS["mono"], 9, "bold"),
            padx=7, pady=2, width=width,
        )
        self._last = None

    def set(self, text, *, fg=TEXT, bg=None):
        key = (text, fg, bg)
        if key == self._last:
            return
        self._last = key
        options = {"text": text, "fg": fg}
        if bg is not None:
            options["bg"] = bg
        self.label.configure(**options)


class Card:
    """A titled container so the inspector reads as sections, not a log."""

    def __init__(self, tkinter, parent, title, *, accent=ACCENT, pady=(0, 8), expand=False):
        self.frame = tkinter.Frame(
            parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1
        )
        self.frame.pack(fill="both" if expand else "x", expand=expand, pady=pady)
        header = tkinter.Frame(self.frame, bg=CARD)
        header.pack(fill="x", padx=10, pady=(8, 2))
        tkinter.Frame(header, width=3, height=13, bg=accent).pack(side="left")
        tkinter.Label(
            header, text=title.upper(), bg=CARD, fg=accent,
            font=(FONTS["mono"], 10, "bold"),
        ).pack(side="left", padx=(7, 0))
        self.body = tkinter.Frame(self.frame, bg=CARD)
        self.body.pack(fill="both", expand=expand, padx=10, pady=(2, 10))


def _field_row(tkinter, parent, key, *, width=15):
    row = tkinter.Frame(parent, bg=CARD)
    row.pack(fill="x", pady=1)
    tkinter.Label(
        row, text=key, width=width, anchor="w", bg=CARD, fg=MUTED,
        font=(FONTS["mono"], 9),
    ).pack(side="left")
    value = tkinter.Label(
        row, text="—", anchor="w", bg=CARD, fg=TEXT, font=(FONTS["mono"], 9)
    )
    value.pack(side="left", fill="x", expand=True)
    return value


def _scrolling_text(tkinter, parent, *, height, wrap="word", size=9):
    frame = tkinter.Frame(parent, bg=CARD)
    text = tkinter.Text(
        frame, height=height, wrap=wrap, bg=BG2, fg=TEXT, relief="flat",
        font=(FONTS["mono"], size), padx=8, pady=6, insertbackground=TEXT,
        selectbackground="#2b3546", highlightthickness=0, state="disabled",
    )
    bar = tkinter.Scrollbar(
        frame, command=text.yview, bg=CARD, troughcolor=BG2,
        activebackground=BORDER, relief="flat", width=10,
    )
    text.configure(yscrollcommand=bar.set)
    text.bind("<MouseWheel>", lambda event: text.yview_scroll(-1 if event.delta > 0 else 1, "units"))
    text.bind("<Button-4>", lambda _event: text.yview_scroll(-1, "units"))
    text.bind("<Button-5>", lambda _event: text.yview_scroll(1, "units"))
    text.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    return frame, text


class ScrollFrame:
    """A vertically scrollable container so a busy tab never clips its cards."""

    def __init__(self, tkinter, parent, *, bg=PANEL2):
        self.tk = tkinter
        self.outer = tkinter.Frame(parent, bg=bg)
        self.canvas = tkinter.Canvas(self.outer, bg=bg, highlightthickness=0, bd=0)
        self.bar = tkinter.Scrollbar(
            self.outer, orient="vertical", command=self.canvas.yview, bg=CARD,
            troughcolor=bg, activebackground=BORDER, relief="flat", width=10,
        )
        self.inner = tkinter.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", self._resize)
        self.canvas.bind("<Configure>", self._fit)
        self.canvas.bind_all("<Button-4>", self._wheel)
        self.canvas.bind_all("<Button-5>", self._wheel)
        self.canvas.bind_all("<MouseWheel>", self._wheel)

    def _resize(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._toggle_bar()

    def _fit(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)
        self._toggle_bar()

    def _toggle_bar(self):
        needed = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 1
        if needed and not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y")
        elif not needed and self.bar.winfo_ismapped():
            self.bar.pack_forget()

    def _wheel(self, event):
        try:
            if not self.canvas.winfo_exists():
                return
            widget = self.canvas.winfo_containing(event.x_root, event.y_root)
        except self.tk.TclError:  # pragma: no cover - window already gone
            return
        node = widget
        while node is not None and node is not self.canvas:
            if isinstance(node, self.tk.Text):
                return  # an inner text keeps the wheel for its own scroll
            node = getattr(node, "master", None)
        if node is not self.canvas:
            return
        if getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            step = -1 if getattr(event, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(step, "units")


def _insert_json_line(text, line):
    match = _KEY_RE.match(line)
    if match:
        text.insert("end", match.group(1))
        text.insert("end", match.group(2), "key")
        line = match.group(3)
    position = 0
    for match in _LITERAL_RE.finditer(line):
        if match.start() > position:
            text.insert("end", line[position : match.start()])
        token = match.group(0)
        text.insert("end", token, "num" if token[0] in "-0123456789" else "const")
        position = match.end()
    text.insert("end", line[position:] + "\n")


def _questions_text(questions) -> str:
    if not questions:
        return "—"
    lines = []
    for name, question in questions.items():
        lines.append(f"{name.upper()}  [{question.get('type', 'choice')}]")
        if question.get("instructions"):
            lines.append(f"  {question['instructions']}")
        criteria = question.get("criteria") or {}
        if criteria:
            lines.append("  " + "   ".join(f"{key} = {value}" for key, value in criteria.items()))
        lines.append("")
    return "\n".join(lines).strip()


class Dashboard:
    """One-window layout: stats left, untouched game center, Jev inspector right."""

    def __init__(self, tkinter, window):
        FONTS["mono"], FONTS["ui"] = _pick_families(tkinter)
        self.tk = tkinter
        self.cache = DeltaCache()
        self._latencies: list[float] = []
        self._cost = 0.0
        self._tokens = 0
        self._decisions = 0
        self._counted = None
        self._assist_sig = None
        self._strategy_sig = None

        root = window.root
        root.configure(bg=BG)
        root.resizable(True, True)
        window.tkcv.pack_forget()

        self.left = tkinter.Frame(root, width=252, bg=PANEL)
        self.left.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.left.pack_propagate(False)

        self.right = tkinter.Frame(root, width=528, bg=PANEL2)
        self.right.grid(row=0, column=2, rowspan=3, sticky="nsew")
        self.right.pack_propagate(False)
        root.grid_rowconfigure(1, weight=1)
        root.grid_columnconfigure(1, weight=1)

        self._build_left()
        self._build_center(window)
        self._build_right()

    # -- helpers -------------------------------------------------------------
    def _label(self, key, widget, text, **options):
        state = (text, tuple(sorted(options.items())))
        if not self.cache.changed(key, state):
            return
        widget.configure(text=text, **options)

    def _render_json(self, key, widget, payload):
        try:
            signature = json.dumps(payload, sort_keys=True, default=str)
        except (TypeError, ValueError):
            signature = repr(payload)
        if not self.cache.changed(key, signature):
            return
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.tag_configure("key", foreground=ACCENT)
        widget.tag_configure("num", foreground=GOLD)
        widget.tag_configure("const", foreground=VIOLET)
        if payload is None:
            widget.insert("end", "—")
        else:
            try:
                source = json.dumps(payload, indent=2, ensure_ascii=False)
            except (TypeError, ValueError):
                source = str(payload)
            for line in source.splitlines():
                _insert_json_line(widget, line)
        widget.configure(state="disabled")

    def _render_text(self, key, widget, content):
        if not self.cache.changed(key, content):
            return
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    # -- left column ---------------------------------------------------------
    def _build_left(self):
        tk = self.tk
        tk.Label(
            self.left, text="DUUM", bg=PANEL, fg=ACCENT, font=(FONTS["mono"], 22, "bold")
        ).pack(anchor="w", padx=16, pady=(18, 0))
        tk.Label(
            self.left, text="Jev local pilot", bg=PANEL, fg=MUTED, font=(FONTS["mono"], 9)
        ).pack(anchor="w", padx=16, pady=(0, 14))

        self.banner = tk.Label(
            self.left, text="", bg=PANEL, fg=TEXT, font=(FONTS["mono"], 10, "bold"),
            wraplength=220, justify="left", anchor="w", padx=10, pady=6,
        )
        self.banner.pack(side="bottom", fill="x", padx=12, pady=12)

        self.health = Meter(tk, self.left, "Health", GREEN)
        self.armor = Meter(tk, self.left, "Armor", BLUE)
        self.ammo = Meter(tk, self.left, "Ammo", GOLD)

        card = Card(tk, self.left, "Estado", accent=ACCENT)
        self.stats = tk.Label(
            card.body, text="", justify="left", anchor="nw", bg=CARD, fg=TEXT,
            font=(FONTS["mono"], 10),
        )
        self.stats.pack(fill="x")

        card = Card(tk, self.left, "Sesión", accent=GREEN)
        self.status = tk.Label(
            card.body, text="", justify="left", anchor="nw", bg=CARD, fg=MUTED,
            font=(FONTS["mono"], 9), wraplength=212,
        )
        self.status.pack(fill="x")

    # -- center column -------------------------------------------------------
    def _build_center(self, window):
        tk = self.tk
        root = window.root
        header = tk.Frame(root, bg=BG)
        header.grid(row=0, column=1, sticky="ew", padx=12, pady=(10, 6))
        self.map_label = tk.Label(
            header, text="DUUM", bg=BG, fg=ACCENT, font=(FONTS["mono"], 13, "bold")
        )
        self.map_label.pack(side="left")
        self.live_label = tk.Label(header, text="", bg=BG, fg=MUTED, font=(FONTS["mono"], 9))
        self.live_label.pack(side="right")

        window.tkcv.configure(
            highlightthickness=2,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            bg="black",
        )
        window.tkcv.grid(row=1, column=1)
        self.stale_overlay = StaleOverlay(tk, window.tkcv)

        bottom = tk.Frame(root, bg=BG)
        bottom.grid(row=2, column=1, sticky="nsew", padx=12, pady=(6, 10))
        card = Card(tk, bottom, "Automapa · riesgo sectorial", accent=VIOLET)
        self.minimap = MiniMap(tk, card.body, width=336, height=214)
        self.minimap.canvas.pack(anchor="center")

    # -- right column --------------------------------------------------------
    def _build_right(self):
        tk = self.tk
        header = tk.Frame(self.right, bg=PANEL2)
        header.pack(fill="x", padx=16, pady=(14, 0))
        tk.Label(
            header, text="INSPECTOR JEV", bg=PANEL2, fg=GREEN,
            font=(FONTS["mono"], 15, "bold"),
        ).pack(anchor="w")
        self.mode = tk.Label(
            header, text="", bg=PANEL2, fg=MUTED, font=(FONTS["mono"], 8), justify="left"
        )
        self.mode.pack(anchor="w", pady=(2, 0))

        strip = tk.Frame(self.right, bg=PANEL2)
        strip.pack(fill="x", padx=16, pady=(10, 8))
        self._tiles = {}
        for column, (key, caption) in enumerate(
            (("decisions", "DECISIONES"), ("p50", "p50 ms"), ("p95", "p95 ms"), ("cost", "COSTO"))
        ):
            cell = tk.Frame(strip, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
            cell.grid(row=0, column=column, sticky="nsew", padx=(0, 6))
            strip.grid_columnconfigure(column, weight=1)
            value = tk.Label(cell, text="—", bg=CARD, fg=TEXT, font=(FONTS["mono"], 13, "bold"))
            value.pack(anchor="w", padx=8, pady=(6, 0))
            tk.Label(cell, text=caption, bg=CARD, fg=MUTED, font=(FONTS["mono"], 7)).pack(
                anchor="w", padx=8, pady=(0, 6)
            )
            self._tiles[key] = value

        tabbar = tk.Frame(self.right, bg=PANEL2)
        tabbar.pack(fill="x", padx=16)
        self.scroll = ScrollFrame(tk, self.right, bg=PANEL2)
        self.scroll.outer.pack(fill="both", expand=True, padx=(16, 8), pady=(6, 12))
        self.content = self.scroll.inner
        self.tabs = {}
        for name, label, builder in (
            ("decision", "DECISIÓN", self._tab_decision),
            ("response", "RESPUESTA", self._tab_response),
            ("request", "PETICIÓN", self._tab_request),
            ("world", "MUNDO", self._tab_world),
        ):
            button = tk.Label(
                tabbar, text=label, bg=PANEL2, fg=MUTED, font=(FONTS["mono"], 9, "bold"),
                padx=10, pady=6, cursor="hand2",
            )
            button.pack(side="left")
            button.bind("<Button-1>", lambda _event, name=name: self._select_tab(name))
            frame = tk.Frame(self.content, bg=PANEL2)
            builder(frame)
            self.tabs[name] = (button, frame)
        self._select_tab("decision")

    def _select_tab(self, name):
        for key, (button, frame) in self.tabs.items():
            if key == name:
                button.configure(fg=ACCENT, bg=CARD)
                frame.pack(fill="both", expand=True)
            else:
                button.configure(fg=MUTED, bg=PANEL2)
                frame.pack_forget()

    # -- tabs ----------------------------------------------------------------
    def _tab_decision(self, parent):
        tk = self.tk
        card = Card(tk, parent, "Control propuesto vs aplicado", accent=GREEN)
        for caption, store in (("PROPUESTO", "prop"), ("APLICADO", "appl")):
            row = tk.Frame(card.body, bg=CARD)
            row.pack(fill="x", pady=2)
            tk.Label(
                row, text=caption, width=10, anchor="w", bg=CARD, fg=MUTED,
                font=(FONTS["mono"], 9),
            ).pack(side="left")
            pills = {}
            for axis in ("movement", "aim", "interaction"):
                pill = Pill(tk, row)
                pill.label.pack(side="left", padx=(0, 6))
                pills[axis] = pill
            setattr(self, store, pills)

        card = Card(tk, parent, "Intervenciones del guardia", accent=AMBER)
        self.assist_body = tk.Frame(card.body, bg=CARD)
        self.assist_body.pack(fill="x")

        card = Card(tk, parent, "Estrategia", accent=ACCENT)
        self.strategy_head = tk.Label(
            card.body, text="—", anchor="w", justify="left", bg=CARD, fg=TEXT,
            font=(FONTS["mono"], 9), wraplength=470,
        )
        self.strategy_head.pack(fill="x")
        self.strategy_plan = tk.Frame(card.body, bg=CARD)
        self.strategy_plan.pack(fill="x", pady=(4, 0))

        card = Card(tk, parent, "Lectura de observaciones", accent=BLUE)
        self.observations = {}
        for axis in ("movement", "aim", "interaction"):
            tk.Label(
                card.body, text=axis.upper(), anchor="w", bg=CARD, fg=MUTED,
                font=(FONTS["mono"], 8, "bold"),
            ).pack(fill="x", pady=(4, 0))
            value = tk.Label(
                card.body, text="—", anchor="w", justify="left", bg=CARD, fg=TEXT,
                font=(FONTS["mono"], 8), wraplength=470,
            )
            value.pack(fill="x")
            self.observations[axis] = value

    def _tab_response(self, parent):
        tk = self.tk
        card = Card(tk, parent, "Respuesta del modelo", accent=GREEN)
        self.response_fields = {}
        for key, label in (
            ("model", "modelo"), ("prompt", "prompt"), ("tokens", "tokens"),
            ("cost", "costo"), ("request", "request"), ("decision", "decisión"),
            ("age", "edad"), ("exec", "llamadas"), ("log", "bitácora"),
        ):
            self.response_fields[key] = _field_row(tk, card.body, label)

        card = Card(tk, parent, "Distribuciones de probabilidad", accent=GOLD)
        self.bars = {}
        self.confidence = {}
        groups = (
            ("movement", "MOVEMENT", MOVEMENTS),
            ("aim", "AIM", AIMS),
            ("interaction", "INTERACTION", INTERACTIONS),
        )
        for index, (axis, title, labels) in enumerate(groups):
            head = tk.Frame(card.body, bg=CARD)
            head.pack(fill="x", pady=(0 if index == 0 else 8, 2))
            tk.Label(
                head, text=title, anchor="w", bg=CARD, fg=GOLD,
                font=(FONTS["mono"], 9, "bold"),
            ).pack(side="left")
            pill = Pill(tk, head)
            pill.label.pack(side="right")
            self.confidence[axis] = pill
            rows = {}
            for label in labels:
                rows[label] = BarRow(tk, card.body, label)
            self.bars[axis] = rows

    def _tab_request(self, parent):
        tk = self.tk
        card = Card(tk, parent, "Preguntas", accent=BLUE)
        frame, self.questions_text = _scrolling_text(tk, card.body, height=11, size=8)
        frame.pack(fill="x")

        card = Card(tk, parent, "Estado enviado a Jev", accent=VIOLET, expand=True)
        frame, self.state_text = _scrolling_text(tk, card.body, height=15, size=8)
        frame.pack(fill="both", expand=True)

    def _tab_world(self, parent):
        tk = self.tk
        card = Card(tk, parent, "Lectura heurística", accent=VIOLET)
        self.world_fields = {}
        for key, label in (
            ("room", "sala"), ("floor", "piso"), ("route", "ruta"),
            ("foes", "enemigos"), ("risk", "riesgo"), ("target", "objetivo"),
        ):
            self.world_fields[key] = _field_row(tk, card.body, label)

        card = Card(tk, parent, "Amenazas (top 3)", accent=RED)
        self.world_threats = tk.Label(
            card.body, text="—", anchor="w", justify="left", bg=CARD, fg=TEXT,
            font=(FONTS["mono"], 9), wraplength=470,
        )
        self.world_threats.pack(fill="x")

        card = Card(tk, parent, "Aspiraciones (top 3)", accent=GOLD)
        self.world_items = tk.Label(
            card.body, text="—", anchor="w", justify="left", bg=CARD, fg=TEXT,
            font=(FONTS["mono"], 9), wraplength=470,
        )
        self.world_items.pack(fill="x")

        self.world_note = tk.Label(
            parent, text="", anchor="w", justify="left", bg=PANEL2, fg=MUTED,
            font=(FONTS["mono"], 8), wraplength=470,
        )
        self.world_note.pack(fill="x", pady=(2, 0))

    # -- update --------------------------------------------------------------
    def update(self, *, pilot, snapshot, decision, controls, worker, stale, error, log_stats=None):
        phase = (snapshot.tick // 4) % 2
        player = snapshot.player
        self.health.set(player.health, 100, warn_at=70, crit_at=35, phase=phase)
        self.armor.set(player.armor, 200, warn_at=100, crit_at=40, phase=phase)
        ammo = player.ammo
        self.ammo.set(
            min(ammo, 100), 100, "∞" if ammo >= 999 else str(ammo), crit_at=10, phase=phase
        )
        episode = snapshot.episode
        self._label(
            "stats",
            self.stats,
            f"MAP      {snapshot.map_name}\n"
            f"TIME     {episode.game_time:6.1f}s\n"
            f"WEAPON   {player.weapon_name}\n"
            f"ENEMIES  {episode.live_enemies}\n"
            f"KILLS    {episode.kills}\n"
            f"ITEMS    {episode.items}\n"
            f"DAMAGE   {episode.damage_received}\n"
            f"SECTORS  {episode.unique_sectors}",
        )
        busy = "ocupado" if worker.busy else "libre"
        self._label(
            "status",
            self.status,
            f"TICK {snapshot.tick}  ·  T {episode.game_time:.1f}s\n"
            f"worker {busy}  ·  stale {stale}\n"
            f"hechas {worker.stats.completed}  ·  descartadas {worker.stats.replaced}",
        )
        self._update_banner(episode.finished, error)

        readout = None
        try:
            readout = read_world(snapshot)
        except Exception:  # pragma: no cover - readout is already fail-soft
            readout = None
        aim_assisted = bool(
            decision is not None
            and any(
                event.kind in ("aim-guidance", "fire-alignment")
                for event in decision.assistance_events
            )
        )
        self.minimap.render(snapshot, readout, aim_assisted=aim_assisted)
        self.stale_overlay.update(stale=stale, error=error)
        self._label("map", self.map_label, f"DUUM · {snapshot.map_name}")
        self._label(
            "live",
            self.live_label,
            f"tick {snapshot.tick}  ·  {episode.game_time:5.1f}s  ·  "
            f"{'fin' if episode.finished else 'muerto' if episode.dead else 'vivo'}",
        )

        prompt = getattr(decision, "prompt_version", None)
        self._label(
            "mode",
            self.mode,
            f"{pilot} · api.typesafe.ai · estado semántico, sin píxeles"
            + (f" · prompt {prompt}" if prompt else ""),
        )

        if decision is not None:
            self._account(decision)
        self._update_tiles()
        self._update_world(readout, decision)
        self._update_request(decision)
        if decision is None:
            self._update_warmup(error)
        else:
            self._update_decision(decision, snapshot)
            self._update_response(decision, snapshot, log_stats)

    # -- banner / tiles ------------------------------------------------------
    def _update_banner(self, finished, error):
        if finished:
            text, bg, fg = "NIVEL COMPLETADO · avanzando…", "#1d3b28", GREEN
        elif error:
            text, bg, fg = f"MODEL ERROR · {error}"[:220], "#3b1d1d", "#ffb4b4"
        else:
            text, bg, fg = "", PANEL, TEXT
        self._label("banner", self.banner, text, bg=bg, fg=fg)

    def _account(self, decision):
        token = (decision.observation_tick, decision.application_tick)
        if token == self._counted:
            return
        self._counted = token
        self._latencies.append(float(decision.decision_ms))
        self._cost += float(decision.cost_usd or 0.0)
        self._tokens += int((decision.input_tokens or {}).get("request", 0) or 0)
        self._decisions += 1

    def _update_tiles(self):
        p50 = _percentile(self._latencies, 0.50)
        p95 = _percentile(self._latencies, 0.95)
        tiles = {
            "decisions": str(self._decisions),
            "p50": f"{p50:.0f}" if p50 is not None else "—",
            "p95": f"{p95:.0f}" if p95 is not None else "—",
            "cost": f"${self._cost:.5f}",
        }
        for key, value in tiles.items():
            self._label(f"tile-{key}", self._tiles[key], value)

    # -- decision tab --------------------------------------------------------
    def _update_decision(self, decision, snapshot):
        proposed = decision.proposed_controls
        applied = decision.applied_controls
        for axis in ("movement", "aim", "interaction"):
            proposed_value = getattr(proposed, axis)
            applied_value = getattr(applied, axis)
            self.prop[axis].set(proposed_value, fg=TEXT, bg=CARD)
            changed = proposed_value != applied_value
            self.appl[axis].set(
                applied_value,
                fg="#10210f" if changed else TEXT,
                bg=AMBER if changed else CARD,
            )

        signature = tuple(
            (event.kind, event.proposed, event.applied) for event in decision.assistance_events
        )
        if signature != self._assist_sig:
            self._assist_sig = signature
            for child in self.assist_body.winfo_children():
                child.destroy()
            if not decision.assistance_events:
                self.tk.Label(
                    self.assist_body,
                    text="sin intervenciones · el guardia respetó al modelo",
                    anchor="w", bg=CARD, fg=MUTED, font=(FONTS["mono"], 9),
                ).pack(fill="x")
            for event in decision.assistance_events:
                row = self.tk.Frame(self.assist_body, bg=CARD)
                row.pack(fill="x", pady=2)
                self.tk.Label(
                    row, text=event.kind, bg="#3a2a12", fg=AMBER,
                    font=(FONTS["mono"], 8, "bold"), padx=6, pady=1,
                ).pack(side="left")
                self.tk.Label(
                    row,
                    text=f"{event.proposed}→{event.applied} · {event.reason}",
                    anchor="w", justify="left", bg=CARD, fg=MUTED,
                    font=(FONTS["mono"], 8), wraplength=360,
                ).pack(side="left", padx=(8, 0))

        strategy = getattr(decision, "strategy", None)
        if strategy:
            head = (
                f"{strategy['mission']} · {strategy['priority']}   "
                f"must_move={strategy['must_move']}   "
                f"hold={strategy['hold_streak']}/{strategy['max_hold_streak']}\n"
                f"{strategy['status']}"
            )
            self._label("strategy-head", self.strategy_head, head)
            plan_sig = tuple(strategy.get("plan", ()))
            if plan_sig != self._strategy_sig:
                self._strategy_sig = plan_sig
                for child in self.strategy_plan.winfo_children():
                    child.destroy()
                for step in strategy.get("plan", ()):
                    self.tk.Label(
                        self.strategy_plan, text=f"· {step}", anchor="w", justify="left",
                        bg=CARD, fg=TEXT, font=(FONTS["mono"], 8), wraplength=470,
                    ).pack(fill="x")
        else:
            self._label("strategy-head", self.strategy_head, "sin estrategia en este prompt")

        for axis in ("movement", "aim", "interaction"):
            self._label(
                f"obs-{axis}", self.observations[axis], decision.observations.get(axis, "—")
            )

    # -- response tab --------------------------------------------------------
    def _update_response(self, decision, snapshot, log_stats):
        age = snapshot.tick - decision.observation_tick
        tokens = int((decision.input_tokens or {}).get("request", 0) or 0)
        fields = {
            "model": decision.model_id,
            "prompt": decision.prompt_version,
            "tokens": f"{tokens} in  ·  {self._tokens} acumulados",
            "cost": f"${decision.cost_usd:.6f}  ·  ${self._cost:.5f} acumulado",
            "request": f"{decision.request_ms:.0f} ms",
            "decision": f"{decision.decision_ms:.0f} ms",
            "age": f"{age} ticks",
            "exec": f"{decision.prediction_calls} llamada(s) · {decision.execution}",
            "log": (
                f"{log_stats['sent']} enviados / {log_stats['dropped']} caídos"
                if log_stats
                else "desactivada"
            ),
        }
        for key, value in fields.items():
            self._label(f"resp-{key}", self.response_fields[key], value, fg=TEXT)

        for axis, values in decision.probabilities.items():
            best = max(values, key=values.__getitem__)
            for label, row in self.bars[axis].items():
                row.set(values.get(label, 0.0), best=(label == best))
            confidence = decision.confidence.get(axis)
            if confidence is None:
                self.confidence[axis].set("conf n/a", fg=MUTED, bg=CARD)
            else:
                color = GREEN if confidence >= 0.7 else AMBER if confidence >= 0.4 else RED
                self.confidence[axis].set(f"conf {confidence:.2f}", fg="#10210f", bg=color)

    def _update_warmup(self, error):
        message = f"sin respuesta aún · {error}" if error else "esperando la primera decisión…"
        for axis, rows in self.bars.items():
            for row in rows.values():
                row.set(0.0, best=False)
            self.confidence[axis].set("conf n/a", fg=MUTED, bg=CARD)
        for key in self.response_fields:
            self._label(f"resp-{key}", self.response_fields[key], "—", fg=MUTED)
        for axis in ("movement", "aim", "interaction"):
            self.prop[axis].set("—", fg=MUTED, bg=CARD)
            self.appl[axis].set("—", fg=MUTED, bg=CARD)
            self._label(f"obs-{axis}", self.observations[axis], "—")
        self._label("strategy-head", self.strategy_head, "—")
        for child in self.assist_body.winfo_children():
            child.destroy()
        self.tk.Label(
            self.assist_body, text=message, anchor="w", bg=CARD, fg=MUTED,
            font=(FONTS["mono"], 9), wraplength=470,
        ).pack(fill="x")

    # -- request tab ---------------------------------------------------------
    def _update_request(self, decision):
        if decision is None:
            self._render_text("questions", self.questions_text, "—")
            self._render_json("state", self.state_text, None)
            return
        self._render_text(
            "questions", self.questions_text, _questions_text(decision.request_questions)
        )
        self._render_json("state", self.state_text, decision.request_state)

    # -- world tab -----------------------------------------------------------
    def _update_world(self, readout, decision):
        if readout is None or not readout.available:
            fields = {key: "—" for key in self.world_fields}
            self._label("world-threats", self.world_threats, "modelo del mundo no disponible")
            self._label("world-items", self.world_items, "—")
        else:
            route = f"{readout.route_steps} salas"
            if readout.route_rooms:
                route += " · " + " → ".join(readout.route_rooms[:4])
            fields = {
                "room": f"{readout.room or '?'}"
                + (f" ({readout.room_kind})" if readout.room_kind else ""),
                "floor": f"{readout.floor or '—'}"
                + ("  · ¡nukage!" if readout.nukage else ""),
                "route": route,
                "foes": f"{readout.hidden_foes} ocultos / {readout.foes_total} total"
                f" · {readout.foes_in_sight} a la vista",
                "risk": f"peor sector {readout.worst_sector} = {readout.worst_risk}"
                f" · medio {readout.overall_risk}",
                "target": (readout.recommended_target or {}).get("kind", "—")
                if isinstance(readout.recommended_target, dict)
                else str(readout.recommended_target or "—"),
            }
            threats = "\n".join(
                f"· rumbo {threat['bearing_degrees']}°  dist {threat['distance_px']}px  "
                f"score {threat['threat_score']}  "
                f"{'LOS' if threat['line_of_sight'] else 'sin LOS'}"
                for threat in readout.top_threats
            ) or "—"
            items = "\n".join(
                f"· {item['kind']}  rumbo {item['bearing_degrees']}°  "
                f"dist {item['distance_px']}px  score {item['aspiration_score']}"
                for item in readout.top_aspirations
            ) or "—"
            self._label("world-threats", self.world_threats, threats)
            self._label("world-items", self.world_items, items)
        for key, value in fields.items():
            self._label(f"world-{key}", self.world_fields[key], value)
        note = (
            "esta lectura también viaja al modelo (prompt v3w)"
            if decision is not None and getattr(decision, "world_model", None)
            else "solo visual · no viaja al modelo en este prompt"
        )
        self._label("world-note", self.world_note, note)


def run_jev_window(
    modules,
    wad,
    controller,
    *,
    map_name="E1M1",
    width=320,
    height=200,
    scale=2,
    decision_rate=12.0,
    max_stale_ticks=30,
    on_decision=None,
):
    """Run normal Duum rendering while a one-in-flight worker chooses controls."""

    modules.desktop.use_clock(None)
    modules.desktop.set_keys(0)
    modules.desktop.mount(str(wad))
    app = modules.engine.Duum()
    pilot = "jev-assisted" if controller.assisted else "jev-raw"
    window = modules.frontend.Window(
        app,
        width=width,
        height=height,
        scale=scale,
        title=f"Duum · {pilot} · Jev",
    )
    app.build(window.cv)
    if app.err:
        window._close()
        raise RuntimeError(f"Duum could not start: {app.err}")
    if map_name and app.level != map_name:
        app.load_level(map_name)
    builder = SnapshotBuilder(app, modules.engine)
    panel = Dashboard(modules.frontend.tkinter, window)
    started = time.perf_counter()
    tick = 0
    frames = 0
    next_decision_time = 0.0
    controls = DuumControls()
    latest = None
    latest_snapshot = builder.build(0)
    stale = 0
    model_error = None
    finish_since = None
    minimum_observation_tick = 0
    latencies = []
    applied_decisions = 0
    worker = DecisionWorker(controller)
    logger = getattr(getattr(controller, "client", None), "logger", None)

    def frame():
        nonlocal tick, frames, next_decision_time, controls, latest, builder
        nonlocal latest_snapshot, stale, model_error, applied_decisions
        nonlocal finish_since, minimum_observation_tick
        if not window.running:
            return
        try:
            result = worker.poll()
        except RuntimeError as error:
            model_error = str(error.__cause__ or error)
            controls = DuumControls()
            result = None
        if result is not None:
            age = tick - result.observation_tick
            if age <= max_stale_ticks and result.observation_tick >= minimum_observation_tick:
                latest = result.with_application_tick(tick + 1)
                controls = latest.applied_controls
                applied_decisions += 1
                latencies.append(latest.decision_ms)
                if on_decision:
                    on_decision(latest)
            else:
                stale += 1
        builder.note_controls(controls)
        if controller.assisted:
            ensure_usable_weapon(app, modules.engine)
        modules.desktop.set_keys(controls_to_mask(controls))
        window._frame_once()
        tick += 1
        frames += 1
        latest_snapshot = builder.build(tick)
        if controller.assisted:
            controls = settle_assisted_controls(controls, latest_snapshot)
        if controls.interaction == "use":
            controls = replace(controls, interaction="neither")
        if latest_snapshot.episode.finished:
            if finish_since is None:
                finish_since = time.perf_counter()
                controls = DuumControls()
            elif time.perf_counter() - finish_since >= 1.0:
                if advance_completed_level(app):
                    controls = DuumControls()
                    builder = SnapshotBuilder(app, modules.engine)
                    latest_snapshot = builder.build(tick)
                    latest = None
                    finish_since = None
                    minimum_observation_tick = tick
                    next_decision_time = app.now
        else:
            finish_since = None
        if (
            model_error is None
            and not latest_snapshot.episode.dead
            and not latest_snapshot.episode.finished
            and app.menu is None
            and app.now + 1e-9 >= next_decision_time
        ):
            worker.submit(latest_snapshot)
            next_decision_time += 1.0 / decision_rate
            if next_decision_time < app.now:
                next_decision_time = app.now + 1.0 / decision_rate
        if tick % 4 == 0 or latest is None or model_error:
            panel.update(
                pilot=pilot,
                snapshot=latest_snapshot,
                decision=latest,
                controls=controls,
                worker=worker,
                stale=stale,
                error=model_error,
                log_stats=logger.stats if logger is not None else None,
            )
        if getattr(app, "quit", False):
            window._close()
            return
        window.root.after(1, frame)

    try:
        window.root.after(1, frame)
        window.root.mainloop()
    finally:
        worker.close()
        modules.desktop.set_keys(0)
        app.closed()
    wall_seconds = time.perf_counter() - started
    stats = worker.stats
    ordered = sorted(latencies)

    def percentile(fraction):
        if not ordered:
            return None
        return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]

    return {
        "pilot": pilot,
        "model_inference": True,
        "network": "online: api.typesafe.ai",
        "engine_ticks": tick,
        "rendered_frames": frames,
        "wall_seconds": wall_seconds,
        "complete_decisions": applied_decisions,
        "prediction_calls": applied_decisions * 3,
        "worker_completed": stats.completed,
        "worker_replaced": stats.replaced,
        "stale_results": stale,
        "mean_decision_ms": statistics.fmean(latencies) if latencies else None,
        "p50_decision_ms": percentile(0.50),
        "p95_decision_ms": percentile(0.95),
        "p99_decision_ms": percentile(0.99),
        "max_decision_ms": max(latencies) if latencies else None,
        "final_snapshot": latest_snapshot.to_dict(),
        "final_snapshot_hash": latest_snapshot.state_hash(),
        "model_error": model_error,
    }
