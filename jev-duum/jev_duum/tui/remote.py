"""The terminal frontend over HTTP: the same screen, with the session elsewhere.

``jev-duum --tui`` draws a session running in this process.  This one draws a
session running on a service (``jev-service/``): it polls ``/api/state``, paints
the game from ``/api/frame.raw`` when the terminal is wide enough, and sends
`p`/`+`/`-` to ``/api/control``.  Nothing here talks to the engine.

It is standard library only — ``urllib`` for the wire — so the client needs no
dependencies at all.  A browser uses the WebSocket push; a terminal redraws at
~10 Hz anyway, so polling costs nothing and keeps the client simple.
"""

from __future__ import annotations

import argparse
import curses
import json
import time
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any

from .app import TuiApp

POLL_HZ = 10.0
TIMEOUT = 5.0


def frame_from_state(state: dict[str, Any], *, rgb: bytes | None = None):
    """Rebuild the value the renderers expect from the wire format.

    Same attributes, same names: ``render.py`` and ``SessionModel`` cannot tell a
    remote frame from a local one, which is the point of having one format.
    """

    player = state.get("player") or {}
    episode = state.get("episode") or {}
    status = state.get("state", "running")
    snapshot = SimpleNamespace(
        map_name=state.get("map", "?"),
        tick=state.get("tick", 0),
        player=SimpleNamespace(
            health=player.get("health", 0),
            armor=player.get("armor", 0),
            ammo=player.get("ammo", 0),
            weapon_name=player.get("weapon", "?"),
            max_health=player.get("max_health", 100),
        ),
        episode=SimpleNamespace(
            game_time=state.get("game_time", 0.0),
            kills=episode.get("kills", 0),
            items=episode.get("items", 0),
            damage_received=episode.get("damage_received", 0),
            unique_sectors=episode.get("unique_sectors", 0),
            stuck_ticks=episode.get("stuck_ticks", 0),
            idle_ticks=episode.get("idle_ticks", 0),
            dead=status == "dead",
            finished=status == "finished",
        ),
    )

    decision = None
    wire = state.get("decision")
    if wire:
        decision = SimpleNamespace(
            observation_tick=wire.get("observation_tick", state.get("tick", 0)),
            application_tick=wire.get("application_tick"),
            probabilities=wire.get("probabilities") or {},
            confidence=wire.get("confidence") or {},
            proposed_controls=SimpleNamespace(**(wire.get("proposed") or {})),
            applied_controls=SimpleNamespace(**(wire.get("applied") or {})),
            assistance_events=[
                SimpleNamespace(**event) for event in (wire.get("interventions") or [])
            ],
            observations=wire.get("observations") or {},
            strategy=wire.get("strategy"),
            model_id=wire.get("model", "?"),
            prompt_version=wire.get("prompt_version", "?"),
            request_keys=wire.get("keys"),
            request_questions_count=wire.get("questions"),
            input_tokens=wire.get("tokens") or {},
            cost_usd=wire.get("cost_usd") or 0.0,
            request_ms=wire.get("request_ms") or 0.0,
            decision_ms=wire.get("decision_ms") or 0.0,
            prediction_calls=wire.get("prediction_calls") or 1,
            execution=wire.get("execution") or "?",
        )

    worker = state.get("worker") or {}
    controls = state.get("controls") or {}
    return SimpleNamespace(
        tick=state.get("tick", 0),
        snapshot=snapshot,
        decision=decision,
        controls=SimpleNamespace(
            movement=controls.get("movement"),
            aim=controls.get("aim"),
            interaction=controls.get("interaction"),
            target=controls.get("target"),
        ),
        stale=state.get("stale", 0),
        error=state.get("error"),
        busy=worker.get("busy", False),
        submitted=worker.get("submitted", 0),
        completed=worker.get("completed", 0),
        replaced=worker.get("replaced", 0),
        failed=worker.get("failed", 0),
        applied=worker.get("applied", 0),
        log_stats=state.get("link"),
        rgb=rgb,
    )


