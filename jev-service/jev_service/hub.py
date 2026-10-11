"""The latest state and frame, plus fan-out to whoever is watching.

The engine runs in its own thread and must never wait for a client.  So every
consumer reads the *latest* value (never a queue that grows) and a subscriber
that cannot keep up simply misses frames.
"""

from __future__ import annotations

import queue
import threading
from typing import Any


def compact(frame) -> dict[str, Any]:
    """The session frame as plain JSON, small enough to poll.

    ``snapshot`` is the full semantic state (the same shape that travels to Jev),
    so an experiment can replay a decision from the API; everything else is what
    the panel reads.
    """

    snapshot = frame.snapshot
    episode = snapshot.episode
    player = snapshot.player
    decision = frame.decision
    return {
        "tick": frame.tick,
        "map": snapshot.map_name,
        "game_time": episode.game_time,
        "state": "dead" if episode.dead else "finished" if episode.finished else "running",
        "stale": frame.stale,
        "error": frame.error,
        "controls": {
            "movement": frame.controls.movement,
            "aim": frame.controls.aim,
            "interaction": frame.controls.interaction,
            "target": getattr(frame.controls, "target", None),
        },
        "player": {
            "health": player.health,
            "armor": player.armor,
            "ammo": player.ammo,
            "weapon": player.weapon_name,
            "max_health": getattr(player, "max_health", 100),
        },
        "episode": {
            "kills": episode.kills,
            "items": episode.items,
            "damage_received": episode.damage_received,
            "unique_sectors": episode.unique_sectors,
            "stuck_ticks": episode.stuck_ticks,
            "idle_ticks": episode.idle_ticks,
        },
        "worker": {
            "busy": frame.busy,
            "submitted": frame.submitted,
            "completed": frame.completed,
            "replaced": frame.replaced,
            "failed": frame.failed,
            "applied": frame.applied,
        },
        "link": frame.log_stats,
        "decision": None
        if decision is None
        else {
            "observation_tick": decision.observation_tick,
            "application_tick": decision.application_tick,
            "probabilities": decision.probabilities,
            "confidence": decision.confidence,
            "proposed": {
                "movement": decision.proposed_controls.movement,
                "aim": decision.proposed_controls.aim,
                "interaction": decision.proposed_controls.interaction,
            },
            "applied": {
                "movement": decision.applied_controls.movement,
                "aim": decision.applied_controls.aim,
                "interaction": decision.applied_controls.interaction,
            },
            "interventions": [
                {"kind": e.kind, "proposed": e.proposed, "applied": e.applied, "reason": e.reason}
                for e in (decision.assistance_events or ())
            ],
            "observations": decision.observations,
            "strategy": decision.strategy,
            "model": decision.model_id,
            "prompt_version": decision.prompt_version,
            "keys": len(decision.request_state or {}),
            "questions": len(decision.request_questions or {}),
            "tokens": decision.input_tokens,
            "cost_usd": decision.cost_usd,
            "request_ms": decision.request_ms,
            "decision_ms": decision.decision_ms,
            "prediction_calls": decision.prediction_calls,
            "execution": decision.execution,
        },
        "snapshot": snapshot.to_dict(),
    }


class Hub:
    """Latest state/frame under a lock, with bounded fan-out to subscribers."""

    def __init__(self, *, queue_size: int = 2):
        self._lock = threading.Lock()
        self._state: dict | None = None
        self._frame: bytes | None = None
        self._png: bytes | None = None
        self._size: tuple[int, int] = (0, 0)
        self._seq = 0
        self._dropped = 0
        self._subscribers: set[queue.Queue] = set()
        self._queue_size = int(queue_size)

    # -- publishing (the engine thread) --------------------------------------
    def publish(self, frame) -> None:
        try:
            state = compact(frame)
        except Exception:
            # The engine thread is the only one and the session runs on it: a
            # serialisation bug must not kill the run.  It is counted, and
            # /health reports it, so it cannot go unnoticed either.
            with self._lock:
                self._dropped += 1
            return
        with self._lock:
            self._seq += 1
            self._state = state
            if frame.rgb is not None:
                # The raw buffer is kept so a request can encode it on demand;
                # a new frame invalidates the cached PNG.
                self._frame = frame.rgb
                self._png = None
            payload = {"seq": self._seq, "state": state}
            for subscriber in list(self._subscribers):
                try:
                    subscriber.put_nowait(payload)
                except queue.Full:
                    # A slow client misses frames; it never slows the engine.
                    try:
                        subscriber.get_nowait()
                        subscriber.put_nowait(payload)
                    except queue.Empty:  # pragma: no cover - raced with a reader
                        pass

    def set_frame_size(self, width: int, height: int) -> None:
        with self._lock:
            self._size = (int(width), int(height))

    # -- reading (the web thread) --------------------------------------------
    def state(self) -> dict | None:
        with self._lock:
            return self._state

    def seq(self) -> int:
        with self._lock:
            return self._seq

    def dropped(self) -> int:
        """Frames that could not be serialised (a bug, but never a crash)."""

        with self._lock:
            return self._dropped

    def size(self) -> tuple[int, int]:
        with self._lock:
            return self._size

    def rgb(self) -> bytes | None:
        with self._lock:
            return self._frame

    def png(self) -> tuple[bytes, int] | None:
        """The latest frame as PNG, encoded once per published frame."""

        with self._lock:
            if self._frame is None:
                return None
            if self._png is None:
                from .frames import encode_png

                self._png = encode_png(self._frame, self._size[0], self._size[1])
            return self._png, self._seq

    # -- subscribing ---------------------------------------------------------
    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)
