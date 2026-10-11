# Repository Guidelines

## Project Structure & Module Organization

- `jev-duum/jev_duum/` — the pilot: `snapshot.py` → `prompts.py` →
  `controller.py` → `worker.py`/`panel.py`, plus `strategy.py`,
  `world_model.py`, `world_readout.py`, `overlays.py` and `jev_log.py`.
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
uv run --no-sync python -m pytest -q            # 131 pass, 4 skip
docker compose up -d                            # audit log :27017/:3000/:8081
```

## Coding Style & Naming Conventions

- Python 3.11–3.13, 4-space indent, `ruff` at line length 100
  (`E4 E7 E9 F I`).
- `from __future__ import annotations`; value types are
  `@dataclass(frozen=True, slots=True)`.
- Lowercase modules, `PascalCase` types, `snake_case` functions and every JSON
  key sent to Jev — the prompts treat those names as a contract.
- Docstrings explain *why*. Edit `map/`, then copy the file into `_map/`; that
  package is excluded from lint on purpose.

## Testing Guidelines

- pytest: files `test_jev_<area>.py`, tests `test_<behaviour>()`.
- Keep tests offline — `conftest.py` sets `JEV_NO_LOG`; use the fake Jev client,
  never real HTTP or MongoDB.
- Live smoke tests need `JEV_LIVE=1` and `TYPESAFE_API_KEY`; four skips are
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
  60 Hz loop, the snapshot contract or the decision worker.
- The panel's presentation is governed by [`DESIGN.md`](DESIGN.md): a single
  fixed screen, no tabs, no scrolling and no animation, colour reserved for
  abnormal states, and colour never the only cue. Change the guide first, then
  `panel.py`; review it offline with `tools/preview_panel.py` (0 $).
- Adapters fail soft (return `None`, never raise into gameplay); pixels are
  never model input; never commit `.env`, keys or commercial WADs.
