"""The panel, as text.  Pure layout: no terminal, no curses, no I/O.

Every box returns lines of ``(text, key)`` runs, where the key is one of the
semantic colours in ``theme.py``.  That keeps the colours in one home and makes
the whole presentation testable with pytest: given a frame, the same lines come
out every time.

The data itself is not re-derived here — the confidence bands, the clipping and
the axis order come from ``panel/format.py`` and ``panel/layout.py``, and the
session series from ``panel/session.py``.  Same source of truth as the Tk panel.
"""

from __future__ import annotations

from ..panel.format import _clip, _confidence_level, _controls_text, _percentile
from ..panel.layout import AXES

Run = tuple[str, str]  # (text, colour key)
Line = list[Run]

UPPER_HALF = "\u2580"  # the top half block: two pixels per cell
FULL = "\u2588"
SHADE = "\u2591"

_LEVEL_KEYS = {"ok": "ok", "off": "off", "warn": "warn", "alarm": "alarm"}


def line(text: str, key: str = "static") -> Line:
    return [(str(text), key)]


def bar(fraction: float, width: int, *, filled: str = FULL, empty: str = SHADE) -> str:
    fraction = 0.0 if fraction < 0 else 1.0 if fraction > 1 else float(fraction)
    filled_cells = int(round(fraction * width))
    return filled * filled_cells + empty * (width - filled_cells)


def fit(line: Line, width: int) -> Line:
    """Trim a line to a column, exactly like an HMI cell: the value is clipped."""

    out: Line = []
    used = 0
    for text, key in line:
        room = width - used
        if room <= 0:
            break
        text = text[:room]
        out.append((text, key))
        used += len(text)
    return out


def fit_all(lines, width: int) -> list[Line]:
    return [fit(item, width) for item in lines]


def _head_level(value) -> str:
    return _confidence_level(value)[1]


# ── boxes ────────────────────────────────────────────────────────────────────
def banner(frame, width: int) -> Line:
    snapshot = frame.snapshot
    episode = snapshot.episode
    if frame.error:
        state, key = "SIN COMUNICACIÓN", "alarm"
    elif frame.stale > 3:
        state, key = f"DATOS OBSOLETOS x{frame.stale}", "warn"
    elif episode.dead:
        state, key = "MUERTO", "alarm"
    elif episode.finished:
        state, key = "NIVEL COMPLETADO", "ok"
    else:
        state, key = "EN MARCHA", "value"
    head = (
        f"SCADA+IA+JEV+DOOM  {snapshot.map_name}  TICK {snapshot.tick}  "
        f"T+{episode.game_time:7.1f}s  DEC {frame.applied}  "
        f"OBS {frame.stale}  HECHAS {frame.completed}/{frame.replaced}  "
    )
    return fit(line(head, "title") + [(state, key)] + line(f"  # {frame.tick}", "static"), width)


def measures(frame, width: int) -> list[Line]:
    player = frame.snapshot.player
    episode = frame.snapshot.episode
    health_key = "alarm" if player.health <= 35 else "warn" if player.health <= 70 else "value"
    rows = [
        line(
            f"SALUD {player.health:>4}  ARMADURA {player.armor:>4}  "
            f"MUNICION {'inf' if player.ammo >= 999 else player.ammo:>4}",
            health_key,
        ),
        line(
            f"ARMA {_clip(player.weapon_name, 14):<14}  PUNTOS {episode.kills:>3}  "
            f"OBJETOS {episode.items:>3}",
        ),
        line(
            f"DANO {episode.damage_received:>4}  SECTORES {episode.unique_sectors:>3}  "
            f"PARADO {episode.stuck_ticks:>3}/{episode.idle_ticks}",
        ),
    ]
    return fit_all(rows, width)


