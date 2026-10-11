# Repository Guidelines

## Project Structure & Module Organization

- `jev-duum/jev_duum/` — the pilot: `snapshot/` → `prompts/` →
  `controller.py` → `worker.py`, plus `strategy.py`, `world_model.py`,
  `world_readout.py`, `assistance.py`, `theme.py` (the single palette, screen and
  automap) and `jev_log.py`.  Six former single-file modules are now packages
  with the **same dotted path**: each `__init__.py` is a facade that re-exports
  the old names, so every caller imports them unchanged.
- `jev-duum/jev_duum/session/` — **the backend**: `policy.py` (the tick rules, as
  pure functions) and `core.py` (`Session`: engine + `SnapshotBuilder` +
  `DecisionWorker`, publishing one `Frame` per tick with the engine's own RGB
  pixels).  No Tk, no HTTP, no dependencies beyond the pilot's.
- `jev-duum/jev_duum/panel/` — the Tk HMI, split by responsibility: `layout.py`
  (fixed numbers), `format.py` (pure helpers), `widgets.py` (primitives),
  `delta.py` (`DeltaCache`), `render.py` (apply-with-delta), `session.py`
  (`SessionModel`, the no-Tk presenter), `frame.py` (`HmiFrame`, one refresh),
  `zones/` (banner, game, decision, link, events), `dashboard.py` (compositor)
  and `loop.py` (the 60 Hz driver).
- `jev-duum/jev_duum/tui/` — the terminal frontend (`curses`, standard library
  only): the same panel over SSH, no display needed.  `render.py` is pure
  presentation, `colors.py` maps `theme.py` to ANSI, `app.py` is the loop.
- `jev-duum/jev_duum/telemetry/` + `overlays/` — session charts and the
  mini-automap / stale HUD.
- `jev-service/` — optional HTTP/WebSocket frontend over `session` (FastAPI,
  its own `pyproject.toml` so the pilot keeps one dependency).  Also serves the
  browser panel.  See [`docs/BACKEND.md`](docs/BACKEND.md).
