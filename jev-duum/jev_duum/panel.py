"""Tk gameplay loop and external diagnostics for asynchronous Jev control."""

from __future__ import annotations

import statistics
import time
from dataclasses import replace

from .actions import controls_to_mask, ensure_usable_weapon, settle_assisted_controls
from .snapshot import SnapshotBuilder
from .types import DuumControls
from .worker import DecisionWorker


def _distribution(values: dict[str, float]) -> str:
    return "  ".join(f"{name} {value:.2f}" for name, value in values.items())


def _probability_lines(title, values):
    lines = [title]
    for name, value in values.items():
        filled = min(12, max(0, round(value * 12)))
        bar = "█" * filled + "·" * (12 - filled)
        lines.append(f"  {name:<13} {bar} {value:>4.2f}")
    return lines


def advance_completed_level(app) -> bool:
    """Advance Duum's intermission through the same public Space key as a player."""

    if app.finish is None:
        return False
    app.key(32, 0, False)
    return True


class Meter:
    def __init__(self, tkinter, parent, label, color):
        self.frame = tkinter.Frame(parent, bg="#17191f")
        self.frame.pack(fill="x", padx=16, pady=(4, 8))
        self.name = tkinter.Label(
            self.frame,
            text=label.upper(),
            bg="#17191f",
            fg="#9298a6",
            font=("Menlo", 10, "bold"),
        )
        self.name.pack(anchor="w")
        self.value = tkinter.Label(
            self.frame,
            text="0",
            bg="#17191f",
            fg="#f2f4f8",
            font=("Menlo", 12, "bold"),
        )
        self.value.pack(anchor="e")
        self.canvas = tkinter.Canvas(
            self.frame,
            width=188,
            height=10,
            bg="#292d36",
            highlightthickness=0,
        )
        self.canvas.pack(fill="x")
        self.fill = self.canvas.create_rectangle(0, 0, 0, 10, fill=color, outline="")

    def set(self, value, maximum, text=None):
        fraction = 0 if maximum <= 0 else min(1.0, max(0.0, value / maximum))
        self.canvas.coords(self.fill, 0, 0, 188 * fraction, 10)
        self.value.configure(text=str(value) if text is None else text)


