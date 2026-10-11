"""Tk gameplay loop and the live Jev decision window (SCADA-style HMI).

One screen, nothing to select, nothing that moves.  The layout follows the
conventions of a transmission SCADA display rather than those of a web
dashboard:

* a fixed three-column grid plus an event list, so nothing is ever hidden
  behind a tab or a scrollbar;
* a status banner across the top with the link quality and the alarm summary
  always visible (ISA-18.2);
* black background with static text in white/grey and low-contrast chrome,
  which is the load-despatch convention (IS 18058:2023);
* **colour reserved for abnormal conditions** (ISA-101): measured values are
  white, and a colour appears only when a limit is crossed, a guard intervenes
  or the link degrades.  Colour is never the only cue — every coloured value
  carries its word;
* no animation, no blinking, no transitions, no gradients, no shadows;
* monospace TAG / value / unit tables and an event list, as an operator expects.

``DESIGN.md`` is the style guide this file implements; the palette below is the
short version of it.  Anything not in that guide does not belong on screen.

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
from collections import deque
from dataclasses import replace

from .actions import controls_to_mask, ensure_usable_weapon, settle_assisted_controls
from .overlays import MiniMap, StaleOverlay
from .snapshot import SnapshotBuilder
from .types import DuumControls
from .worker import DecisionWorker
from .world_readout import read_world

# ── palette: the whole style guide in nine values ────────────────────────────
# Chrome never uses a data colour, and a data colour never decorates.  Static
# text is white/grey; the four hues below are reserved, each with one meaning,
# and each one always travels with the word that spells it out.
BG = "#000000"        # screen background: black is the transmission default
PANEL = "#0d0d0d"     # panel background, a shade above the screen
RULE = "#333333"      # 1px separators; emphasis is line weight, not colour
STATIC = "#b0b0b0"    # static text: labels, tags, table headers
TITLE = "#ffffff"     # panel headings
VALUE = "#ffffff"     # measured values, when everything is normal
OK = "#00ff00"        # in service / applied as proposed
WARN = "#ffa500"      # above a limit, guard intervention, stale data
ALARM = "#ff0000"     # alarm: no link, critical health
INFO = "#ffff00"      # reference information: limits, units, secondary
OFF = "#808080"       # out of service / no data
TRACK = "#3c3c3c"     # bargraph background (chrome, not information)

# The panel's own tests import these names; the semantics are the ones above.
GREEN, AMBER, RED = OK, WARN, ALARM

FONTS = {"mono": "DejaVu Sans Mono", "ui": "DejaVu Sans"}

# Height of the event list pinned to the bottom of the window.
EVENT_H = 145
# How many decisions the event list shows at once.
EVENT_ROWS = 5

# Confidence bands, in words, because a bare 0.62 means nothing to a room.
# The level decides the colour: normal states carry no colour at all.
def _confidence_level(value):
    if value is None:
        return "SIN DATO", "off"
    if value >= 0.70:
        return "ALTA", "ok"
    if value >= 0.40:
        return "MEDIA", "warn"
    return "BAJA", "alarm"


# The typed questions the model answers, in the order the panel presents them.
# ``target`` only exists on the hunt prompts; the panel builds the rows it
# actually receives, so a new prompt version needs no change here.
AXES = (
    ("movement", "MOVIMIENTO", "MOV"),
    ("aim", "APUNTADO", "APU"),
    ("interaction", "ACCIÓN", "ACC"),
    ("target", "OBJETIVO", "OBJ"),
)

AXIS_ORDER = {name: index for index, (name, _, _) in enumerate(AXES)}

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


def _threshold_color(base, value, warn_at, crit_at):
    """White → amber → red as a measurement approaches its limits.

    Normal values stay the base colour: ISA-101 asks for colour on the
    abnormal, and a screen where everything is coloured is a screen where
    nothing is.  A critical value keeps its red; the old blink dropped it to a
    dark red at 1.37:1 against its own bar every other refresh.
    """

    if crit_at is not None and value <= crit_at:
        return ALARM
    if warn_at is not None and value <= warn_at:
        return WARN
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


# ── widgets ──────────────────────────────────────────────────────────────────


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
        self.title = tkinter.Label(
            head, text=title.upper(), bg=PANEL, fg=TITLE,
            font=(FONTS["mono"], 10, "bold"), anchor="w",
        )
        self.title.pack(side="left")
        self.flag_holder = tkinter.Frame(head, bg=PANEL)
        self.flag_holder.pack(side="right")
        tkinter.Frame(self.frame, bg=RULE, height=1).pack(fill="x", padx=8, pady=(4, 0))
        self.body = tkinter.Frame(self.frame, bg=PANEL)
        self.body.pack(fill="both", expand=expand, padx=8, pady=(5, 7))

    def set_title(self, text):
        if self.title.cget("text") != text.upper():
            self.title.configure(text=text.upper())


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
            self.frame, text="—", width=9, anchor="e", bg=PANEL, fg=VALUE,
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
        self.choice = tkinter.Label(
            head, text="—", bg=PANEL, fg=VALUE, font=(FONTS["mono"], 20, "bold")
        )
        self.choice.pack(side="left", padx=(4, 0))
        self.conf = Flag(tkinter, head)
        self.conf.label.pack(side="right")
        self.canvas = tkinter.Canvas(
            self.frame, height=20, bg=TRACK, highlightthickness=0, bd=0
        )
        self.canvas.pack(fill="x", pady=(3, 2))
        self.canvas.bind("<Configure>", self._on_configure)
        self.breakdown = tkinter.Label(
            self.frame, text="", bg=PANEL, fg=STATIC, font=(FONTS["mono"], 9),
            anchor="w", justify="left",
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
        self.breakdown.configure(text=f"ALTERNATIVAS   {others}" if others else "")
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


def _table(tkinter, parent, rows, *, keys=STATIC, size=10, pairs=1):
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


def _state_index(state) -> str:
    """One line per top-level state key, with its type and size."""

    if not isinstance(state, dict):
        return "—"
    rows = []
    for key, value in state.items():
        if isinstance(value, dict):
            kind = f"dict({len(value)})"
        elif isinstance(value, (list, tuple)):
            kind = f"list({len(value)})"
        elif isinstance(value, bool):
            kind = f"bool {value}"
        elif isinstance(value, (int, float)):
            kind = f"num {value}"
        else:
            kind = f"str({len(str(value))})"
        rows.append((str(key), kind))
    width = max((len(key) for key, _ in rows), default=0)
    return "\n".join(f"{key:<{width}}  {kind}" for key, kind in rows)


def _controls_text(controls) -> str:
    """The three typed answers of one control set, as the event list shows it."""

    if controls is None:
        return ""
    parts = [controls.movement, controls.aim, controls.interaction]
    target = getattr(controls, "target", None)
    if target:
        parts.append(str(target))
    return "   ".join(parts)


def _guard_motive(events) -> str:
    """One line explaining a decision's intervention, for the event list."""

    if not events:
        return ""
    parts = [f"{event.kind}: {event.proposed}→{event.applied}" for event in events]
    text = "   ".join(parts)
    if len(events) > 1:
        text = f"×{len(events)}  " + text
    return text if len(text) <= 96 else text[:93] + "…"


