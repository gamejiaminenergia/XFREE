# Repository Guidelines

## Project Structure & Module Organization

- `jev-duum/jev_duum/` — the pilot: `snapshot/` → `prompts/` →
  `controller.py` → `worker.py`/`panel/`, plus `strategy.py`,
  `world_model.py`, `world_readout.py`, `overlays/`, `theme.py` (the single
  palette, screen and automap), `telemetry/` (the session charts) and
  `jev_log.py`.  The six former single-file modules are now packages with the
  **same dotted path**: each `__init__.py` is a facade that re-exports the old
  names, so every caller imports them unchanged.
- `jev-duum/jev_duum/panel/` — the HMI split by responsibility: `layout.py`
  (fixed numbers), `format.py` (pure helpers), `widgets.py` (primitives),
  `delta.py` (`DeltaCache`), `render.py` (apply-with-delta), `session.py`
  (`SessionModel`, the no-Tk presenter), `frame.py` (`HmiFrame`, one refresh),
  `zones/` (banner, game, decision, link, events), `dashboard.py` (compositor)
  and `loop.py` (the 60 Hz driver).
- `jev-duum/tests/` — pytest suite; `jev-duum/artifacts/` is regenerable
  evidence and stays git-ignored.
- `map/` — schematic E1M1 knowledge (`sense.py`, `heuristics.py`,
  `doom_map.svg`), the source of truth, vendored into `jev_duum/_map/`.
- `jev-log/` + `docker-compose.yml` — optional MongoDB/Express audit log.
- `mods/balance.py` — reproducible, reversible engine patch (10× player health,
  10× player damage) applied to a pinned checkout; never committed into the
  engine.
- `docs/` — plans and measured results. `duum/` is the pinned external engine
  (MPL-2.0, git-ignored, never edited).

## Build, Test, and Development Commands

```bash
./main.sh                                       # one command: engine + mod + game
bash scripts/setup_duum.sh                      # clone Duum at the pinned commit
cd jev-duum && uv sync                          # stdlib + Duum only
uv run --no-sync jev-duum --pilot jev-assisted  # play (bash play.sh wraps it)
uv run --no-sync ruff check jev_duum tests      # lint
uv run --no-sync python -m pytest -q            # 179 pass, 5 skip
docker compose up -d                            # audit log :27017/:3000/:8081
```

Two dev tools review the interface offline, at 0 $:
`tools/preview_panel.py` (screenshots of the five screen states) and
`tools/dump_panel_tree.py` (a deterministic dump of the whole widget tree, the
safe gate for a behaviour-preserving refactor — screenshots print wall-clock
latency and are not reproducible).

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
  `panel/`, `telemetry/` and `overlays/`; never redefine a colour in a widget
  (the automap's own tones are `MAP_*` in `theme.py`, DESIGN.md §3.1).
  `panel/` re-exports `GREEN`/`AMBER`/`RED` for its own tests.
- A package is a **facade**: its `__init__.py` re-exports the names callers
  import. Adding a zone or an instrument means a new module plus one import —
  never a new colour, never a second home for a datum.

## Testing Guidelines

- pytest: files `test_jev_<area>.py`, tests `test_<behaviour>()`.
- Keep tests offline — `conftest.py` sets `JEV_NO_LOG`; use the fake Jev client,
  never real HTTP or MongoDB.
- Live smoke tests need `JEV_LIVE=1` and `TYPESAFE_API_KEY`; five skips are
  expected. Keep the adapter boundary deterministic: no wall-clock, no
  randomness.

## Commit & Pull Request Guidelines

- Commit subject in short imperative form; the body says what changed and why.
  History mixes Spanish and English, e.g.
  `Jev pilot: paquete jev-duum y plan de reemplazo`.
- Pull requests: what and why, a linked issue, the `ruff` and `pytest` output,
  screenshots for UI changes, and the spend when the live API is called.

## Agent-Specific Instructions

- Treat `duum/` as read-only and pinned by commit; the adapter validates HEAD.
- The Tk panel is presentation only: keep it delta-updating and never touch the
  60 Hz loop, the snapshot contract or the decision worker. `panel/loop.py`
  drives the loop; `panel/dashboard.py` is the compositor and `panel/session.py`
  the no-Tk presenter.
- The panel's presentation is governed by [`DESIGN.md`](DESIGN.md): a single
  fixed screen, no tabs, no scrolling and no animation, colour reserved for
  abnormal states, and colour never the only cue. Change the guide first, then
  `panel/`; review it offline with `tools/preview_panel.py` (0 $).
- `theme.py` is the one code home of the palette and `FONTS` (DESIGN.md §3);
  `panel/`, `telemetry/` and `overlays/` import it and never redefine a colour.
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
- Adapters fail soft (return `None`, never raise into gameplay); pixels are
  never model input; never commit `.env`, keys or commercial WADs.
