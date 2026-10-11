"""The banner drawn over the game canvas when decisions go stale or fail."""

from __future__ import annotations

from ..theme import MAP_STALE_ERROR_BG, MAP_STALE_TEXT, MAP_STALE_WARN_BG


class StaleOverlay:
    """A banner drawn over the game canvas when decisions go stale or fail."""

    def __init__(self, tkinter, canvas, *, height: int = 24):
        self.canvas = canvas
        self.height = int(height)
        self._cached: tuple | None = None

    def update(self, *, stale: int, error: str | None) -> None:
        if error:
            state = ("error", error)
        elif stale > 3:
            state = ("stale", int(stale))
        else:
            state = ("ok",)
        if state == self._cached:
            return
        self._cached = state
        canvas = self.canvas
        canvas.delete("hud")
        if state[0] == "ok":
            return
        width = int(float(canvas["width"]))
        if state[0] == "error":
            color, text = MAP_STALE_ERROR_BG, f"SIN MODELO · {error}"[:80]
        else:
            color, text = MAP_STALE_WARN_BG, f"DECISIONES OBSOLETAS ×{stale}"
        # Solid, not ``stipple="gray50"``: a one-pixel checkerboard shimmers on
        # a projector and reads as texture rather than as an alert.
        canvas.create_rectangle(
            0, 0, width, self.height, fill=color, outline="", tags="hud"
        )
        canvas.create_text(
            width / 2, self.height / 2, text=text, fill=MAP_STALE_TEXT,
            font=("DejaVu Sans Mono", 10, "bold"), tags="hud",
        )