def _target_text(target) -> str:
    """Render the recommended target as a TAG, not as a dumped dictionary.

    The prompt versions disagree on the shape (a word in one, a dict with a
    position in another); an operator field has to read like a field either way.
    """

    if isinstance(target, dict):
        kind = target.get("kind") or target.get("name") or "?"
        position = target.get("position_px")
        if isinstance(position, (list, tuple)) and len(position) == 2:
            return f"{kind} @ {position[0]:.0f},{position[1]:.0f}"
        return str(kind)
    return str(target) if target else "—"


def _questions_summary(questions) -> str:
    """The typed questions with the tag that actually travelled in the request."""

    if not isinstance(questions, dict) or not questions:
        return "—"
    blocks = []
    for name, question in questions.items():
        title = next((label for key, label, _ in AXES if key == name), None)
        heading = f"{title} ({name})" if title else str(name)
        instructions = question.get("instructions") or {}
        criteria = question.get("criteria") or {}
        task = instructions.get("task") or instructions.get("question") or ""
        blocks.append(f"{heading}  ·  {question.get('type', '?')}")
        if task:
            blocks.append(f"  {task}")
        if criteria:
            blocks.append("  respuestas: " + ", ".join(criteria))
    return "\n".join(blocks)


class Dashboard:
    """One fixed screen: situation, decision, link, events.  No tabs, no motion."""

    def __init__(self, tkinter, window, *, fullscreen=True):
        FONTS["mono"], FONTS["ui"] = _pick_families(tkinter)
        self.tk = tkinter
        self.window = window
        self.cache = DeltaCache()
        self._history: deque = deque(maxlen=64)
        self._history_sig = None
        self._event_cells: list = []
        self._latencies: list[float] = []
        self._cost = 0.0
        self._tokens = 0
        self._decisions = 0
        self._counted = None
        self._strategy_sig = None
        self._geo = None
        self._fullscreen = False
        self._axes_sig = None
        self._muted = False
        self.game_w = int(getattr(window.cv, "w", 320))
        self.game_h = int(getattr(window.cv, "h", 200))
        self.base_scale = max(1, int(getattr(window, "scale", 1)))

        root = window.root
        root.configure(bg=BG)
        root.resizable(True, True)
        window.tkcv.pack_forget()

        # banner · three columns · event list.  Column 0 is as wide as the game
        # at its largest crisp integer zoom and no wider, so the engine canvas
        # never floats in a margin of background.
        self.banner = tkinter.Frame(root, bg=PANEL, highlightbackground=RULE,
                                    highlightthickness=1)
        self.banner.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.center = tkinter.Frame(root, bg=BG)
        self.center.grid(row=1, column=1, rowspan=3, sticky="nsew", padx=(6, 0))
        self.right = tkinter.Frame(root, bg=BG)
        self.right.grid(row=1, column=2, rowspan=3, sticky="nsew", padx=(6, 0))
        self.bottom = tkinter.Frame(root, bg=BG)
        self.bottom.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        root.grid_columnconfigure(0, weight=0)
        root.grid_columnconfigure(1, weight=5)
        root.grid_columnconfigure(2, weight=5)
        # Only the diagram row absorbs slack.  Giving the weight to a fixed
        # panel is how its body ended up unmapped: when the natural height
        # overflowed the window, that row ate the whole deficit.
        root.grid_rowconfigure(0, weight=0)
        root.grid_rowconfigure(1, weight=0)
        root.grid_rowconfigure(2, weight=0)
        root.grid_rowconfigure(3, weight=1)
        root.grid_rowconfigure(4, weight=0)

        self._build_banner()
        self._build_game(window)
        self._build_situation()
        self._build_decision()
        self._build_link()
        self._build_events()

        root.bind("<Configure>", self._on_configure)
        root.bind("<F11>", self._toggle_fullscreen)
        self._set_fullscreen(fullscreen)
        root.after(60, self._initial_relayout)

    # -- helpers -------------------------------------------------------------
    def _set_fullscreen(self, enabled):
        """Fill the screen on start; F11 toggles, and some WMs need a fallback."""

        self._fullscreen = bool(enabled)
        root = self.window.root
        try:
            root.attributes("-fullscreen", self._fullscreen)
        except self.tk.TclError:  # pragma: no cover - platform dependent
            return
        if self._fullscreen:
            root.update_idletasks()
            screen_w = root.winfo_screenwidth()
            screen_h = root.winfo_screenheight()
            # A window manager that ignores -fullscreen still gets a sized window.
            if root.winfo_width() < screen_w * 0.9 or root.winfo_height() < screen_h * 0.9:
                try:
                    root.geometry(f"{screen_w}x{screen_h}+0+0")
                except self.tk.TclError:  # pragma: no cover
                    pass
        root.after(50, self._relayout_now)

    def _toggle_fullscreen(self, _event=None):
        self._set_fullscreen(not self._fullscreen)
        return "break"

    def _close_window(self, _event=None):
        """The window has no title bar in fullscreen; give the user a way out."""

        try:
            # The same flag the engine's own Menu -> Quit sets: the frame loop
            # closes the window cleanly on its next tick, with no pending callbacks.
            self.window.app.quit = True
            return "break"
        except Exception:  # pragma: no cover - fall back to a hard close
            try:
                self.window._close()
            except Exception:
                pass
        return "break"

    def _header_button(self, parent, text, command, *, danger=False):
        idle = ALARM if danger else STATIC
        button = self.tk.Label(
            parent, text=text, bg=PANEL, fg=idle, font=(FONTS["mono"], 9, "bold"),
            padx=8, pady=2, bd=0, cursor="hand2",
        )
        button.pack(side="left", padx=(6, 0))
        button.bind("<Button-1>", command)
        button.bind("<Enter>", lambda _event: button.configure(fg=TITLE))
        button.bind("<Leave>", lambda _event: button.configure(fg=idle))
        return button

    def _on_configure(self, event):
        if event.widget is not self.window.root:
            return
        self._relayout(event.width, event.height)

    def _relayout_now(self):
        root = self.window.root
        self._relayout(root.winfo_width(), root.winfo_height())

    def _initial_relayout(self):
        root = self.window.root
        self._relayout(max(root.winfo_width(), root.winfo_reqwidth()),
                       max(root.winfo_height(), root.winfo_reqheight()))

    def _relayout(self, total_w, total_h):
        """Size the game column to the engine canvas, never the other way round.

        The engine renders at integer zoom, so a column wider than the canvas
        only buys background.  The game takes the largest crisp zoom that fits
        the height budget and at most 40% of the width.
        """

        if total_w <= 1 or total_h <= 1:
            return
        if (total_w, total_h) == self._geo:
            return
        self._geo = (total_w, total_h)

        # banner + measurements + event list + the diagram's own chrome
        reserved = 28 + 146 + EVENT_H + 130
        avail_h = max(self.game_h, total_h - reserved)
        by_height = max(1, avail_h // self.game_h)
        by_width = max(1, int(total_w * 0.40) // self.game_w)
        scale = max(1, min(by_height, by_width))
        if scale != self.window.scale:
            self.window.scale = scale
        self.window.tkcv.configure(width=self.game_w * scale, height=self.game_h * scale)
        for bar in (self.health, self.armor, self.ammo):
            bar.refresh()
        for row in self.axes.values():
            row.refresh()

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
        widget.tag_configure("key", foreground=TITLE)
        widget.tag_configure("num", foreground=INFO)
        widget.tag_configure("const", foreground=OFF)
        if payload is None:
            widget.insert("end", "sin dato")
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

    # -- banner: system, time, link quality and the alarm summary ------------
    def _build_banner(self):
        tk = self.tk
        left = tk.Frame(self.banner, bg=PANEL)
        left.pack(side="left", padx=8, pady=4)
        tk.Label(
            left, text="JEV·DUUM", bg=PANEL, fg=TITLE, font=(FONTS["mono"], 12, "bold")
        ).pack(side="left")
        self.map_label = tk.Label(
            left, text="", bg=PANEL, fg=STATIC, font=(FONTS["mono"], 10)
        )
        self.map_label.pack(side="left", padx=(8, 0))
        self.live_label = tk.Label(
            left, text="", bg=PANEL, fg=VALUE, font=(FONTS["mono"], 10)
        )
        self.live_label.pack(side="left", padx=(12, 0))

        right = tk.Frame(self.banner, bg=PANEL)
        right.pack(side="right", padx=8, pady=4)
        self._header_button(right, "F11", self._toggle_fullscreen)
        self._header_button(right, "CERRAR", self._close_window, danger=True)
        self.alarm_count = tk.Label(
            right, text="", bg=PANEL, fg=STATIC, font=(FONTS["mono"], 10, "bold")
        )
        self.alarm_count.pack(side="right", padx=(10, 0))
        self.link_flag = Flag(tk, right)
        self.link_flag.label.pack(side="right")

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
            size=9, pairs=2,
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
            size=9, pairs=1,
        )
        self.world_threats = tk.Label(
            side, text="", anchor="w", justify="left", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 9),
        )
        self.world_threats.pack(fill="x", pady=(4, 0))

    def _build_situation(self):
        """The situational table lives inside the diagram panel.

        Kept as a named no-op so the build order in ``__init__`` still reads as
        the screen's zones: banner, game, situation, decision, link, events.
        """

    # -- centre column: the decision ----------------------------------------
    def _build_decision(self):
        tk = self.tk
        panel = Panel(tk, self.center, "Decisión de la IA", expand=True)
        self.decision_panel = panel
        self.decision_flag = Flag(tk, panel.flag_holder)
        self.decision_flag.label.pack(side="right")
        self.axes: dict = {}
        self.axes_body = tk.Frame(panel.body, bg=PANEL)
        self.axes_body.pack(fill="x")

        guard = Panel(tk, self.center, "Guardia determinista")
        self.guard_panel = guard
        self.guard_flag = Flag(tk, guard.flag_holder)
        self.guard_flag.label.pack(side="right")
        self._guard_table, self.guard_fields = _table(
            tk, guard.body,
            (("PROPUESTO", "prop"), ("APLICADO", "appl")),
            size=10,
        )
        self.guard_body = tk.Frame(guard.body, bg=PANEL)
        self.guard_body.pack(fill="x", pady=(3, 0))

        why = Panel(tk, self.center, "Por qué · respuesta del modelo")
        self.why_panel = why
        self._why_table, self.observations = _table(
            tk, why.body, [(title, axis) for axis, title, _ in AXES],
            size=9,
        )
        for label in self.observations.values():
            label.configure(wraplength=380, justify="left")

        strategy = Panel(tk, self.center, "Estrategia")
        self.strategy_panel = strategy
        self.strategy_head = tk.Label(
            strategy.body, text="", anchor="w", justify="left", bg=PANEL, fg=VALUE,
            font=(FONTS["mono"], 9), wraplength=420,
        )
        self.strategy_head.pack(fill="x")
        self.strategy_plan = tk.Frame(strategy.body, bg=PANEL)
        self.strategy_plan.pack(fill="x", pady=(3, 0))

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
            value = tk.Label(cell, text="—", bg=PANEL, fg=VALUE, font=(FONTS["mono"], 11, "bold"))
            value.pack(anchor="w", padx=6, pady=(4, 0))
            # The sample count travels with the percentile: a p95 over one
            # measurement is that measurement, and it used to look like a bug.
            label = tk.Label(
                cell, text=f"{caption} {unit}".strip(), bg=PANEL, fg=STATIC,
                font=(FONTS["mono"], 9),
            )
            label.pack(anchor="w", padx=6, pady=(0, 4))
            self._tiles[key] = value
            self._tile_captions[key] = (label, f"{caption} {unit}".strip())
        self.cost_label = tk.Label(
            self.right, text="", anchor="w", bg=BG, fg=STATIC, font=(FONTS["mono"], 9)
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
            size=9,
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
            size=9,
        )
        tk.Label(
            panel.body, text="RESPUESTA CRUDA", anchor="w", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 9, "bold"),
        ).pack(fill="x", pady=(6, 0))
        self.response_raw_text = _plain_text(tk, panel.body, height=10, size=9, width=24,
                                             wrap="char")
        self.response_raw_text.pack(fill="both", expand=True, pady=(2, 0))

    # -- event list: newest first, one row per decision ---------------------
    def _build_events(self):
        """A real event list: full width, one column per field.

        The fields used to be packed left, so the strip spent two thirds of the
        screen on nothing.  The last column takes the slack instead, and it
        carries the thing that actually explains an event: why the guard moved.
        """

        tk = self.tk
        panel = Panel(tk, self.bottom, "Eventos · último arriba")
        # The loop's own telemetry sits in the header's blank right half rather
        # than on a line of its own.
        self._event_note = tk.Label(
            panel.header, text="", anchor="e", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 9),
        )
        self._event_note.pack(side="right", padx=(0, 10))
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

    # -- update --------------------------------------------------------------
    def update(self, *, pilot, snapshot, decision, controls, worker, stale, error, log_stats=None):
        player = snapshot.player
        episode = snapshot.episode
        max_health = max(1, int(getattr(player, "max_health", 100) or 100))
        critical = player.health <= int(max_health * 0.35)
        self.health.set(
            player.health, max_health,
            warn_at=int(max_health * 0.70), crit_at=int(max_health * 0.35),
        )
        self.armor.set(player.armor, 200, warn_at=100, crit_at=40)
        ammo = player.ammo
        self.ammo.set(min(ammo, 100), 100, "∞" if ammo >= 999 else str(ammo), crit_at=10)

        self._label("map", self.map_label, snapshot.map_name)
        self._label(
            "live",
            self.live_label,
            f"TICK {snapshot.tick}   T+{episode.game_time:7.1f}s   "
            f"{'FIN' if episode.finished else 'MUERTO' if episode.dead else 'EN MARCHA'}",
            fg=ALARM if episode.dead else VALUE,
        )
        measures = {
            "weapon": player.weapon_name,
            "kills": str(episode.kills),
            "items": str(episode.items),
            "damage": str(episode.damage_received),
            "sectors": str(episode.unique_sectors),
            "stuck": f"{episode.stuck_ticks} / inactivo {episode.idle_ticks}",
        }
        for key, value in measures.items():
            self._label(f"mes-{key}", self.measure_fields[key], value)
        self._label(
            "pipeline",
            self._event_note,
            f"BUCLE  worker {'ocupado' if worker.busy else 'libre'}   "
            f"decididas {worker.stats.completed}   descartadas {worker.stats.replaced}   "
            f"obsoletas {stale}",
        )

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
        self._update_situation(readout)
        self._update_banner(stale, error, worker)

        if decision is not None:
            self._account(decision)
        self._update_counters()
        self._update_quality(stale, error, critical)
        self._update_axes(decision)
        self._update_guard(decision)
        self._update_why(decision)
        self._update_request(decision)
        self._update_response(decision, snapshot, log_stats)
        self._update_events()
        if decision is None:
            self._update_warmup(error)

    # -- link quality: the decision's data-quality flags ---------------------
    def _update_quality(self, stale, error, critical):
        """Spell out the state of the link and of the decision, in words.

        A decision that cannot be trusted is also *drawn* as untrustworthy:
        the chosen answer greys out and the distributions lose their bright
        block, so the screen never presents a dead decision as a live one.
        """

        if error:
            text, level = "SIN COMUNICACIÓN", "alarm"
        elif stale > 3:
            text, level = "DATOS OBSOLETOS", "warn"
        elif critical:
            text, level = "SALUD CRÍTICA", "alarm"
        else:
            text, level = "EN LÍNEA", "ok"
        self._muted = bool(error) or stale > 3
        self.link_flag.level(text, level)
        self.decision_flag.level(
            f"OBSOLETA ×{stale}" if stale > 3 else text, level
        )

    def _update_banner(self, stale, error, worker):
        """The always-visible alarm summary: one line, a count and a word."""

        if error:
            text, level = "ALARMA 1", "alarm"
        elif stale > 3:
            text, level = "AVISO 1", "warn"
        else:
            text, level = "ALARMA 0", "ok"
        fg, _bg = Flag.LEVELS[level]
        self._label("alarm", self.alarm_count, text, fg=fg)

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
        self._label("guard-prop", self.guard_fields["prop"],
                    proposed_text or "sin dato", fg=VALUE if proposed_text else OFF)
        self._label("guard-appl", self.guard_fields["appl"],
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
        for event in events:
            row = self.tk.Frame(self.guard_body, bg=PANEL)
            row.pack(fill="x", pady=1)
            self.tk.Label(
                row, text=event.kind, bg=PANEL, fg=WARN,
                font=(FONTS["mono"], 9, "bold"), anchor="w",
            ).pack(side="left", padx=(0, 6))
            self.tk.Label(
                row,
                text=f"{event.reason}",
                anchor="w", justify="left", bg=PANEL, fg=STATIC,
                font=(FONTS["mono"], 9), wraplength=340,
            ).pack(side="left")

    def _update_why(self, decision):
        for axis, widget in self.observations.items():
            text = "sin dato" if decision is None else decision.observations.get(axis, "—")
            self._label(f"why-{axis}", widget, str(text).replace(">", "="))
        strategy = getattr(decision, "strategy", None) if decision is not None else None
        if strategy:
            head = (
                f"{strategy['mission']} · prioridad {strategy['priority']}\n"
                f"avanzar={strategy['must_move']}   "
                f"sostener {strategy['hold_streak']}/{strategy['max_hold_streak']}   "
                f"{strategy['status']}"
            )
        else:
            head = "sin estrategia en este prompt"
        self._label("strategy-head", self.strategy_head, head)
        plan_sig = tuple(strategy.get("plan", ())) if strategy else ()
        if plan_sig != self._strategy_sig:
            self._strategy_sig = plan_sig
            for child in self.strategy_plan.winfo_children():
                child.destroy()
            for step in plan_sig:
                self.tk.Label(
                    self.strategy_plan, text=f"· {step}", anchor="w", justify="left",
                    bg=PANEL, fg=STATIC, font=(FONTS["mono"], 9), wraplength=420,
                ).pack(fill="x")

    # -- situation: diagram tags, threats and route --------------------------
    def _update_situation(self, readout):
        if readout is None or not readout.available:
            for key, widget in self.world_fields.items():
                self._label(f"world-{key}", widget, "sin dato", fg=OFF)
            self._label("world-threats", self.world_threats, "modelo del mundo no disponible",
                        fg=OFF)
            return
        route = f"{readout.route_steps} salas"
        if readout.route_rooms:
            route += " " + " → ".join(readout.route_rooms[:3])
        fields = {
            "room": f"{readout.room or '?'}"
            + (f" ({readout.room_kind})" if readout.room_kind else ""),
            "floor": f"{readout.floor or '—'}" + ("  NUKAGE" if readout.nukage else ""),
            "route": route,
            "foes": f"{readout.foes_in_sight} vista / {readout.hidden_foes} ocultos"
            f" / {readout.foes_total} total",
            "risk": f"peor sector {readout.worst_sector} = {readout.worst_risk}"
            f"   medio {readout.overall_risk}",
            "target": _target_text(readout.recommended_target),
        }
        for key, value in fields.items():
            self._label(f"world-{key}", self.world_fields[key], value, fg=VALUE)
        threats = "\n".join(
            f"{threat['bearing_degrees']:>6.0f}°  {threat['distance_px']:>5.0f}px"
            f"  AMENAZA {threat['threat_score']:>4}  "
            f"{'LOS' if threat['line_of_sight'] else 'SIN LOS'}"
            for threat in readout.top_threats
        ) or "sin amenazas a la vista"
        self._label("world-threats", self.world_threats, threats, fg=STATIC)

    # -- counters and accounting ---------------------------------------------
    def _account(self, decision):
        token = (decision.observation_tick, decision.application_tick)
        if token == self._counted:
            return
        self._counted = token
        self._latencies.append(float(decision.decision_ms))
        self._cost += float(decision.cost_usd or 0.0)
        self._tokens += int((decision.input_tokens or {}).get("request", 0) or 0)
        self._decisions += 1
        self._history.appendleft(
            {
                "n": self._decisions,
                "tick": decision.observation_tick,
                "movement": decision.applied_controls.movement,
                "aim": decision.applied_controls.aim,
                "interaction": decision.applied_controls.interaction,
                "target": getattr(decision.applied_controls, "target", None),
                "confidence": max(
                    (value for value in decision.confidence.values() if value is not None),
                    default=None,
                ),
                "ms": float(decision.decision_ms or 0.0),
                "guard": _guard_motive(decision.assistance_events),
            }
        )
        self._history_sig = None

    def _update_counters(self):
        p50 = _percentile(self._latencies, 0.50)
        p95 = _percentile(self._latencies, 0.95)
        samples = len(self._latencies)
        tiles = {
            "decisions": str(self._decisions),
            "p50": f"{p50:.0f}" if p50 is not None else "—",
            "p95": f"{p95:.0f}" if p95 is not None else "—",
            "tokens": str(self._tokens),
        }
        for key, value in tiles.items():
            self._label(f"tile-{key}", self._tiles[key], value)
        for key in ("p50", "p95"):
            label, caption = self._tile_captions[key]
            self._label(f"caption-{key}", label, f"{caption} n={samples}")
        self._label("cost", self.cost_label, f"COSTE ACUMULADO  ${self._cost:.5f}")

    # -- event list ----------------------------------------------------------
    def _update_events(self):
        items = list(self._history)[:EVENT_ROWS]
        signature = tuple(item["n"] for item in items)
        if signature == self._history_sig:
            return
        self._history_sig = signature
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

    # -- request and response, always visible --------------------------------
    def _update_request(self, decision):
        if decision is None:
            for key, widget in self.request_fields.items():
                self._label(f"req-{key}", widget, "sin dato", fg=OFF)
            self._render_text("state-index", self.state_index_text, "sin dato")
            self._render_text("questions", self.questions_text, "sin dato")
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
            self._label(f"req-{key}", self.request_fields[key], value, fg=VALUE)
        self._render_text("state-index", self.state_index_text, _state_index(state))
        self._render_text(
            "questions", self.questions_text, _questions_summary(decision.request_questions)
        )

    def _update_response(self, decision, snapshot, log_stats):
        if decision is None:
            for key, widget in self.response_fields.items():
                self._label(f"resp-{key}", widget, "sin dato", fg=OFF)
            self._render_json("response-raw", self.response_raw_text, None)
            return
        age = snapshot.tick - decision.observation_tick
        fields = {
            "model": decision.model_id,
            "prompt": decision.prompt_version,
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
            self._label(f"resp-{key}", self.response_fields[key], value, fg=VALUE)
        self._render_json(
            "response-raw", self.response_raw_text, getattr(decision, "response_raw", None)
        )

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
    fullscreen=True,
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
    panel = Dashboard(modules.frontend.tkinter, window, fullscreen=fullscreen)
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
                if latest.hunt is not None:
                    builder.note_hunt_target(latest.hunt.get("target_id"))
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
