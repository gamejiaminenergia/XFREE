import io
import json
import urllib.error

import pytest

from jev_duum import jev_client
from jev_duum.jev_client import JevClient, JevError, input_cost_usd

KEY = "apikey_test_secret_value"


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def http_error(code, body=b"", headers=None):
    return urllib.error.HTTPError(
        "https://api.typesafe.ai/v1/systemone",
        code,
        "error",
        headers or {},
        io.BytesIO(body),
    )


def test_missing_key_is_reported_without_echoing_anything(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(JevError, match="TYPESAFE_API_KEY"):
        JevClient()


def test_key_comes_from_the_environment_when_not_passed(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    assert JevClient().api_key == KEY
    assert JevClient(api_key="explicit").api_key == "explicit"


def test_request_sends_bearer_header_and_never_leaks_the_key(monkeypatch):
    captured = {}

    def opener(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse({"model": "jev-1.0", "answers": {}, "usage": {"input_tokens": 5}})

    client = JevClient(api_key=KEY, opener=opener)
    client.ask({"a": 1}, {"movement": {"type": "noul"}})
    request = captured["request"]
    assert request.get_header("Authorization") == "Bearer " + KEY
    assert request.get_method() == "POST"
    body = json.loads(request.data.decode())
    assert body["model"] == "jev-latest"
    assert body["state"] == {"a": 1}
    assert set(body["questions"]) == {"movement"}
    assert captured["timeout"] == 30.0


def test_transport_failures_never_embed_the_key(monkeypatch):
    def opener(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(jev_client.time, "sleep", lambda *_: None)
    client = JevClient(api_key=KEY, opener=opener, retries=2)
    with pytest.raises(JevError) as error:
        client.ask({"a": 1}, {"q": {"type": "noul"}})
    assert KEY not in str(error.value)


def test_retries_a_dropped_connection(monkeypatch):
    attempts = {"n": 0}

    def opener(request, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionResetError(104, "connection reset by peer")
        return FakeResponse({"model": "jev-1.0", "answers": {}})

    monkeypatch.setattr(jev_client.time, "sleep", lambda *_: None)
    client = JevClient(api_key=KEY, opener=opener)
    assert client.ask({"a": 1}, {"q": {"type": "noul"}})["model"] == "jev-1.0"
    assert attempts["n"] == 2


def test_retries_on_429_honouring_retry_after(monkeypatch):
    attempts = {"n": 0}
    slept = []

    def opener(request, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise http_error(429, b"slow down", {"retry-after": "1"})
        return FakeResponse(
            {"model": "jev-1.0", "answers": {"q": {"type": "noul", "noul": 0.9}}}
        )

    monkeypatch.setattr(jev_client.time, "sleep", lambda value: slept.append(value))
    client = JevClient(api_key=KEY, opener=opener)
    response = client.ask({"a": 1}, {"q": {"type": "noul"}})
    assert response["model"] == "jev-1.0"
    assert attempts["n"] == 2
    assert slept == [1.0]


def test_does_not_retry_fatal_usage_errors(monkeypatch):
    attempts = {"n": 0}

    def opener(request, timeout=None):
        attempts["n"] += 1
        raise http_error(401, b'{"error_type":"unauthorized"}')

    monkeypatch.setattr(jev_client.time, "sleep", lambda *_: None)
    client = JevClient(api_key=KEY, opener=opener)
    with pytest.raises(JevError, match="HTTP 401"):
        client.ask({"a": 1}, {"q": {"type": "noul"}})
    assert attempts["n"] == 1


def test_retries_529_provider_overload(monkeypatch):
    attempts = {"n": 0}

    def opener(request, timeout=None):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise http_error(529, b"overloaded")
        return FakeResponse({"model": "jev-1.0", "answers": {}})

    monkeypatch.setattr(jev_client.time, "sleep", lambda *_: None)
    client = JevClient(api_key=KEY, opener=opener)
    assert client.ask({"a": 1}, {"q": {"type": "noul"}})["model"] == "jev-1.0"
    assert attempts["n"] == 3


def test_tracks_calls_and_input_tokens():
    def opener(request, timeout=None):
        return FakeResponse({"model": "jev-1.0", "answers": {}, "usage": {"input_tokens": 556}})

    client = JevClient(api_key=KEY, opener=opener)
    client.ask({"a": 1}, {"q": {"type": "noul"}})
    client.ask({"a": 1}, {"q": {"type": "noul"}})
    assert client.calls == 2
    assert client.input_tokens == 1112


def test_input_cost_matches_the_published_price():
    assert input_cost_usd(1_000_000) == pytest.approx(0.042)
    assert input_cost_usd(556) == pytest.approx(0.000023352)