def decision(frame, width: int, *, bar_width: int = 16) -> list[Line]:
    decision = frame.decision
    if decision is None:
        return [line("esperando la primera decision", "off")]
    rows: list[Line] = []
    muted = bool(frame.error) or frame.stale > 3
    for name, title, tag in AXES:
        values = (decision.probabilities or {}).get(name)
        if not values:
            continue
        best = max(values, key=values.__getitem__)
        confidence = (decision.confidence or {}).get(name)
        if muted:
            word, level = "SIN DATO", "off"
        else:
            word, level = _confidence_level(confidence)
        head = f"{tag:<4}{title:<11}"
        choice = f"{(best.upper().replace('_', ' ')):<16}"
        badge = f" {word}" + (f" {confidence:.2f}" if confidence is not None else "")
        rows.append(
            line(head, "static")
            + [(choice, "off" if muted else "value"), (badge, level)]
        )
        rows.append(
            line("    ")
            + [(bar(max(0.0, values[best]), bar_width), level)]
            + line(f" {values[best]:.2f}", "value")
        )
        others = "  ".join(
            f"{name_} {value:.2f}" for name_, value in values.items() if name_ != best
        )
        rows.append(line("    " + _clip(f"ALT {others}", max(10, width - 4)), "off"))
    return fit_all(rows, width)


def guard(frame, width: int) -> list[Line]:
    decision = frame.decision
    proposed = _controls_text(decision.proposed_controls if decision else None)
    applied = _controls_text(decision.applied_controls if decision else None)
    events = decision.assistance_events if decision else ()
    corrected = bool(proposed and applied and proposed != applied)
    flag = f"INTERVINO x{len(events)}" if events else "SIN INTERVENCION"
    rows = [
        line(f"{flag:<22}", "warn" if events else "ok"),
        line(f"PROPUESTO {_clip(proposed or 'sin dato', width - 12)}", "static"),
        line(
            f"APLICADO  {_clip(applied or 'sin dato', width - 12)}",
            "warn" if corrected else "value",
        ),
    ]
    for event in list(events)[:2]:
        rows.append(line(_clip(f"  {event.kind}: {event.proposed}->{event.applied}", width), "warn"))
    return fit_all(rows, width)


def why(frame, width: int) -> list[Line]:
    decision = frame.decision
    rows = []
    for name, title, _tag in AXES:
        text = "-" if decision is None else decision.observations.get(name, "-")
        rows.append(
            line(f"{title:<11}", "static")
            + [(_clip(str(text).replace(">", "="), max(8, width - 12)), "value")]
        )
    return fit_all(rows, width)


def strategy(frame, width: int) -> list[Line]:
    block = getattr(frame.decision, "strategy", None) if frame.decision else None
    if not block:
        return [line("sin estrategia en este prompt", "off")]
    rows = [
        line(
            f"{block['mission']} / prioridad {block['priority']} / "
            f"{'mover' if block['must_move'] else 'aguantar'} "
            f"{block['hold_streak']}/{block['max_hold_streak']}",
            "value",
        ),
        line(_clip(str(block.get("status", "")), width), "static"),
    ]
    for step in list(block.get("plan", ()))[:3]:
        rows.append(line(_clip(f"  - {step}", width), "off"))
    return fit_all(rows, width)


def link(frame, width: int) -> list[Line]:
    decision = frame.decision
    if decision is None:
        return [line("sin datos del enlace todavia", "off")]
    usage = (decision.input_tokens or {}).get("request", 0)
    # A remote frame carries the two counts instead of the raw request payload,
    # which would be kilobytes on every poll.
    keys = getattr(decision, "request_keys", None)
    if keys is None:
        keys = len(decision.request_state or {})
    questions = getattr(decision, "request_questions_count", None)
    if questions is None:
        questions = len(decision.request_questions or {})
    rows = [
        line(
            f"MODELO {decision.model_id}  PROMPT {decision.prompt_version}",
            "value",
        ),
        line(f"TOKENS {usage}  CLAVES {keys}  PREGUNTAS {questions}"),
        line(f"PETICION {decision.request_ms:.0f} ms  DECISION {decision.decision_ms:.0f} ms"),
        line(f"EDAD {frame.tick - decision.observation_tick} ticks  "
             f"LLAMADAS {decision.prediction_calls} / {decision.execution}"),
        line(
            "BITACORA "
            + (
                f"{frame.log_stats['sent']} env / {frame.log_stats['dropped']} caidos"
                if frame.log_stats
                else "desactivada"
            ),
            "static",
        ),
    ]
    return fit_all(rows, width)


