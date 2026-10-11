# jev-service

The Jev pilot behind HTTP: live state, decisions and the engine's own pixels.

The engine lives in [`../jev-duum`](../jev-duum) (`jev_duum.session`); this package
only adapts it to the web. `jev-duum` keeps its single dependency (`duum`), and
FastAPI lives here, the same way the audit log lives in `jev-log/`.

```bash
cd jev-service
uv sync
uv run --no-sync jev-service --fake        # local deterministic model: 0 $, no key
uv run --no-sync jev-service               # the real Jev (TYPESAFE_API_KEY)
```

Then open <http://127.0.0.1:8000>. It binds to localhost by default.

## Endpoints

| Endpoint | What it returns |
|---|---|
| `GET /health` | liveness, uptime, current tick and sequence |
| `GET /api/meta` | pilot, model, `prompt_version`, mission, engine commit, WAD |
| `GET /api/state` | the latest frame as JSON: player, episode, worker, decision, and the full semantic `snapshot` (the same shape that travels to Jev). `?full=0` drops the snapshot |
| `GET /api/frame.png` | the latest engine frame, as PNG |
| `GET /api/frame.raw` | the same frame as raw RGB, for a client that paints its own cells |
| `GET /api/frames.stream` | `multipart/x-mixed-replace` of those PNGs, for a plain `<img>` |
| `WS /ws` | push of `{seq, state}` at the session's frame rate |
| `POST /api/control` | `{"paused": true}` and/or `{"decision_rate": 8}` |
| `GET /` | the panel in the browser |

Two clients ship with it: the browser page and the terminal panel,

```bash
cd ../jev-duum && uv run --no-sync jev-duum-tui --url http://127.0.0.1:8000
```

which polls the state, paints the game from `/api/frame.raw` and sends its keys
to `/api/control`. It needs nothing but `urllib` and a terminal, so the session
can run on one machine and be watched from another.

```bash
curl -s localhost:8000/api/state | jq .decision.applied
curl -s localhost:8000/api/control -H 'content-type: application/json' -d '{"paused":true}'
```

## Design notes

- **The engine is never touched by a request.** `Session` runs in its own thread
  and publishes into a `Hub`; the web layer only reads the latest value. A slow
  or broken client misses frames and cannot slow the session down.
- **No new dependency for pixels.** The engine hands out raw RGB; `frames.py`
  writes the PNG with `zlib`, from the standard library.
- **No pydantic per frame.** The state is already a dict; serialising it with a
  `response_model` ten times a second would be pure overhead.
- **Colours come from `theme.py`.** `GET /` is rendered with the palette
  substituted into the CSS variables, so the guide is still the single home.
- **Local by default.** `--host 127.0.0.1`; `POST /api/control` takes
  `--control-token` if the service is ever exposed.
- **The key stays on the server.** No client sees `TYPESAFE_API_KEY`.

## Tests

```bash
cd jev-service
uv sync && uv run --no-sync pytest -q
uv run --no-sync ruff check jev_service tests
```

They need no engine, no network and no key: the hub and the app are driven with
fabricated frames.
