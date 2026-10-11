# Contributing

Thanks for looking. This repository is a small, deliberately thin pilot, so the
rules are short.

## Get running

```bash
bash scripts/setup_duum.sh      # pinned Duum engine (never vendored)
cd jev-duum
uv sync
uv run --no-sync python -m pytest -q
```

The five skipped tests are the opt-in live smoke test: set `JEV_LIVE=1` and a
`TYPESAFE_API_KEY` (in `jev-duum/.env` or the environment) to run them. They cost
a fraction of a cent and exercise the whole wire path.

## Before you push

```bash
cd jev-duum
uv run --no-sync ruff check jev_duum tests
uv run --no-sync python -m pytest -q
```

CI runs exactly these two commands plus `uv sync --frozen` on a checkout of the
pinned Duum commit.

## Conventions

- **Line length 100, ruff `E4 E7 E9 F I`.** `ruff` is the single source of
  truth for lint; keep the tree clean before opening a pull request.
- **`jev_duum/_map/` is vendored verbatim** from `map/` at the repository root
  (the source of truth, standard library only). Only its imports were made
  package-relative. Change `map/`, then copy the file across — and leave the
  `_map` exception in `pyproject.toml` intact.
- **The loop is not a playground.** The Tk panel, the telemetry and the
  overlays are presentation only: they read snapshots and decisions and never
  touch the 60 Hz loop, the snapshot contract or the decision worker. Keep the
  panel delta-updating (only redraw what changed) so a resize costs no frames.
  The palette lives once in `theme.py`; the session charts in `telemetry/` are
  fixed-size canvases with bounded buffers (`panel/session.py` owns them),
  redrawn throttled, so the HMI invariant (`tests/test_jev_hmi.py`) keeps
  passing.
- **Six modules are packages with the same dotted path.** `snapshot/`,
  `prompts/`, `panel/`, `telemetry/`, `overlays/` and `prompt_eval/` keep a
  facade `__init__.py` that re-exports the old names; import them the same way
  and add code into the module that owns the responsibility.
- **A refactor must not change behaviour.** Before and after, run
  `tools/dump_panel_tree.py` and `cmp` the JSON; keep the request contract green
  in `tests/test_jev_prompt_contract.py` and
  `tests/test_jev_snapshot_contract.py`. See [`docs/REFACTOR.md`](docs/REFACTOR.md).
- **What travels to Jev is semantic.** No pixels, ever. Anything the panel
  shows that does not ride in the request is display-only and should be labelled
  as such (see the diagram's world tags).
- **Model failures never stop gameplay.** New adapters return `None` and the
  prompt/guard path degrades instead of raising.
- **Determinism.** The engine, baselines and replay paths are fixed-tick and
  reproducible; avoid wall-clock or randomness in the adapter boundary.

## Never commit

- `jev-duum/.env` or any TypeSafe key (the file is git-ignored on purpose).
- Commercial Doom WADs. Only Freedoom (BSD-3-Clause) is bundled.
- Anything under `artifacts/` or the Duum checkout: both are regenerable and
  git-ignored.

## Commit messages

Short imperative subject, then a body that says what changed and why. Spanish
or English are both fine; match the surrounding history.