def telemetry(model, width: int) -> list[Line]:
    p50 = _percentile(model.latencies, 0.50)
    p95 = _percentile(model.latencies, 0.95)
    rows = [
        line(
            f"LATENCIA p50 {p50:.0f}  p95 {p95:.0f}  n {model.samples}"
            if p50 is not None and p95 is not None
            else "LATENCIA sin serie",
            "static",
        ),
        line(f"COSTE ${model.cost:.5f}  TOKENS {model.tokens}", "static"),
    ]
    for name, title, tag in AXES:
        values = model.confidence.get(name)
        if not values:
            continue
        last = values[-1]
        rows.append(
            line(f"{tag} ", "static")
            + [(bar(last, max(6, width - 12)), "warn" if last < 0.4 else "value")]
            + line(f" {last:.2f}", "value")
        )
    total = len(model.interventions)
    hit = sum(model.interventions)
    rows.append(line(f"GUARDIA {hit}/{total} intervenciones", "static"))
    return fit_all(rows, width)


def events(model, width: int, rows: int = 4) -> list[Line]:
    out = []
    for item in list(model.history)[:rows]:
        confidence = item["confidence"]
        level = _head_level(confidence)
        flag = "INTERVINO" if item["guard"] else "APLICADO"
        out.append(
            line(f"#{item['n']:04d} {item['tick']:>6} ", "off")
            + [(f"{item['movement']:<14}", "value")]
            + [(f"{item['aim']:<6}{item['interaction']:<8}", "value")]
            + [(f"{confidence:.2f}" if confidence is not None else "  - ", level)]
            + line(f" {item['ms']:>5.0f}ms ", "static")
            + [(f"{flag:<10}", "warn" if item["guard"] else "off")]
            + line(f" {_clip(item['guard'], max(8, width - 60))}", "static")
        )
    if not out:
        out.append(line("sin decisiones todavia", "off"))
    return fit_all(out, width)


def balance(model, width: int) -> list[Line]:
    movements = model.movement_counts().most_common(3)
    actions = model.interaction_counts().most_common(3)
    return fit_all([
        line("MOV " + ("  ".join(f"{name} {count}" for name, count in movements) or "-")),
        line("ACC " + ("  ".join(f"{name} {count}" for name, count in actions) or "-")),
        line(f"COSTE ${model.cost:.5f}  DECISIONES {model.decisions}", "static"),
    ], width)


# ── the game view ────────────────────────────────────────────────────────────
def game_art(rgb, src_w: int, src_h: int, cols: int, rows: int, basic) -> list[list[tuple[int, int, str]]]:
    """Two engine pixels per cell, painted as upper half blocks.

    ``basic(r, g, b)`` quantises a pixel to one of the eight basic colours, which
    keeps the terminal colour pairs bounded (8x8) on any terminal.
    """

    if not rgb or cols < 4 or rows < 2:
        return []
    art = []
    for row in range(rows):
        top_y = min(src_h - 1, (2 * row) * src_h // (2 * rows))
        bottom_y = min(src_h - 1, (2 * row + 1) * src_h // (2 * rows))
        cells = []
        for col in range(cols):
            x = min(src_w - 1, int((col + 0.5) * src_w / cols))
            top = (top_y * src_w + x) * 3
            bottom = (bottom_y * src_w + x) * 3
            cells.append(
                (
                    basic(rgb[top], rgb[top + 1], rgb[top + 2]),
                    basic(rgb[bottom], rgb[bottom + 1], rgb[bottom + 2]),
                    UPPER_HALF,
                )
            )
        art.append(cells)
    return art
