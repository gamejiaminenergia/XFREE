"""The one screen: layout root, the frame contract and the zones that fill it.

Everything here is presentation.  The zones own their widgets but live on
this object, so ``Dashboard`` keeps the single set of boxes the geometry
invariant is measured on; the loop still never learns how the screen is drawn."""

from __future__ import annotations

import time

from ..theme import ALARM, BG, FONTS, PANEL, RULE, VALUE
from ..world_readout import read_world
from .delta import DeltaCache
from .format import _percentile, _pick_families
from .frame import HmiFrame
from .layout import BANNER_H, EVENT_H, TELEMETRY_INTERVAL, TELEMETRY_POINTS
from .render import label
from .session import SessionModel
from .zones import (
    BannerSection,
    DecisionSection,
    EventsSection,
    GameSection,
    LinkSection,
)


class Dashboard(
    BannerSection,
    GameSection,
    DecisionSection,
    LinkSection,
    EventsSection,
):
    """One fixed screen: situation, decision, link, events.  No tabs, no motion."""

    def __init__(self, tkinter, window, *, fullscreen=True):
        FONTS["mono"], FONTS["ui"] = _pick_families(tkinter)
        self.tk = tkinter
        self.window = window
        self.cache = DeltaCache()
        self.session = SessionModel()

        self._event_cells: list = []

        self._telemetry_ts = 0.0
        self._narrow = None
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

        # banner + measurements + the bottom strip + the diagram's own chrome
        self._reflow(total_w)
        bottom_h = EVENT_H + (110 if self._narrow else 0)
        reserved = BANNER_H + 146 + bottom_h + 130
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

    def _reflow(self, total_w):
        """Below 1600 px the bottom strip stacks instead of overflowing.

        Only the telemetry reorganises with the window; the numbered panels keep
        their cells and, per the guide, never move with their data.
        """

        narrow = total_w < 1600
        if narrow == self._narrow:
            return
        self._narrow = narrow
        events = self._events_panel.frame
        balance = self._balance_panel.frame
        events.grid_forget()
        balance.grid_forget()
        if narrow:
            self._strip.grid_columnconfigure(0, weight=1)
            self._strip.grid_columnconfigure(1, weight=0)
            events.grid(row=0, column=0, sticky="ew")
            balance.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        else:
            self._strip.grid_columnconfigure(0, weight=3)
            self._strip.grid_columnconfigure(1, weight=2)
            events.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
            balance.grid(row=0, column=1, sticky="nsew")

    def update(self, *, pilot, snapshot, decision, controls, worker, stale, error,
               log_stats=None) -> None:
        """Public entry point; the loop may also build an ``HmiFrame`` directly."""

        self.render(
            HmiFrame(
                pilot=pilot, snapshot=snapshot, decision=decision, controls=controls,
                worker=worker, stale=stale, error=error, log_stats=log_stats,
            )
        )

    def render(self, view) -> None:
        """One refresh, dispatched to the zones that own each part of the screen."""

        snapshot = view.snapshot
        decision = view.decision
        worker = view.worker
        stale = view.stale
        error = view.error
        log_stats = view.log_stats
        player = snapshot.player
        episode = snapshot.episode
        self.session.observe_vitals(player, decision)
        max_health = self.session.max_health
        critical = player.health <= int(max_health * 0.35)
        self.health.set(
            player.health, max_health,
            warn_at=int(max_health * 0.70), crit_at=int(max_health * 0.35),
        )
        self.armor.set(player.armor, 200, warn_at=100, crit_at=40)
        ammo = player.ammo
        self.ammo.set(min(ammo, 100), 100, "∞" if ammo >= 999 else str(ammo), crit_at=10)

        label(self.cache, "map", self.map_label, snapshot.map_name)
        label(self.cache, 
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
            label(self.cache, f"mes-{key}", self.measure_fields[key], value)
        label(self.cache, 
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
            self.session.account(decision)
        self._update_counters()
        self._update_telemetry(decision)
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

    def _update_telemetry(self, decision):
        """Redraw the session charts from the bounded buffers, on a throttle.

        The loop calls ``update`` every few ticks; the charts only need a few
        frames a second, so nothing here costs the 60 Hz loop or the worker.
        """

        now = time.monotonic()
        changed = self.cache.changed("telemetry-decisions", self.session.decisions)
        if not changed and (now - self._telemetry_ts) < TELEMETRY_INTERVAL:
            return
        self._telemetry_ts = now
        p50 = _percentile(self.session.latencies, 0.50)
        p95 = _percentile(self.session.latencies, 0.95)
        self.latency_spark.render(self.session.latencies[-TELEMETRY_POINTS:], p50, p95)
        self.confidence_spark.render(
            {axis: list(values) for axis, values in self.session.confidence.items()}
        )
        self.intervention.render(self.session.interventions, self.session.rule_counts)
        self.action_bars.render(self.session.movement_counts(), self.session.interaction_counts())
        self.vital_trace.render(
            self.session.health, self.session.ammo, self.session.intervention_marks, self.session.max_health
        )
        self.consumption.render(
            self.session.tokens_in, self.session.tokens_out, self.session.cost, self.session.decisions
        )
        self.policy_delta.render(self.session.previous_controls, self.session.applied_controls)