class Dashboard:
    """One-window layout: stats left, untouched game center, Jev metrics right."""

    def __init__(self, tkinter, window):
        root = window.root
        root.configure(bg="#0d0f14")
        root.resizable(True, True)
        window.tkcv.pack_forget()

        self.left = tkinter.Frame(root, width=230, bg="#17191f")
        self.left.grid(row=0, column=0, sticky="nsew")
        self.left.pack_propagate(False)
        window.tkcv.configure(
            highlightthickness=3,
            highlightbackground="#444b58",
            highlightcolor="#65d8ff",
            bg="black",
        )
        window.tkcv.grid(row=0, column=1, padx=12, pady=12)
        self.right = tkinter.Frame(root, width=470, bg="#12141a")
        self.right.grid(row=0, column=2, sticky="nsew")
        self.right.pack_propagate(False)
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(1, weight=1)

        tkinter.Label(
            self.left,
            text="DUUM",
            bg="#17191f",
            fg="#65d8ff",
            font=("Menlo", 22, "bold"),
        ).pack(anchor="w", padx=16, pady=(18, 0))
        tkinter.Label(
            self.left,
            text="Jev local pilot",
            bg="#17191f",
            fg="#9298a6",
            font=("Menlo", 10),
        ).pack(anchor="w", padx=16, pady=(0, 18))
        self.health = Meter(tkinter, self.left, "Health", "#ef5350")
        self.armor = Meter(tkinter, self.left, "Armor", "#42a5f5")
        self.ammo = Meter(tkinter, self.left, "Ammo", "#ffca28")
        self.stats = tkinter.Label(
            self.left,
            text="",
            justify="left",
            anchor="nw",
            bg="#17191f",
            fg="#d8dbe2",
            font=("Menlo", 11),
        )
        self.stats.pack(fill="x", padx=16, pady=10)

        tkinter.Label(
            self.right,
            text="JEV DECISIONS",
            bg="#12141a",
            fg="#8ee8a8",
            font=("Menlo", 16, "bold"),
        ).pack(anchor="w", padx=16, pady=(16, 0))
        self.mode = tkinter.Label(
            self.right,
            text="",
            bg="#12141a",
            fg="#9298a6",
            font=("Menlo", 9),
        )
        self.mode.pack(anchor="w", padx=16, pady=(2, 10))
        self.text = tkinter.Text(
            self.right,
            width=59,
            height=38,
            wrap="word",
            bg="#12141a",
            fg="#eeeeee",
            insertbackground="#eeeeee",
            selectbackground="#34495e",
            relief="flat",
            font=("Menlo", 10),
            padx=16,
            pady=4,
        )
        self.text.pack(fill="both", expand=True)
        self.text.configure(state="disabled")

    def update(self, *, pilot, snapshot, decision, controls, worker, stale, error):
        self.health.set(snapshot.player.health, 100)
        self.armor.set(snapshot.player.armor, 200)
        ammo = snapshot.player.ammo
        self.ammo.set(min(ammo, 100), 100, "∞" if ammo >= 999 else str(ammo))
        self.stats.configure(
            text=(
                f"MAP     {snapshot.map_name}\n"
                f"TIME    {snapshot.episode.game_time:6.1f}s\n"
                f"WEAPON  {snapshot.player.weapon_name}\n"
                f"ENEMIES {snapshot.episode.live_enemies}\n"
                f"KILLS   {snapshot.episode.kills}\n"
                f"ITEMS   {snapshot.episode.items}\n"
                f"DAMAGE  {snapshot.episode.damage_received}\n"
                f"SECTORS {snapshot.episode.unique_sectors}"
            )
        )
        self.mode.configure(
            text=f"{pilot} · online: api.typesafe.ai · semantic state only · no pixels"
        )
        lines = [
            f"TICK {snapshot.tick}    GAME {snapshot.episode.game_time:.2f}s",
            f"worker busy={worker.busy} completed={worker.stats.completed} "
            f"replaced={worker.stats.replaced} stale={stale}",
        ]
        if snapshot.episode.finished:
            lines.extend(("", "LEVEL COMPLETE · advancing shortly…"))
        if error:
            lines.extend(("", f"MODEL ERROR: {error}"))
        elif decision is None:
            lines.extend(("", "Warming model / waiting for first complete decision…"))
        else:
            age = snapshot.tick - decision.observation_tick
            conf = "  ".join(
                f"{name} {value:.2f}" if value is not None else f"{name} n/a"
                for name, value in decision.confidence.items()
            )
            lines.extend(("", *_probability_lines("MOVEMENT", decision.probabilities["movement"])))
            lines.extend(("", *_probability_lines("AIM", decision.probabilities["aim"])))
            lines.extend(
                ("", *_probability_lines("INTERACTION", decision.probabilities["interaction"]))
            )
            lines.extend(
                (
                    "",
                    f"model {decision.model_id}",
                    f"confidence {conf}",
                    f"proposed: {decision.proposed_controls.movement} / "
                    f"{decision.proposed_controls.aim} / "
                    f"{decision.proposed_controls.interaction}",
                    f"applied:  {decision.applied_controls.movement} / "
                    f"{decision.applied_controls.aim} / "
                    f"{decision.applied_controls.interaction}",
                    f"observation tick {decision.observation_tick}  "
                    f"application tick {decision.application_tick}  age {age}",
                    f"request {decision.request_ms:.1f} ms  "
                    f"complete decision {decision.decision_ms:.1f} ms  "
                    f"tokens {decision.input_tokens.get('request', 0)}  "
                    f"cost ${decision.cost_usd:.6f}",
                    f"assistance: "
                    f"{', '.join(event.kind for event in decision.assistance_events) or 'none'}",
                    "",
                    "MOVEMENT STATE",
                    decision.observations["movement"],
                    "",
                    "AIM STATE",
                    decision.observations["aim"],
                    "",
                    "INTERACTION STATE",
                    decision.observations["interaction"],
                )
            )
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(lines))
        self.text.configure(state="disabled")


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
            if (
                age <= max_stale_ticks
                and result.observation_tick >= minimum_observation_tick
            ):
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
