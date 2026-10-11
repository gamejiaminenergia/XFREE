"""The shared canvas floor: fixed-size captions and the 9 pt minimum."""

from __future__ import annotations

from ..theme import FONTS, PANEL, STATIC

_SMALL = 9  # the guide's floor: nothing on this screen is smaller than 9 pt


def _caption(tkinter, parent, width=0):
    """A fixed-width caption row: the widget's word travels with its value."""

    label = tkinter.Label(
        parent, text="", width=width, anchor="w", justify="left", bg=PANEL,
        fg=STATIC, font=(FONTS["mono"], _SMALL),
    )
    label.pack(fill="x")
    return label


def _set_caption(label, text):
    """Set a caption, clipped to its fixed width like every other HMI cell."""

    try:
        width = int(label.cget("width"))
    except Exception:  # pragma: no cover - defensive
        width = 0
    if width:
        text = "\n".join(_clip(line, width) for line in str(text).split("\n"))
    if label.cget("text") != text:
        label.configure(text=text)


def _clip(text, width):
    text = str(text)
    if width and len(text) > width:
        return text[: max(1, width - 1)] + "…"
    return text
