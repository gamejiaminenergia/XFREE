"""Audit log: every Jev request and its raw response, persisted in MongoDB.

The stack lives in the repository root (``docker-compose.yml``): MongoDB 7 plus
the small Express API in ``jev-log/server.js``, which stores one document per
call in ``jevlog.jev_calls`` — request and response together, so a decision can
always be replayed and audited from the database alone.

    POST http://localhost:3000/calls   { tick, request, response, metadata }
    GET  http://localhost:3000/calls   list, paginated
    GET  http://localhost:3000/health  readiness

Design rules, in order of importance:

1. Logging must never break, slow down, or fail a decision.  ``log`` enqueues
   and returns; a daemon worker does the HTTP POST.  Every failure is swallowed
   and counted in ``stats``.
2. No third-party dependency: the venv is stdlib-only, so this speaks HTTP with
   ``urllib.request`` exactly like ``jev_client``.
3. The full ``state`` and the full ``questions`` travel in the document: the
   point of the log is to see *what the model was asked*, not just what it said.

Environment:

    JEV_LOG_URL   base URL of the API (default http://localhost:3000)
    JEV_NO_LOG    any value disables logging entirely
    JEV_LOG_DEBUG any value prints dropped-document warnings to stderr
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import sys
import threading
import urllib.error
import urllib.request

DEFAULT_LOG_URL = "http://localhost:3000"
DEFAULT_TIMEOUT = 2.0


def _resolve_url(url: str | None) -> str:
    value = (url or os.environ.get("JEV_LOG_URL") or DEFAULT_LOG_URL).strip()
    value = value.rstrip("/")
    if value.endswith("/calls"):
        value = value[: -len("/calls")]
    return value


def _disabled(enabled: bool | None) -> bool:
    if enabled is False:
        return True
    if enabled is True:
        return False
    return bool(os.environ.get("JEV_NO_LOG"))


class JevCallLogger:
    """Fire-and-forget writer for ``jevlog.jev_calls``.

    ``log`` never blocks and never raises.  Use ``log_sync`` in tests, or when
    the caller genuinely wants to know whether the document landed.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        enabled: bool | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        opener=None,
    ):
        self.url = _resolve_url(url)
        self.timeout = float(timeout)
        self._opener = opener or urllib.request.urlopen
        self._disabled = _disabled(enabled)
        self.enabled = not self._disabled
        self.sent = 0
        self.dropped = 0
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self._closed = False
        # The game loop never calls close(); make sure a short run still lands.
        atexit.register(self._drain)

    # -- public surface ------------------------------------------------------
    @property
    def stats(self) -> dict:
        return {"sent": self.sent, "dropped": self.dropped, "enabled": self.enabled}

    def build_document(
        self,
        *,
        state,
        questions,
        response,
        tick=None,
        pilot=None,
        prompt_version=None,
        model=None,
        **extra,
    ) -> dict:
        """Assemble the document the API stores (pure; no I/O)."""

        return {
            "tick": int(tick) if isinstance(tick, int) else None,
            "request": {
                "model": model or "jev-latest",
                "pilot": pilot,
                "prompt_version": prompt_version,
                "state": state,
                "questions": questions,
            },
            "response": response if isinstance(response, dict) else {"raw": response},
            "metadata": dict(extra),
        }

    def log(self, document: dict) -> None:
        """Enqueue one document; returns immediately and never raises."""

        if self._disabled or self._closed:
            return
        self._ensure_worker()
        self._queue.put(document)

    def log_call(
        self,
        *,
        state,
        questions,
        response,
        tick=None,
        pilot=None,
        prompt_version=None,
        model=None,
        **extra,
    ) -> None:
        """Convenience wrapper around ``build_document`` + ``log``."""

        self.log(
            self.build_document(
                state=state,
                questions=questions,
                response=response,
                tick=tick,
                pilot=pilot,
                prompt_version=prompt_version,
                model=model,
                **extra,
            )
        )

    def log_sync(self, document: dict | None = None, **fields) -> str | None:
        """POST one document synchronously; returns the Mongo ``_id`` or None."""

        if self._disabled:
            return None
        if document is None:
            document = self.build_document(**fields)
        try:
            payload = json.dumps(document, default=str).encode("utf-8")
        except (TypeError, ValueError):
            self.dropped += 1
            return None
        return self._post(payload)

    def close(self, timeout: float = 2.0) -> None:
        """Let the worker drain the queue, then stop it."""

        if self._closed:
            return
        self._closed = True
        worker = self._worker
        if worker is not None and worker.is_alive():
            self._queue.join()
            self._queue.put(None)
            worker.join(timeout=timeout)

    def _drain(self, timeout: float = 3.0) -> None:
        """Best-effort ``close`` for interpreter shutdown; never raises."""

        try:
            if not self._closed and self._worker is not None:
                self.close(timeout)
        except Exception:  # pragma: no cover - shutdown must stay quiet
            pass

    # -- worker --------------------------------------------------------------
    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._run, name="jev-log", daemon=True)
            self._worker.start()

    def _run(self) -> None:
        while True:
            document = self._queue.get()
            try:
                if document is None:
                    return
                try:
                    payload = json.dumps(document, default=str).encode("utf-8")
                except (TypeError, ValueError) as error:  # pragma: no cover - defensive
                    self.dropped += 1
                    self._warn(f"dropped an unserializable document: {error}")
                    continue
                self._post(payload)
            finally:
                self._queue.task_done()

    def _post(self, payload: bytes) -> str | None:
        request = urllib.request.Request(
            f"{self.url}/calls",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
            self.sent += 1
            try:
                return str(json.loads(body).get("inserted_id"))
            except (TypeError, ValueError):
                return None
        except (urllib.error.URLError, OSError, ValueError) as error:
            self.dropped += 1
            self._warn(f"dropped a call log ({error})")
            return None

    @staticmethod
    def _warn(message: str) -> None:
        if os.environ.get("JEV_LOG_DEBUG"):
            print(f"jev-log: {message}", file=sys.stderr)
