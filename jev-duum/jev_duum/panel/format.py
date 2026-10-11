"""Pure helpers: confidence bands, thresholds, clipping and the small text
renderings the HMI builds out of a decision.

Nothing here touches a widget or the session: given the same input these
functions always return the same value, which is what the panel's tests pin."""

from __future__ import annotations

import re

from ..theme import ALARM, WARN
from .layout import AXES, THREAT_CELL


def _confidence_level(value):
    if value is None:
        return "SIN DATO", "off"
    if value >= 0.70:
        return "ALTA", "ok"
    if value >= 0.40:
        return "MEDIA", "warn"
    return "BAJA", "alarm"

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

_KEY_RE = re.compile(r'^(\s*)("(?:[^"\\]|\\.)*")(\s*:.*)$')
_LITERAL_RE = re.compile(
    r'(?<![\w"])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|\btrue\b|\bfalse\b|\bnull\b'
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

def _clip(text, width):
    """Trim a value to a fixed cell, so nothing beside it can move."""

    text = str(text)
    if width and len(text) > width:
        return text[: max(1, width - 1)] + "…"
    return text

def _clip_to_cell(widget, text):
    """Never let a value widen its box.

    An HMI cell has the width it was given; if the value does not fit, it is
    the value that is clipped.  A box that grows and shrinks with its data
    moves everything beside it and costs the operator a second look.
    """

    try:
        width = int(widget.cget("width"))
    except Exception:
        return text
    return _clip(text, width)

def _threat_block(lines) -> str:
    """Exactly three lines of one fixed cell, whatever the numbers say."""

    lines = [str(line) for line in lines][:3] or ["sin amenazas a la vista"]
    while len(lines) < 3:
        lines.append("")
    return "\n".join(f"{_clip(line, THREAT_CELL):<{THREAT_CELL}}" for line in lines)

def _guard_motive(events) -> str:
    """One line explaining a decision's intervention, for the event list."""

    if not events:
        return ""
    parts = [f"{event.kind}: {event.proposed}→{event.applied}" for event in events]
    text = "   ".join(parts)
    if len(events) > 1:
        text = f"×{len(events)}  " + text
    return text if len(text) <= 64 else text[:63] + "…"

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