class RemoteSession:
    """A ``Session``-shaped client, so the TUI cannot tell the difference."""

    def __init__(self, base_url: str, *, pixels: bool = True, poll_hz: float = POLL_HZ):
        self.base = base_url.rstrip("/")
        self.pixels = bool(pixels)
        self.poll_hz = float(poll_hz)
        self.meta = self._json("/api/meta")
        self.paused = bool(self.meta.get("paused"))
        self.decision_rate = float(self.meta.get("decision_rate") or 10.0)
        size = str(self.meta.get("resolution") or "320x200")
        try:
            width, height = (int(part) for part in size.lower().split("x"))
        except ValueError:
            width, height = 320, 200
        self._size = (width, height)
        self.last_tick = 0
        self.frames = 0

    # -- wire ----------------------------------------------------------------
    def _json(self, path: str) -> dict:
        return json.loads(self._fetch(path))

    def _fetch(self, path: str) -> bytes:
        with urllib.request.urlopen(f"{self.base}{path}", timeout=TIMEOUT) as response:
            return response.read()

    def _post(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{self.base}{path}", data=body, method="POST",
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())

    def _pixels(self) -> bytes | None:
        if not self.pixels:
            return None
        try:
            return self._fetch("/api/frame.raw")
        except (urllib.error.URLError, OSError):
            return None

    # -- the shape the TUI uses ----------------------------------------------
    def frame_size(self) -> tuple[int, int]:
        return self._size

    def set_pixels(self, enabled: bool) -> bool:
        self.pixels = bool(enabled)
        return self.pixels

    def set_paused(self, paused: bool) -> bool:
        try:
            answer = self._post("/api/control", {"paused": bool(paused)})
            self.paused = bool(answer.get("paused", paused))
        except (urllib.error.URLError, OSError):
            self.paused = bool(paused)
        return self.paused

    def set_decision_rate(self, rate: float) -> float:
        rate = float(rate)
        if rate <= 0:
            raise ValueError("decision rate must be positive")
        self.decision_rate = rate
        try:
            self._post("/api/control", {"decision_rate": rate})
        except (urllib.error.URLError, OSError):
            pass
        return self.decision_rate

    def step(self):
        state = self._json("/api/state?full=0")
        self.last_tick = state.get("tick", 0)
        frame = frame_from_state(state, rgb=self._pixels())
        if frame.rgb is not None:
            self.frames += 1
        return frame

    def run(self, *, stop=None, realtime: bool = True, fps: float = POLL_HZ, on_frame=None):
        started = time.perf_counter()
        period = 1.0 / float(fps)
        next_at = time.perf_counter()
        while not (stop is not None and stop.is_set()):
            try:
                frame = self.step()
            except (urllib.error.URLError, OSError) as error:
                # The service went away: keep the screen up and say so.
                frame = None
                if on_frame is not None:
                    on_frame(frame, error)
            if frame is not None and on_frame is not None:
                on_frame(frame)
            if realtime:
                next_at += period
                delay = next_at - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_at = time.perf_counter()
        return self.summary(wall_seconds=time.perf_counter() - started)

    def summary(self, *, wall_seconds: float | None = None) -> dict:
        return {
            "mode": "remote",
            "url": self.base,
            "tick": self.last_tick,
            "frames": self.frames,
            "wall_seconds": wall_seconds,
            "paused": self.paused,
            "decision_rate": self.decision_rate,
            **{key: self.meta[key] for key in ("pilot", "model", "prompt_version") if key in self.meta},
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jev-duum-tui", description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000",
                        help="the jev-service base URL (default: %(default)s)")
    parser.add_argument("--poll", type=float, default=POLL_HZ,
                        help="state refreshes per second (default: %(default)s)")
    parser.add_argument("--no-game", action="store_true",
                        help="never paint the game, even on a wide terminal")
    return parser


def _run(stdscr, session: RemoteSession, *, show_game: bool) -> dict:
    import threading

    stop = threading.Event()
    app = TuiApp(stdscr, session, show_game=show_game)

    def on_frame(frame, error=None):
        if frame is None:
            app.draw_disconnected(error)
            app.handle_keys(stop)
            return
        app.on_frame(frame, stop)

    return session.run(stop=stop, realtime=True, fps=session.poll_hz, on_frame=on_frame)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        session = RemoteSession(args.url, poll_hz=args.poll)
    except (urllib.error.URLError, OSError, ValueError) as error:
        print(f"jev-duum-tui: cannot reach {args.url}: {error}")
        return 1
    try:
        summary = curses.wrapper(lambda stdscr: _run(stdscr, session, show_game=not args.no_game))
    except KeyboardInterrupt:  # pragma: no cover - Ctrl-C is a normal way out
        summary = session.summary()
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