- `jev-duum/tools/` — dev tools, all offline and at 0 $: `preview_panel.py`
  (screenshots of the five screen states), `dump_panel_tree.py` (deterministic
  widget-tree dump: the refactor gate), `record_headless.py` (video from the
  engine's own frames) and `decision_stage_mockup.py`.
- `jev-duum/tests/` — pytest suite; `jev-duum/artifacts/` is regenerable
  evidence and stays git-ignored.
- `scripts/` — `setup_duum.sh` (pinned engine) and `record.sh` (screen capture
  **or** backend frames into `video/<tipo>/`).
- `video/` — recordings.  The index (`video/README.md`) and the `.gitkeep` are
  versioned; **the media is not** (`.gitignore`: `mp4`, `mkv`, `mov`, `webm`,
  `gif` and each clip's `.json` sidecar).
- `map/` — schematic E1M1 knowledge (`sense.py`, `heuristics.py`,
  `doom_map.svg`), the source of truth, vendored into `jev_duum/_map/`.
- `jev-log/` + `docker-compose.yml` — optional MongoDB/Express audit log.
- `mods/balance.py` — reproducible, reversible engine patch (10× player health,
  10× player damage) applied to a pinned checkout; never committed into the
  engine.  `JEV_VANILLA=1` runs without it, and the mod is reversible.
- `docs/` — plans and measured results: [`BACKEND.md`](docs/BACKEND.md) (the
  backend/frontend split), [`REFACTOR.md`](docs/REFACTOR.md) (the package
  refactor and its gates), [`DESIGN.md`](DESIGN.md) (the HMI style guide) and
  the historical `*_PLAN.md`.  `duum/` is the pinned external engine (MPL-2.0,
  git-ignored, never edited).

## Build, Test, and Development Commands

```bash
./main.sh                                       # one command: engine + mod + game
bash scripts/setup_duum.sh                      # clone Duum at the pinned commit
cd jev-duum && uv sync                          # stdlib + Duum only
uv run --no-sync jev-duum --pilot jev-assisted  # play (bash play.sh wraps it)
uv run --no-sync jev-duum --pilot jev-assisted --tui   # same panel, in the terminal
uv run --no-sync ruff check jev_duum tests tools # lint
uv run --no-sync python -m pytest -q            # 219 pass, 5 skip
docker compose up -d                            # audit log :27017/:3000/:8081
bash scripts/record.sh --launch --window        # graba la partida en video/
bash scripts/record.sh --from-backend           # vídeo sin X (solo la vista del juego)
cd jev-service && uv sync && uv run --no-sync pytest -q    # frontend HTTP (12 tests)
uv run --no-sync jev-service --fake             # HTTP + navegador, modelo local
```

Three dev tools review or reproduce the interface offline, at 0 $:
`tools/preview_panel.py` (screenshots of the five screen states, for a human),
`tools/dump_panel_tree.py` (a deterministic dump of the whole widget tree — the
gate for a behaviour-preserving refactor, because screenshots print wall-clock
latency and are not reproducible) and `tools/record_headless.py` (video straight
from the engine's RGB buffer).

`scripts/record.sh` records into `video/<tipo>/` with a sortable name and a
`.json` sidecar, using NVENC when the GPU allows it.  Two modes, and they are not
interchangeable: **screen capture** (`--launch`, `--window`) grabs desktop
pixels — the only one that shows the SCADA panel, and `--window` is what keeps
other monitors out of the clip; **`--from-backend`** pipes the engine's own
frames to ffmpeg (exact, no X, no desktop) but records the game view only.  See
[`video/README.md`](video/README.md).

The five skips are the opt-in live smoke tests (`JEV_LIVE=1` plus a key). If the
sibling `duum/` checkout has commits on top of the adapter's pin, the adapter's
HEAD check makes every engine-backed test fail; point the suite at a worktree of
the pinned commit instead of touching the engine:
`JEV_DUUM_PATH=/path/to/duum-pinned uv run --no-sync python -m pytest -q`.

## Coding Style & Naming Conventions

- Python 3.11–3.13, 4-space indent, `ruff` at line length 100
  (`E4 E7 E9 F I`).
- `from __future__ import annotations`; value types are
  `@dataclass(frozen=True, slots=True)`.
- Lowercase modules, `PascalCase` types, `snake_case` functions and every JSON
  key sent to Jev — the prompts treat those names as a contract.
- Docstrings explain *why*. Edit `map/`, then copy the file into `_map/`; that
  package is excluded from lint on purpose.
- The palette and `FONTS` are defined **once**, in `theme.py`, and imported by
  `panel/`, `telemetry/`, `overlays/`, `tui/` and the service's browser page;
  never redefine a colour in a widget (the automap's own tones are `MAP_*` in
  `theme.py`, DESIGN.md §3.1).  `panel/` re-exports `GREEN`/`AMBER`/`RED` for its
  own tests.
- A package is a **facade**: its `__init__.py` re-exports the names callers
  import. Adding a zone or an instrument means a new module plus one import —
  never a new colour, never a second home for a datum.
- Comments and docstrings in the code are English; commit bodies and the
  user-facing docs mix Spanish and English as the history does.

## Testing Guidelines

- pytest: files `test_jev_<area>.py`, tests `test_<behaviour>()`.
- Keep tests offline — `conftest.py` sets `JEV_NO_LOG`; use the fake Jev client,
  never real HTTP or MongoDB.  The service tests fabricate frames, so they need
  no engine either.
- Live smoke tests need `JEV_LIVE=1` and `TYPESAFE_API_KEY`; five skips are
  expected. Keep the adapter boundary deterministic: no wall-clock, no
  randomness.
- **The gates, not just the count.** Three things must stay green and are what
  actually protects behaviour:
  - `tools/dump_panel_tree.py` before/after (`cmp`) — the Tk panel's widget tree.
  - `tests/test_jev_prompt_contract.py` and `tests/test_jev_snapshot_contract.py`
    — the bytes that travel to Jev.
  - `tests/test_jev_policy_equivalence.py` — every tick rule, exhaustively,
    against the expression it replaced.  A whole-loop A/B is **not** a valid
    gate: the decision worker is asynchronous, so two runs of the same loop
    legitimately diverge.

## Commit & Pull Request Guidelines

- Commit subject in short imperative form; the body says what changed and why.
  History mixes Spanish and English, e.g.
  `Jev pilot: paquete jev-duum y plan de reemplazo`.
- Pull requests: what and why, a linked issue, the `ruff` and `pytest` output,
  screenshots for UI changes, and the spend when the live API is called.

## Agent-Specific Instructions

- Treat `duum/` as read-only and pinned by commit; the adapter validates HEAD.
- **One owner for the engine.** It is single-threaded Python: only the Tk loop
  (`panel/loop.py`) or a `Session` may advance it, one per process.  A frontend
  reads frames and never touches the engine — the HTTP service reads a `Hub`,
  the TUI reads the frames `Session` publishes.
- **The tick rules live in `session/policy.py`.** Do not re-inline "should I ask
  the model?", "is this result still usable?", "is the level over?" or the
  refresh cadence anywhere: the Tk loop and the headless session must pace a
  session the same way, and that file has the tests.
- The Tk panel is presentation only: keep it delta-updating and never touch the
  60 Hz loop, the snapshot contract or the decision worker. `panel/loop.py`
  drives the loop; `panel/dashboard.py` is the compositor and `panel/session.py`
  the no-Tk presenter.
- The panel's presentation is governed by [`DESIGN.md`](DESIGN.md): a single
  fixed screen, no tabs, no scrolling and no animation, colour reserved for
  abnormal states, and colour never the only cue. Change the guide first, then
  `panel/`; review it offline with `tools/preview_panel.py` (0 $).
- The terminal UI is the same presentation in another medium: it must reuse
  `panel/format.py`, `panel/layout.py` and `panel/session.py` rather than
  re-derive confidence bands, axis order or the session series.
- `theme.py` is the one code home of the palette and `FONTS` (DESIGN.md §3);
  `panel/`, `telemetry/`, `overlays/` and `tui/` import it and never redefine a
  colour.
- `telemetry/` (DESIGN.md §5, "Telemetría de sesión") draws session charts
  from data that already exists — latency, `confidence` per head,
  `assistance_events`, `applied_controls`, health/ammo, tokens and cost. Keep
  the invariant intact: every instrument is a fixed-height canvas (with a modest
  request width so it cannot widen its column) or a clipped fixed-width label,
  so `tests/test_jev_hmi.py` keeps passing. Buffers are bounded `deque`s owned
  by `panel/session.py` (`SessionModel`), never by a widget, and redraw is
  throttled (~3 Hz) — never per tick, never with animation.
- The one responsive rule is a single reflow in `Dashboard._relayout`: below
  1600 px the bottom strip stacks `EVENTOS` over `BALANCE`; the numbered panels
  keep their cells. One datum keeps one home — do not mirror a value into a
  second panel.
- **Refactors must not change behaviour.** The panel's widget tree is the gate:
  `tools/dump_panel_tree.py` before and after, `cmp` must match; the request
  contract is pinned by `tests/test_jev_prompt_contract.py` and
  `tests/test_jev_snapshot_contract.py`. See [`docs/REFACTOR.md`](docs/REFACTOR.md).
- **Nothing is taken away from the terminal.** The default surface is the CLI:
  `./main.sh`, `--headless` with its JSON keys, `--record`, `--replay`, the four
  console scripts and `scripts/record.sh`.  New frontends are opt-in (`--tui`,
  `jev-service`) and `tests/test_jev_cli_surface.py` freezes the flags, the
  pilots and the entry points.
- **`jev-duum` has one dependency: `duum`.** A web framework, a charting library
  or a terminal toolkit do not belong in it: the service lives in `jev-service/`
  and the TUI uses `curses` from the standard library.
- The service binds to `127.0.0.1`, takes `--control-token` when exposed, and
  keeps `TYPESAFE_API_KEY` server-side: no client ever sees it.  It must not
  read the engine directly — it goes through a `Hub` fed by a `Session`.
- Adapters fail soft (return `None`, never raise into gameplay); pixels are
  never model input; never commit `.env`, keys or commercial WADs.
