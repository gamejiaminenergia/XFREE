"""The terminal frontend: the same screen, over SSH, with no display at all.

It is a frontend over ``session`` — the backend — exactly like the Tk panel: it
never touches the engine, it only reads the frames the session publishes.  The
layout and the colours come from ``render`` (pure) and ``colors`` (the palette in
``theme.py`` mapped to ANSI), so this file is only geometry, keys and curses.
"""

from __future__ import annotations

import curses
import locale
import threading
import time

from ..integration import DuumRuntime
from ..panel.session import SessionModel
from ..session.core import Session
from . import colors, render

BOX = ("+", "-", "|")
BANNER_H = 1
BOTTOM_H = 8
DRAW_TICKS = 6  # 10 redraws a second at 60 engine ticks
NARROW_WIDTH = 112
FILLED_KEYS = ("warn", "alarm")


def unicode_ok() -> bool:
    """Half blocks need a UTF-8 locale; a C locale would garble them."""

    return "utf" in (locale.getpreferredencoding(False) or "").lower()


class TuiApp:
    """Draw a session in a curses window and take keys from it."""

    def __init__(self, stdscr, session, *, show_game: bool = True, draw_ticks: int = DRAW_TICKS):
        self.stdscr = stdscr
        self.session = session
        self.model = SessionModel()
        self.show_game = bool(show_game) and unicode_ok()
        self.draw_ticks = max(1, int(draw_ticks))
        self.palette = colors.resolve(colors=getattr(curses, "COLORS", 8) or 8)
        self._pairs: dict[str, int] = {}
        self._game_pairs: dict[tuple[int, int], int] = {}
        self._next_pair = 1
        self._setup()

    # -- curses setup --------------------------------------------------------
    def _setup(self) -> None:
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.keypad(True)
        try:
            curses.start_color()
            curses.use_default_colors()
        except curses.error:  # pragma: no cover - odd terminals
            pass
        for key, colour in self.palette.items():
            if self._next_pair >= getattr(curses, "COLOR_PAIRS", 64) - 1:
                break
            try:
                curses.init_pair(self._next_pair, colour, -1)
            except curses.error:  # pragma: no cover
                break
            self._pairs[key] = self._next_pair
            self._next_pair += 1

    def _attr(self, key: str) -> int:
        pair = self._pairs.get(key)
        attribute = curses.color_pair(pair) if pair else curses.A_NORMAL
        if key in FILLED_KEYS:
            attribute |= curses.A_REVERSE
        return attribute

    def _game_attr(self, fg: int, bg: int) -> int:
        found = self._game_pairs.get((fg, bg))
        if found is None:
            if self._next_pair >= getattr(curses, "COLOR_PAIRS", 64):
                return curses.A_NORMAL
            try:
                curses.init_pair(self._next_pair, fg, bg)
            except curses.error:  # pragma: no cover
                return curses.A_NORMAL
            found = self._next_pair
            self._game_pairs[(fg, bg)] = found
            self._next_pair += 1
        return curses.color_pair(found)

    # -- primitives ----------------------------------------------------------
    def _write(self, row: int, column: int, width: int, lines, *, limit: int | None = None) -> int:
        """Write runs of text at an exact position.  Returns the rows used."""

        used = 0
        for index, runs in enumerate(lines):
            if limit is not None and index >= limit:
                break
            at = column
            for text, key in runs:
                room = width - (at - column)
                if room <= 0:
                    break
                text = text[:room]
                if not text:
                    continue
                try:
                    self.stdscr.addstr(row + index, at, text, self._attr(key))
                except curses.error:  # pragma: no cover - last cell of the screen
                    pass
                at += len(text)
            used = index + 1
        return used

    def _box(self, row: int, column: int, height: int, width: int, title: str) -> bool:
        if height < 3 or width < 6:
            return False
        top, horizontal, vertical = BOX
        attr = self._attr("rule")
        try:
            self.stdscr.addstr(row, column, top + horizontal * (width - 2) + top, attr)
            for offset in range(1, height - 1):
                self.stdscr.addstr(row + offset, column, vertical, attr)
                self.stdscr.addstr(row + offset, column + width - 1, vertical, attr)
            self.stdscr.addstr(row + height - 1, column, top + horizontal * (width - 2) + top, attr)
            self.stdscr.addstr(row, column + 2, f" {title[: max(0, width - 6)]} ", self._attr("title"))
        except curses.error:  # pragma: no cover
            return False
        return True

    def _boxed(self, row, column, height, width, title, lines) -> None:
        if self._box(row, column, height, width, title):
            self._write(row + 1, column + 2, width - 4, lines, limit=height - 2)

    def _draw_game(self, row: int, column: int, width: int, rows: int, frame) -> int:
        """Paint the engine frame as half blocks; returns the rows it used."""

        if not self.show_game or frame.rgb is None:
            return 0
        canvas = self.session.runtime.canvas
        art = render.game_art(frame.rgb, canvas.w, canvas.h, width, rows, colors.basic)
        for index, cells in enumerate(art):
            at = column
            for fg, bg, char in cells:
                if at >= column + width:
                    break
                try:
                    self.stdscr.addstr(row + index, at, char, self._game_attr(fg, bg))
                except curses.error:  # pragma: no cover
                    break
                at += 1
        return len(art)

    # -- the screen ----------------------------------------------------------
    def draw(self, frame) -> None:
        height, width = self.stdscr.getmaxyx()
        self.stdscr.erase()
        self._write(0, 0, width, [render.banner(frame, width)])

        if width >= NARROW_WIDTH:
            left = max(26, int(width * 0.30))
            centre = max(34, int(width * 0.36))
            right = max(26, width - left - centre - 6)
        else:
            left, centre, right = 0, max(30, width - 4), 0

        # Only pay for the engine's pixels when they are actually on screen: the
        # copy is most of the per-step cost and a narrow layout never draws it.
        self.session.set_pixels(bool(self.show_game and left))

        top = BANNER_H + 1
        body = max(4, height - top - BOTTOM_H - 2)

        if left:
            self._box(top, 0, body, left, "MEDIDAS")
            used = self._draw_game(top + 1, 0, left - 4, body - 2, frame)
            self._write(
                top + 1 + used, 2, left - 4,
                render.measures(frame, left - 4) + [render.line("")]
                + render.why(frame, left),
                limit=body - 2 - used,
            )

        if centre:
            column = left + (2 if left else 0)
            upper = max(6, body // 2)
            self._boxed(top, column, upper, centre, "DECISION DE LA IA",
                        render.decision(frame, centre))
            lower = body - upper - 1
            self._boxed(top + upper + 1, column, lower, centre,
                        "GUARDIA / POR QUE / ESTRATEGIA",
                        render.guard(frame, centre) + render.strategy(frame, centre))

        if right:
            column = width - right
            upper = max(6, body // 2)
            self._boxed(top, column, upper, right, "ENLACE", render.link(frame, right))
            lower = body - upper - 1
            self._boxed(top + upper + 1, column, lower, right, "TELEMETRIA",
                        render.telemetry(self.model, right))

        bottom = height - BOTTOM_H
        if bottom > top + 2:
            if right:
                events_width = max(40, width - 40)
                self._boxed(bottom, 0, BOTTOM_H, events_width, "EVENTOS - ULTIMO ARRIBA",
                            render.events(self.model, events_width))
                self._boxed(bottom, events_width, BOTTOM_H, width - events_width, "BALANCE",
                            render.balance(self.model, width - events_width))
            else:
                self._boxed(bottom, 0, BOTTOM_H, width - 2, "EVENTOS - ULTIMO ARRIBA",
                            render.events(self.model, width - 2))

        state = "PAUSA" if self.session.paused else "EN MARCHA"
        self._write(height - 1, 0, width, [[
            ("[q] salir  [p] pausa  [+/-] ritmo  [g] juego   ", "off"),
            (f" {state} ", "warn" if self.session.paused else "ok"),
            (f" {self.session.decision_rate:.0f} Hz  {frame.tick} ticks", "static"),
        ]])
        self.stdscr.noutrefresh()
        curses.doupdate()

    # -- keys and loop -------------------------------------------------------
    def handle_keys(self, stop: threading.Event) -> None:
        while True:
            try:
                key = self.stdscr.getch()
            except curses.error:  # pragma: no cover
                return
            if key == -1:
                return
            if key in (ord("q"), ord("Q")):
                stop.set()
                return
            if key in (ord("p"), ord("P")):
                self.session.set_paused(not self.session.paused)
            elif key in (ord("+"), ord("=")):
                self.session.set_decision_rate(min(20.0, self.session.decision_rate + 1))
            elif key in (ord("-"), ord("_")):
                self.session.set_decision_rate(max(1.0, self.session.decision_rate - 1))
            elif key in (ord("g"), ord("G")):
                self.show_game = (not self.show_game) and unicode_ok()

    def on_frame(self, frame, stop: threading.Event) -> None:
        self.model.observe_vitals(frame.snapshot.player, frame.decision)
        if frame.decision is not None:
            self.model.account(frame.decision)
        if frame.tick % self.draw_ticks == 0:
            try:
                self.draw(frame)
            except curses.error:  # pragma: no cover - terminal too small
                pass
        self.handle_keys(stop)

    def run(self) -> dict:
        stop = threading.Event()
        started = time.perf_counter()
        try:
            self.session.run(
                stop=stop, realtime=True, fps=60.0,
                on_frame=lambda frame: self.on_frame(frame, stop),
            )
        finally:
            summary = self.session.summary(wall_seconds=time.perf_counter() - started)
        return summary


def run_tui(
    modules,
    wad,
    controller,
    *,
    map_name="E1M1",
    width=320,
    height=200,
    decision_rate=10.0,
    max_stale_ticks=30,
    show_game=True,
) -> dict:
    """Run the terminal frontend over a headless session.  Returns its summary."""

    runtime = DuumRuntime(modules, wad, map_name, width, height)
    session = Session(
        runtime, controller, decision_rate=decision_rate,
        max_stale_ticks=max_stale_ticks, pixels=True, frame_every=2,
    )
    try:
        return curses.wrapper(lambda stdscr: TuiApp(stdscr, session, show_game=show_game).run())
    except KeyboardInterrupt:  # pragma: no cover - Ctrl-C is a normal way out
        return session.summary()
    finally:
        session.close()
