"""A minimal, stdlib-only client for the TypeSafe System One (Jev) API.

Jev returns typed judgments with probabilities; it never generates prose. The
adapter sends one ``state`` plus a set of ``choice``/``score``/``noul``
questions and consumes the structured answer.

```text
POST https://api.typesafe.ai/v1/systemone
GET  https://api.typesafe.ai/v1/models
```

The key is never embedded here: it is resolved from the ``TYPESAFE_API_KEY``
environment variable (or an explicit argument) and never printed, logged, or
attached to raised exceptions.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODELS_URL = "https://api.typesafe.ai/v1/models"
DEFAULT_MODEL = "jev-latest"

# Input is $0.042 per million tokens; output is free (verified 2026-10-10).
PRICE_INPUT_USD_PER_MTOK = 0.042

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})
_FATAL_STATUS = frozenset({400, 401, 403, 404, 422})


class JevError(RuntimeError):
    """Raised when no trustworthy judgment can be obtained from Jev."""


def resolve_api_key(api_key: str | None = None) -> str:
    """Return a non-empty key, or fail loudly without echoing any secret."""

    value = api_key or os.environ.get("TYPESAFE_API_KEY")
    if not value or not str(value).strip():
        raise JevError(
            "Missing TypeSafe API key. Export TYPESAFE_API_KEY (or place it in the "
            "git-ignored jev-duum/.env and run through play.sh) before using a Jev pilot."
        )
    return str(value).strip()


def input_cost_usd(input_tokens: int) -> float:
    return max(0, int(input_tokens)) * PRICE_INPUT_USD_PER_MTOK / 1_000_000


class JevClient:
    """One request per call; retries only the failures that deserve it."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_MODEL,
        endpoint: str | None = None,
        models_url: str | None = None,
        timeout: float = 30.0,
        retries: int = 3,
        opener=None,
    ):
        self.api_key = resolve_api_key(api_key)
        self.model = model or DEFAULT_MODEL
        self.endpoint = endpoint or os.environ.get("TYPESAFE_URL") or DEFAULT_ENDPOINT
        self.models_url = models_url or DEFAULT_MODELS_URL
        self.timeout = float(timeout)
        self.retries = max(1, int(retries))
        self._opener = opener or urllib.request.urlopen
        self.calls = 0
        self.input_tokens = 0

    # -- public surface ------------------------------------------------------
    def ask(self, state, questions, *, model: str | None = None) -> dict:
        """Ask every question against one shared ``state`` in a single request."""

        if not isinstance(questions, dict) or not questions:
            raise JevError("questions must be a non-empty dict")
        payload = {
            "state": state,
            "model": model or self.model,
            "questions": questions,
        }
        response = self._send("POST", self.endpoint, payload)
        usage = response.get("usage") or {}
        try:
            tokens = int(usage.get("input_tokens") or 0)
        except (TypeError, ValueError):
            tokens = 0
        self.calls += 1
        self.input_tokens += tokens
        return response

    def models(self) -> list:
        response = self._send("GET", self.models_url, None)
        return response.get("models", response if isinstance(response, list) else [])

    # -- transport -----------------------------------------------------------
    def _send(self, method: str, url: str, payload):
        last_error = None
        for attempt in range(self.retries):
            request = self._request(method, url, payload)
            try:
                with self._opener(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                return json.loads(body)
            except urllib.error.HTTPError as error:
                detail = self._safe_detail(error)
                if error.code in _FATAL_STATUS:
                    raise JevError(f"Jev rejected the request (HTTP {error.code}): {detail}") from None
                last_error = JevError(f"Jev HTTP {error.code}: {detail}")
                if error.code not in _RETRYABLE_STATUS or attempt == self.retries - 1:
                    raise last_error from None
                self._sleep(attempt, error.headers.get("retry-after"))
            except urllib.error.URLError as error:
                last_error = JevError(f"Jev transport failure: {error.reason}")
                if attempt == self.retries - 1:
                    raise last_error from None
                self._sleep(attempt)
            except json.JSONDecodeError as error:
                last_error = JevError(f"Jev returned non-JSON content: {error}")
                if attempt == self.retries - 1:
                    raise last_error from None
                self._sleep(attempt)
        raise last_error or JevError("Jev request failed")

    def _request(self, method: str, url: str, payload):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Authorization": "Bearer " + self.api_key}
        if data is not None:
            headers["Content-Type"] = "application/json"
        return urllib.request.Request(url, data=data, headers=headers, method=method)

    @staticmethod
    def _safe_detail(error: urllib.error.HTTPError) -> str:
        """Read a short body excerpt without ever touching the credentials."""

        try:
            return error.read().decode("utf-8", "replace")[:400]
        except Exception:  # pragma: no cover - defensive
            return error.reason if isinstance(error.reason, str) else "no body"

    def _sleep(self, attempt: int, retry_after=None) -> None:
        delay = 2**attempt
        if retry_after:
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                pass
        time.sleep(min(delay, 10.0))
