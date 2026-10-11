"""The one-line stability readout: previous decision versus current."""

from __future__ import annotations

from ..theme import FONTS, OFF, PANEL, STATIC, VALUE, WARN
from .canvas import _SMALL, _caption, _clip


class PolicyDelta:
    """What changed between the previous decision and this one, on one line."""

    def __init__(self, tkinter, parent, *, width=24):
        self.caption = _caption(tkinter, parent, width=22)
        self.value = tkinter.Label(
            parent, text="", width=width, anchor="w", justify="left", bg=PANEL,
            fg=VALUE, font=(FONTS["mono"], _SMALL),
        )
        self.value.pack(fill="x")
        self._last = None

    def render(self, previous, current):
        if previous is None or current is None:
            text, fg = "sin referencia todavía", OFF
        else:
            changed = False
            lines = []
            for label, before, after in (
                ("MOV", previous.movement, current.movement),
                ("APU", previous.aim, current.aim),
                ("ACC", previous.interaction, current.interaction),
            ):
                if before != after:
                    changed = True
                    lines.append(f"{label} {before}→{after}")
                else:
                    lines.append(f"{label} = {before}")
            text = "\n".join(lines)
            fg = WARN if changed else STATIC
        signature = (text, fg)
        if signature == self._last:
            return
        self._last = signature
        try:
            width = int(self.value.cget("width"))
        except Exception:  # pragma: no cover - defensive
            width = 0
        if width:
            text = "\n".join(_clip(line, width) for line in text.split("\n"))
        self.value.configure(text=text, fg=fg)
