"""Single-in-flight Jev worker with latest-snapshot replacement."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkerStats:
    submitted: int
    completed: int
    replaced: int
    failed: int


class DecisionWorker:
    def __init__(self, controller):
        self.controller = controller
        self._condition = threading.Condition()
        self._pending = None
        self._result = None
        self._error = None
        self._closed = False
        self._busy = False
        self._submitted = 0
        self._completed = 0
        self._replaced = 0
        self._failed = 0
        self._thread = threading.Thread(target=self._run, name="jev-duum", daemon=True)
        self._thread.start()

    def submit(self, snapshot) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("decision worker is closed")
            self._submitted += 1
            if self._pending is not None:
                self._replaced += 1
            self._pending = snapshot
            self._condition.notify()

    def poll(self):
        with self._condition:
            if self._error is not None:
                error = self._error
                self._error = None
                raise RuntimeError("Jev decision worker failed") from error
            result = self._result
            self._result = None
            return result

    @property
    def busy(self) -> bool:
        with self._condition:
            return self._busy

    @property
    def stats(self) -> WorkerStats:
        with self._condition:
            return WorkerStats(
                self._submitted, self._completed, self._replaced, self._failed
            )

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                snapshot = self._pending
                self._pending = None
                self._busy = True
            try:
                result = self.controller.decide(snapshot)
            except Exception as error:
                with self._condition:
                    self._error = error
                    self._failed += 1
                    self._busy = False
            else:
                with self._condition:
                    self._result = result
                    self._completed += 1
                    self._busy = False

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify_all()
        self._thread.join(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
