"""Mockup (offline, $0) of a decision-first "stage" for a live AI talk.

The shipped inspector puts the game first and tucks the model's decision into a
side tab.  For a congress the priority is the opposite: the *decision* is the
protagonist, readable from the back of the room, with the game demoted to a
small "what the agent sees" picture-in-picture.

This is a design artifact, not the product: it builds a static layout from one
real snapshot plus a constant fake model answer, so it never touches the network
or the gameplay loop.

    python3 tools/decision_stage_mockup.py --allow-any-commit --out artifacts/ui-audit

Screenshots need Pillow; the game frame is drawn with pure Tk (no extra deps).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("JEV_NO_LOG", "1")

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
for path in (str(ROOT), str(TOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import tkinter as tk  # noqa: E402
from tkinter import font as tkfont  # noqa: E402

from preview_panel import FakeJevClient  # noqa: E402

from jev_duum.controller import JevDuumController  # noqa: E402
from jev_duum.integration import load_duum  # noqa: E402
from jev_duum.overlays import MiniMap  # noqa: E402
from jev_duum.snapshot import SnapshotBuilder  # noqa: E402
from jev_duum.types import AIMS, INTERACTIONS, MOVEMENTS  # noqa: E402
from jev_duum.wad import default_wad_path, resolve_wad  # noqa: E402
from jev_duum.world_readout import read_world  # noqa: E402

# ── palette ──────────────────────────────────────────────────────────────────
BG = "#070910"
PANEL = "#0d1119"
CARD = "#161b27"
CARD2 = "#1d2534"
BORDER = "#2b3548"
TRACK = "#232c3d"
TEXT = "#eef2fa"
MUTED = "#8b93a7"
DIM = "#5b6376"
ACCENT = "#65d8ff"
GREEN = "#8ee8a8"
AMBER = "#ffb74d"
RED = "#ef5350"
GOLD = "#ffca28"
VIOLET = "#b388ff"

FAM = {"sans": "DejaVu Sans", "mono": "DejaVu Sans Mono"}

AXES = (
    ("MOVIMIENTO", "movement", MOVEMENTS, ACCENT),
    ("APUNTADO", "aim", AIMS, VIOLET),
    ("ACCIÓN", "interaction", INTERACTIONS, GREEN),
)


def pick_families():
    try:
        families = set(tkfont.families())
    except Exception:  # pragma: no cover - headless fallback
        families = set()

    def pick(*candidates):
        for candidate in candidates:
            if candidate in families:
                return candidate
        return "TkDefaultFont"

    FAM["sans"] = pick("DejaVu Sans", "Noto Sans", "Helvetica")
    FAM["mono"] = pick("DejaVu Sans Mono", "Noto Mono", "Courier")


def sans(size, weight="normal"):
    return (FAM["sans"], size, weight)


def mono(size, weight="normal"):
    return (FAM["mono"], size, weight)


def card(parent, *, bg=CARD, border=BORDER, pad=16, **pack):
    frame = tk.Frame(parent, bg=bg, highlightbackground=border, highlightthickness=1)
    frame.pack(**pack)
    body = tk.Frame(frame, bg=bg)
    body.pack(fill="both", expand=True, padx=pad, pady=pad)
    return frame, body


class ChoiceBar:
    """The hero widget: the chosen action, its confidence and a stacked bar."""

    def __init__(self, parent, title, accent):
        self.accent = accent
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(0, 16))
        head = tk.Frame(row, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text=title, bg=CARD, fg=MUTED, font=sans(11, "bold")).pack(side="left")
        self.choice = tk.Label(head, text="—", bg=CARD, fg=accent, font=sans(32, "bold"))
        self.choice.pack(side="left", padx=(18, 0))
        self.conf = tk.Label(
            head, text="", bg=CARD2, fg=MUTED, font=mono(13, "bold"), padx=10, pady=3
        )
        self.conf.pack(side="right")
        self.canvas = tk.Canvas(row, height=24, bg=TRACK, highlightthickness=0, bd=0)
        self.canvas.pack(fill="x", pady=(10, 5))
        self.breakdown = tk.Label(row, text="", bg=CARD, fg=MUTED, font=mono(10), anchor="w")
        self.breakdown.pack(fill="x")

    def set(self, distribution, confidence):
        order = list(distribution)
        best = max(order, key=distribution.__getitem__)
        self.choice.configure(text=best.upper().replace("_", " "))
        if confidence is None:
            self.conf.configure(text="conf n/a", bg=CARD2, fg=MUTED)
        else:
            tone = GREEN if confidence >= 0.7 else AMBER if confidence >= 0.4 else RED
            self.conf.configure(text=f"conf {confidence:.2f}", bg=tone, fg="#0a1410")
        width = max(200, self.canvas.winfo_width())
        self.canvas.delete("all")
        # Draw the stacked bar left→right, the chosen segment bright.
        x = 0.0
        for name in order:
            segment = width * max(0.0, float(distribution[name]))
            fill = self.accent if name == best else TRACK
            self.canvas.create_rectangle(x, 0, x + segment, 24, fill=fill, outline=CARD)
            x += segment
        if x < width:  # rounding slack
            self.canvas.create_rectangle(x, 0, width, 24, fill=TRACK, outline=CARD)
        parts = "    ".join(
            f"{name}={distribution[name]:.2f}" for name in order if name != best
        )
        self.breakdown.configure(text=f"alternativas:   {parts}")


class StatBox:
    def __init__(self, parent, label, color):
        self.color = color
        box = tk.Frame(parent, bg=CARD2, highlightbackground=BORDER, highlightthickness=1)
        box.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.value = tk.Label(box, text="—", bg=CARD2, fg=color, font=mono(28, "bold"))
        self.value.pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(box, text=label.upper(), bg=CARD2, fg=MUTED, font=sans(9, "bold")).pack(
            anchor="w", padx=12, pady=(0, 10)
        )

    def set(self, value, color=None):
        self.value.configure(text=str(value), fg=color or self.color)


def eyebrow(parent, text, color=MUTED, size=10):
    return tk.Label(
        parent, text=text.upper(), bg=CARD, fg=color, font=sans(size, "bold"), anchor="w"
    )


def row(parent, label, value, *, color=TEXT, width=13, wrap=0):
    line = tk.Frame(parent, bg=CARD)
    line.pack(fill="x", pady=1)
    tk.Label(line, text=label, width=width, anchor="w", bg=CARD, fg=MUTED, font=mono(10)).pack(
        side="left"
    )
    value_label = tk.Label(
        line, text=value, anchor="w", justify="left", bg=CARD, fg=color, font=mono(10, "bold"),
    )
    if wrap:
        value_label.configure(wraplength=wrap)
    value_label.pack(side="left", fill="x", expand=True)
    return value_label


def capture_frame(modules, wad, map_name):
    """One offline frame of the game + the snapshot that describes it."""

    app = modules.engine.Duum()
    window = modules.frontend.Window(app, width=320, height=200, scale=1, title="capture")
    app.build(window.cv)
    if app.err:
        raise SystemExit(f"Duum could not start: {app.err}")
    if app.level != map_name:
        app.load_level(map_name)
    for _ in range(3):
        window._frame_once()
    ppm = window.hdr + bytes(window.cv.buf)
    snapshot = SnapshotBuilder(app, modules.engine).build(0)
    window._close()
    return ppm, snapshot


def build_stage(root, ppm, snapshot, readout, decision):
    metrics = decision.input_tokens.get("request", 0)
    health, armor, ammo = snapshot.player.health, snapshot.player.armor, snapshot.player.ammo
    strategy = decision.strategy or {}

    # -- header --------------------------------------------------------------
    header = tk.Frame(root, bg=BG)
    header.pack(fill="x", padx=22, pady=(18, 10))
    tk.Label(header, text="JEV", bg=BG, fg=ACCENT, font=sans(30, "bold")).pack(side="left")
    tk.Label(
        header, text="  ·  cómo decide la IA", bg=BG, fg=MUTED, font=sans(18)
    ).pack(side="left")
    right = tk.Frame(header, bg=BG)
    right.pack(side="right")
    tk.Label(
        right,
        text=f"decisión #{1284:04d}    ·    {decision.decision_ms:.0f} ms    ·    "
        f"${decision.cost_usd:.5f}    ·    {metrics} tokens",
        bg=BG, fg=GOLD, font=mono(14, "bold"),
    ).pack(anchor="e")
    tk.Label(
        right, text="live · api.typesafe.ai · estado semántico, sin píxeles",
        bg=BG, fg=DIM, font=mono(10),
    ).pack(anchor="e")

    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True, padx=22, pady=(0, 18))
    left = tk.Frame(body, bg=BG, width=470)
    left.pack(side="left", fill="y")
    left.pack_propagate(False)
    middle = tk.Frame(body, bg=BG)
    middle.pack(side="left", fill="both", expand=True, padx=16)
    right_col = tk.Frame(body, bg=BG, width=430)
    right_col.pack(side="left", fill="y")
    right_col.pack_propagate(False)

    # -- left: perception ----------------------------------------------------
    _, lb = card(left, pad=(14, 12), fill="x")
    eyebrow(lb, "entrada · lo que la IA percibe", ACCENT, 11).pack(anchor="w", pady=(0, 10))
    stats = tk.Frame(lb, bg=CARD)
    stats.pack(fill="x")
    hp = StatBox(stats, "vida", GREEN)
    ar = StatBox(stats, "armadura", ACCENT)
    am = StatBox(stats, "munición", GOLD)
    hp.set(health, RED if health <= 35 else GREEN)
    ar.set(armor)
    am.set("∞" if ammo >= 999 else ammo)

    _, gb = card(left, pad=(14, 12), fill="x", pady=(12, 0))
    eyebrow(gb, "vista del agente (segundo plano)", MUTED, 10).pack(anchor="w", pady=(0, 8))
    image = tk.PhotoImage(data=ppm)
    tk.Label(gb, image=image, bd=0).pack()
    gb.image = image  # keep a reference
    mini = MiniMap(tk, gb, width=398, height=150)
    mini.canvas.pack(fill="x", pady=(10, 0))
    mini.render(snapshot, readout)

    _, tb = card(left, pad=(14, 12), fill="x", pady=(12, 0))
    eyebrow(tb, "amenazas cercanas", RED, 10).pack(anchor="w", pady=(0, 8))
    threats = readout.top_threats[:2] if readout.available else ()
    if threats:
        for threat in threats:
            color = RED if threat["line_of_sight"] else AMBER
            row(
                tb, f"rumbo {threat['bearing_degrees']}°",
                f"{threat['distance_px']} px · score {threat['threat_score']:.2f} · "
                f"{'LOS' if threat['line_of_sight'] else 'sin LOS'}",
                color=color, width=13,
            )
    else:
        row(tb, "—", "sin amenazas relevantes", color=MUTED)

    _, ob = card(left, pad=(14, 12), fill="x", pady=(12, 0))
    eyebrow(ob, "objetivo", GREEN, 10).pack(anchor="w", pady=(0, 8))
    target = (readout.recommended_target or {}) if readout.available else {}
    mission = strategy.get("mission_statement") or "—"
    row(ob, "misión", mission, color=GREEN, width=13, wrap=300)
    row(ob, "pickup", str(target.get("kind", "—")))
    route = f"{readout.route_steps} salas" if readout.available else "—"
    if readout.available and readout.route_rooms:
        route += " → " + readout.route_rooms[0]
    row(ob, "ruta", route)
    row(ob, "sala", readout.room or "—")

    # -- middle: the decision ------------------------------------------------
    _, mb = card(middle, pad=(20, 18), fill="both", expand=True)
    eyebrow(mb, "la decisión de la IA", GREEN, 13).pack(anchor="w")
    tk.Label(
        mb, text="una sola petición · tres preguntas tipadas · probabilidades",
        bg=CARD, fg=DIM, font=mono(10),
    ).pack(anchor="w", pady=(2, 16))
    bars = {}
    for title, axis, _labels, accent in AXES:
        bar = ChoiceBar(mb, title, accent)
        bar.set(decision.probabilities[axis], decision.confidence.get(axis))
        bars[axis] = bar

    # guard intervention
    events = decision.assistance_events
    banner = tk.Frame(mb, bg="#2a2110", highlightbackground=AMBER, highlightthickness=1)
    banner.pack(fill="x", pady=(4, 0))
    if events:
        tk.Label(
            banner, text="INTERVENCIÓN DEL GUARDIA DETERMINISTA", bg="#2a2110", fg=AMBER,
            font=sans(10, "bold"),
        ).pack(anchor="w", padx=12, pady=(8, 2))
        for event in events:
            tk.Label(
                banner,
                text=f"el modelo dijo «{event.proposed}» → aplicado «{event.applied}» · {event.reason}",
                bg="#2a2110", fg=TEXT, font=mono(10), anchor="w", justify="left",
                wraplength=820,
            ).pack(anchor="w", padx=12, pady=(0, 6))
    else:
        tk.Label(
            banner, text="sin intervenciones · se aplicó exactamente lo que propuso el modelo",
            bg="#2a2110", fg=MUTED, font=mono(10),
        ).pack(anchor="w", padx=12, pady=10)

    # timeline of recent decisions
    _, tl = card(mb, pad=(20, 12), fill="x", pady=(16, 0))
    eyebrow(tl, "ritmo de decisión · últimas 24 (ejemplo)", VIOLET, 10).pack(anchor="w", pady=(0, 8))
    strip = tk.Canvas(tl, height=34, bg=CARD, highlightthickness=0, bd=0)
    strip.pack(fill="x")
    timeline_colors = [ACCENT, GREEN, GOLD, VIOLET, ACCENT, RED, GREEN, GOLD]
    for index in range(24):
        color = timeline_colors[index % len(timeline_colors)]
        height = 10 + (index * 7) % 22
        strip.create_rectangle(index * 34 + 2, 34 - height, index * 34 + 26, 34, fill=color, outline="")

    # -- right: why + metrics ------------------------------------------------
    _, wb = card(right_col, pad=(14, 12), fill="x")
    eyebrow(wb, "por qué · razonamiento", VIOLET, 11).pack(anchor="w", pady=(0, 10))
    tk.Label(
        wb,
        text=f"{strategy.get('mission', '—')}  ·  prioridad {strategy.get('priority', '—')}",
        bg=CARD, fg=TEXT, font=mono(11, "bold"), anchor="w",
    ).pack(anchor="w")
    tk.Label(
        wb, text=strategy.get("status", "—"), bg=CARD, fg=MUTED, font=mono(10),
        anchor="w", justify="left", wraplength=380,
    ).pack(anchor="w", pady=(4, 8))
    for step in (strategy.get("plan") or ())[:4]:
        tk.Label(
            wb, text=f"· {step}", bg=CARD, fg=TEXT, font=mono(10),
            anchor="w", justify="left", wraplength=380,
        ).pack(anchor="w")

    _, kb = card(right_col, pad=(14, 12), fill="x", pady=(12, 0))
    eyebrow(kb, "métricas", GOLD, 10).pack(anchor="w", pady=(0, 8))
    row(kb, "latencia", f"{decision.decision_ms:.0f} ms")
    row(kb, "tokens", f"{metrics} (entrada)")
    row(kb, "coste", f"${decision.cost_usd:.6f}")
    row(kb, "acumulado", "$0.04182")
    row(kb, "modelo", decision.model_id)
    row(kb, "prompt", decision.prompt_version)

    _, hb = card(right_col, pad=(14, 12), fill="both", expand=True, pady=(12, 0))
    eyebrow(hb, "historial reciente (ejemplo)", ACCENT, 10).pack(anchor="w", pady=(0, 8))
    history = [
        ("#1284", "strafe_left · right · fire", GREEN),
        ("#1283", "forward · straight · fire", ACCENT),
        ("#1282", "strafe_left · right · neither", AMBER),
        ("#1281", "forward · left · use", VIOLET),
        ("#1280", "hold · straight · neither", MUTED),
        ("#1279", "strafe_right · right · fire", GREEN),
    ]
    for tag, action, color in history:
        line = tk.Frame(hb, bg=CARD)
        line.pack(fill="x", pady=2)
        tk.Label(line, text=tag, bg=CARD, fg=color, font=mono(10, "bold")).pack(side="left")
        tk.Label(line, text=action, bg=CARD, fg=TEXT, font=mono(10)).pack(side="right")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="decision_stage_mockup", description=__doc__)
    parser.add_argument("--duum-path", type=Path, default=ROOT.parent / "duum")
    parser.add_argument("--wad", type=Path, default=default_wad_path())
    parser.add_argument("--map", dest="map_name", default="E1M1")
    parser.add_argument("--size", default="1760x990")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "ui-audit")
    parser.add_argument("--allow-any-commit", action="store_true")
    args = parser.parse_args(argv)
    width, height = (int(part) for part in args.size.lower().split("x"))

    try:
        wad = resolve_wad(args.wad)
        modules = load_duum(args.duum_path, frontend=True, require_pinned=not args.allow_any_commit)
    except Exception as error:
        parser.error(str(error))

    modules.desktop.use_clock(None)
    modules.desktop.set_keys(0)
    modules.desktop.mount(str(wad.path))

    ppm, snapshot = capture_frame(modules, wad, args.map_name)
    controller = JevDuumController(
        client=FakeJevClient(), assisted=True, prompt_version="v3w", pilot="jev-assisted"
    )
    decision = controller.decide(snapshot).with_application_tick(1)
    readout = read_world(snapshot)

    root = tk.Tk()
    pick_families()
    root.configure(bg=BG)
    root.title("JEV · pantalla de decisión (mockup offline)")
    root.geometry(f"{width}x{height}+0+0")
    build_stage(root, ppm, snapshot, readout, decision)
    root.update_idletasks()
    root.update()

    args.out.mkdir(parents=True, exist_ok=True)
    try:
        import time

        from PIL import ImageGrab

        time.sleep(0.4)
        root.update()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        path = args.out / "10-decision-stage.png"
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
        print(f"saved {path}")
    except ImportError:
        print("Pillow not installed; showing the mockup window instead.", file=sys.stderr)
        root.after(1500, root.destroy)
        root.mainloop()
        return 0
    root.destroy()
    print("offline mockup: no network, model answered by a local fake client.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
