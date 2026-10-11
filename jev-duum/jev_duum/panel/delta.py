"""The per-widget change check that removes the per-refresh flicker."""

from __future__ import annotations


class DeltaCache:
    """Remember the last value drawn per key and report only real changes.

    The panel asks this before touching any widget, which is what removes the
    per-refresh flicker: a refresh that did not change a field is a no-op.
    """

    def __init__(self):
        self._values: dict = {}

    def changed(self, key, value) -> bool:
        if key in self._values and self._values[key] == value:
            return False
        self._values[key] = value
        return True

    def reset(self, key) -> None:
        self._values.pop(key, None)
