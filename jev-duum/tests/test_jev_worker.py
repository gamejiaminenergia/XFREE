import threading
import time

from jev_duum.worker import DecisionWorker


def test_worker_keeps_one_inference_in_flight_and_replaces_pending_snapshot():
    started = threading.Event()
    release = threading.Event()

    class Controller:
        def decide(self, snapshot):
            started.set()
            release.wait(timeout=2)
            return snapshot

    with DecisionWorker(Controller()) as worker:
        worker.submit("first")
        assert started.wait(timeout=2)
        worker.submit("second")
        worker.submit("newest")
        release.set()
        deadline = time.monotonic() + 2
        while worker.stats.completed < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert worker.stats.completed == 2
        assert worker.stats.replaced == 1
        assert worker.poll() == "newest"
