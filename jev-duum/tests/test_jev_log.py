"""The audit log must never break a decision, and it must land in Mongo."""

import json

from jev_duum.jev_log import JevCallLogger


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _opener(payload, captured):
    def open_(request, timeout=None):
        captured.append(request)
        return FakeResponse(payload)

    return open_


def test_document_carries_the_full_request_and_response():
    logger = JevCallLogger("http://localhost:3000/calls", enabled=True)
    document = logger.build_document(
        state={"tick": 7, "player": {"health": 100}},
        questions={"movement": {"type": "choice"}},
        response={"probabilities": {"forward": 1.0}},
        tick=7,
        pilot="jev-assisted",
        prompt_version="v3w",
        model="jev-latest",
        stage="decision",
    )
    assert document["tick"] == 7
    assert document["request"]["pilot"] == "jev-assisted"
    assert document["request"]["prompt_version"] == "v3w"
    assert document["request"]["state"]["tick"] == 7
    assert document["request"]["questions"]["movement"]["type"] == "choice"
    assert document["response"]["probabilities"] == {"forward": 1.0}
    assert document["metadata"]["stage"] == "decision"
    json.dumps(document)  # must be JSON-serializable
    logger.close()


def test_url_is_normalised_with_or_without_the_calls_suffix():
    assert JevCallLogger("http://host:3000").url == "http://host:3000"
    assert JevCallLogger("http://host:3000/calls").url == "http://host:3000"
    assert JevCallLogger("http://host:3000/", enabled=True).url == "http://host:3000"


def test_no_log_disables_everything(monkeypatch):
    monkeypatch.setenv("JEV_NO_LOG", "1")
    logger = JevCallLogger()
    assert logger.enabled is False
    assert logger.log_sync({"anything": True}) is None
    logger.log({"anything": True})  # must be a silent no-op
    assert logger.stats == {"sent": 0, "dropped": 0, "enabled": False}


def test_a_transport_failure_is_counted_and_never_raised():
    def boom(request, timeout=None):
        raise OSError("connection refused")

    logger = JevCallLogger(enabled=True, opener=boom)
    assert logger.log_sync({"request": {}, "response": {}}) is None
    assert logger.stats["dropped"] == 1
    assert logger.stats["sent"] == 0


def test_sync_post_sends_one_json_document_to_calls():
    captured = []
    logger = JevCallLogger(enabled=True, opener=_opener({"inserted_id": "abc123"}, captured))
    inserted = logger.log_sync({"tick": 1, "request": {}, "response": {}})
    assert inserted == "abc123"
    assert logger.stats["sent"] == 1
    request = captured[0]
    assert request.full_url == "http://localhost:3000/calls"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode("utf-8"))["tick"] == 1


def test_async_log_drains_on_close():
    captured = []
    logger = JevCallLogger(enabled=True, opener=_opener({"inserted_id": "x"}, captured))
    for tick in range(5):
        logger.log({"tick": tick, "request": {}, "response": {}})
    logger.close()
    assert logger.stats["sent"] == 5
    assert len(captured) == 5


def test_log_call_wrapper_builds_and_enqueues():
    captured = []
    logger = JevCallLogger(enabled=True, opener=_opener({"inserted_id": "y"}, captured))
    logger.log_call(
        state={"tick": 3},
        questions={"aim": {"type": "choice"}},
        response={"probabilities": {"straight": 1.0}},
        tick=3,
        pilot="jev-raw",
    )
    logger.close()
    assert logger.stats["sent"] == 1
