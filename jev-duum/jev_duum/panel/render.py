"""Apply-with-delta helpers: touch a widget only when its cell actually changed.

The zones ask these before configuring a widget, which is what keeps a
refresh that changed nothing a no-op and removes the per-refresh flicker."""

from __future__ import annotations

import json

from ..theme import INFO, OFF, TITLE
from .format import _clip_to_cell, _insert_json_line


def label(cache, key, widget, text, **options):
    state = (text, tuple(sorted(options.items())))
    if not cache.changed(key, state):
        return
    widget.configure(text=_clip_to_cell(widget, text), **options)

def render_json(cache, key, widget, payload):
    try:
        signature = json.dumps(payload, sort_keys=True, default=str)
    except (TypeError, ValueError):
        signature = repr(payload)
    if not cache.changed(key, signature):
        return
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.tag_configure("key", foreground=TITLE)
    widget.tag_configure("num", foreground=INFO)
    widget.tag_configure("const", foreground=OFF)
    if payload is None:
        widget.insert("end", "sin dato")
    else:
        try:
            source = json.dumps(payload, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            source = str(payload)
        for line in source.splitlines():
            _insert_json_line(widget, line)
    widget.configure(state="disabled")

def render_text(cache, key, widget, content):
    if not cache.changed(key, content):
        return
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", content)
    widget.configure(state="disabled")
