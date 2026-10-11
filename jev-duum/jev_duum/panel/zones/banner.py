"""Banner zone: brand, map, clock, link quality and the alarm summary."""

from __future__ import annotations

from ...theme import ALARM, FONTS, PANEL, STATIC, TITLE, VALUE, WARN
from ..layout import TITLE_PT, TITLE_SUBTITLE, TITLE_TEXT
from ..render import label
from ..widgets import Flag


class BannerSection:
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

    # -- banner: system, time, link quality and the alarm summary ------------
    def _build_banner(self):
        tk = self.tk
        left = tk.Frame(self.banner, bg=PANEL)
        left.pack(side="left", padx=8, pady=4)
        # A product title the room can read from ten metres.  Tk has no
        # letter-spacing, so each glyph is its own label with a hair of padding;
        # the "+" carries the single accent.  Both lines are fixed width, so the
        # brand never pushes the map, the clock or the link block beside it.
        brand = tk.Frame(left, bg=PANEL)
        brand.pack(side="left")
        word = tk.Frame(brand, bg=PANEL)
        word.pack(anchor="w")
        for glyph in TITLE_TEXT:
            tk.Label(
                word, text=glyph, bg=PANEL,
                fg=WARN if glyph == "+" else TITLE,
                font=(FONTS["mono"], TITLE_PT, "bold"), padx=2,
            ).pack(side="left")
        tk.Label(
            brand, text=TITLE_SUBTITLE, anchor="w", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 9),
        ).pack(anchor="w")
        self.map_label = tk.Label(
            left, text="", width=9, anchor="w", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 10),
        )
        self.map_label.pack(side="left", padx=(8, 0))
        self.live_label = tk.Label(
            left, text="", width=34, anchor="w", bg=PANEL, fg=VALUE,
            font=(FONTS["mono"], 10),
        )
        self.live_label.pack(side="left", padx=(12, 0))

        right = tk.Frame(self.banner, bg=PANEL)
        right.pack(side="right", padx=8, pady=4)
        self._header_button(right, "F11", self._toggle_fullscreen)
        self._header_button(right, "CERRAR", self._close_window, danger=True)
        self.alarm_count = tk.Label(
            right, text="", width=10, anchor="e", bg=PANEL, fg=STATIC,
            font=(FONTS["mono"], 10, "bold"),
        )
        self.alarm_count.pack(side="right", padx=(10, 0))
        self.link_flag = Flag(tk, right, width=15)
        self.link_flag.label.pack(side="right", pady=(2, 0))

    def _update_banner(self, stale, error, worker):
        """The always-visible alarm summary: one line, a count and a word."""

        if error:
            text, level = "ALARMA 1", "alarm"
        elif stale > 3:
            text, level = "AVISO 1", "warn"
        else:
            text, level = "ALARMA 0", "ok"
        fg, _bg = Flag.LEVELS[level]
        label(self.cache, "alarm", self.alarm_count, text, fg=fg)
