# Jev plays Duum

<!-- After pushing, uncomment and swap <you>/<repo> for the real slug:
[![CI](https://github.com/<you>/<repo>/actions/workflows/ci.yml/badge.svg)](https://github.com/<you>/<repo>/actions/workflows/ci.yml)
-->

**Jev** (TypeSafe System One) plays the pure-Python [Duum](https://github.com/hmofet/duum)
engine from a compact **semantic** state: one HTTP request per decision asking
three tactical questions — movement, aim, interaction. The framebuffer never
leaves the machine, a deterministic guard enforces safety on top of the model's
answer, and every request/response pair is kept for audit.

```
Duum (60 Hz) ─▶ SnapshotBuilder ─▶ semantic state ─▶ POST api.typesafe.ai
     ▲                                                      │
     └──────── controls ◀─ deterministic guard ◀── argmax ◀─┘
```

The project ships no model weights: Jev is a remote API, so the deployment is
standard library + Duum only. A decision costs about $0.00003–$0.00005.

**To run it, just one command:** `./main.sh`

## What is in this repository

| Path | What it is |
|---|---|
| `jev-duum/` | The pilot: snapshot → TypeSafe request → guard → engine, the Tk inspector, the offline prompt harness and the bundled Freedoom IWAD. |
| `map/` | Schematic E1M1 knowledge (`sense.py`, `heuristics.py`, `doom_map.svg`), stdlib only; vendored into `jev_duum/_map/`. |
| `jev-log/` | Small Express API that stores one document per model call in MongoDB. |
| `docker-compose.yml` | MongoDB 7 + that API + Mongo Express, for the passive audit log. |
| `docs/` | Plans, architecture notes and the measured results. |
| `scripts/setup_duum.sh` | Clones the pinned Duum engine at the exact commit this code expects. |

Duum itself is **not** vendored — it stays an external, pinned dependency.

## Requirements

- Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/)
- The pinned Duum checkout (fetched for you by `./main.sh`)
- A TypeSafe API key
- Optional: Tk for the game window, Docker for the audit log

## Quickstart

```bash
./main.sh
```

That is the whole thing. The **first run** asks for your `TYPESAFE_API_KEY` once
(typed into the terminal, saved git-ignored, never printed) and then plays. It
finds or clones the pinned engine, syncs the environment, applies the balance
mod and opens the single window: **the game on the left, the AI's decision on
the right**.

<details>
<summary>Optional flags — you do not need any of these</summary>

```bash
./main.sh --windowed                 # normal window instead of fullscreen
./main.sh --headless --ticks 600     # no window, JSON summary
./main.sh --pilot manual             # you play instead of the AI
JEV_VANILLA=1 ./main.sh              # skip the balance mod
```

`bash play.sh` (from `jev-duum/`) is the same demo without the engine bootstrap.
The bundled `freedoom1.wad` (Freedoom Phase 1, BSD-3-Clause) is validated by
header and SHA-256; `--wad /path/to/file.wad` accepts another legal IWAD.

</details>

<details>
<summary>Manual setup — only if you do not want <code>./main.sh</code> to do it for you</summary>

```bash
git clone https://github.com/<you>/<repo>.git
cd <repo>
bash scripts/setup_duum.sh            # pinned engine (MPL-2.0)
cp jev-duum/.env.example jev-duum/.env
$EDITOR jev-duum/.env                 # set TYPESAFE_API_KEY
cd jev-duum && uv sync
bash play.sh
```

</details>

## The window — one fixed screen, nothing to select

The banner carries the product title `SCADA+IA+JEV+DOOM` (subtitle
`Supervisión en tiempo real · jev-1.13.0`), the map, the tick/clock, the link
state and the alarm summary. Below it, a fixed three-column grid:

- **Left — the game and the world.** The live Duum view at the engine's own
  crisp integer zoom; the health/armor/ammo meters and the episode table; the
  schematic mini-map with its tags, the threat lines and the vital traces
  (health/ammo with a mark on every guard intervention).
- **Centre — the decision.** One row per typed question (`MOVIMIENTO` /
  `APUNTADO` / `ACCIÓN`, plus `OBJETIVO` on the hunt prompts), the chosen answer
  in large type, the full probability bar and confidence band, the
  **deterministic guard** as proposed→applied, the `POR QUÉ` observations, the
  strategy plan, and the latency sparkline (p50/p95 references).
- **Right — the link.** The session KPIs (decisions, p50/p95, tokens, cost); the
  request (`state` index, typed questions, token/cost consumption); the response
  (confidence per head, previous→current controls, raw JSON).
- **Bottom — events and balance.** `EVENTOS` (newest first, one row per
  decision, with the guard's motive) beside `BALANCE` (guard intervention rate
  and rule ranking, applied-movement and action distribution).

Nothing is behind a tab and nothing scrolls: everything is always on screen.
Launch it with `./main.sh`.

<details>
<summary>Rehearse for free, offline — dev tool, no API key, no network</summary>

```bash
cd jev-duum
python3 tools/preview_panel.py             # offline shots of the fixed screen (no tabs)
python3 tools/dump_panel_tree.py           # deterministic widget-tree dump (refactor gate)
python3 tools/record_headless.py --fake --seconds 10 --out /tmp/clip.mp4   # video, no X
python3 tools/decision_stage_mockup.py     # the design mockup
```

Rendered with a constant fake model answer; Pillow is optional and only used to
save the PNG.

</details>

## Run modes

<details>
<summary>Advanced — prompt versions, offline baselines and evaluations</summary>

```bash
# Jev plays, windowed and fullscreen by default (--windowed for a normal window)
uv run --no-sync jev-duum --pilot jev-assisted

# The same panel in the terminal: headless engine, no X, works over SSH
uv run --no-sync jev-duum --pilot jev-assisted --tui

# The same session over HTTP + WebSocket, with the panel in a browser
cd ../jev-service && uv sync && uv run --no-sync jev-service --fake

# Same, without the world-model block, to A/B it
uv run --no-sync jev-duum --pilot jev-assisted --no-world-model --headless --ticks 600

# Human plays
uv run --no-sync jev-duum --pilot manual

# Deterministic offline baselines (never touch the network)
uv run --no-sync jev-duum --pilot scripted --headless --ticks 600

# Eight paired policy experiments with real tokens (~$0.78 / 10 min at 10 Hz)
uv run --no-sync jev-duum-eval --map E1M1 --ticks 3600
```

Choose the request shape with `--prompt-version v1|v2|v3|v3w` (default `v3w`).
See [`jev-duum/README.md`](jev-duum/README.md) for the prompt tables, the
offline prompt harness and the measured results.

</details>

## Session telemetry

Filling the slack that used to be black, seven instruments read data the pilot
already has (`jev_duum/telemetry/`): a latency sparkline with p50/p95 lines
and amber points over p95; confidence per head (MOV/APU/ACC); guard intervention
rate and the most frequent rules; applied-movement and action distribution;
health/ammo traces with a mark per intervention; tokens in/out plus running and
average cost; and a previous→current control line. They redraw on a throttle
(~3 Hz) from bounded buffers, never touch the 60 Hz loop, and — like every panel
— never change size with their data.

The window starts fullscreen and reflows on resize: below 1600 px the bottom
strip stacks `EVENTOS` over `BALANCE` instead of overflowing. `F11` toggles
fullscreen; because there is no title bar then, the top-right corner also
carries `F11` and `CERRAR`.

## Audit log (optional)

```bash
docker compose up -d          # mongo :27017, api :3000, mongo express :8081
curl -s localhost:3000/health

cd jev-duum
uv run --no-sync jev-duum --pilot jev-assisted --log-calls
curl -s "localhost:3000/calls?limit=5"      # newest first, full request + response
docker compose down           # add -v to drop the volume
```

Logging is fire-and-forget on a daemon thread: it never blocks a decision and
never raises. `JEV_NO_LOG=1` disables it, `JEV_LOG_URL` points elsewhere.

## Develop

```bash
cd jev-duum
uv run --no-sync ruff check jev_duum tests
uv run --no-sync python -m pytest -q          # 219 pass, 5 skipped (live API)
```

The five skips are the opt-in live smoke test (`JEV_LIVE=1` plus a key). See
[CONTRIBUTING.md](CONTRIBUTING.md) for the conventions, including why
`jev_duum/_map/` is excluded from linting.

## Documentation

- [`docs/JEV_DUUM_PLAN.md`](docs/JEV_DUUM_PLAN.md) — the plan and the measured
  results (prompts, tokens, guard interventions, live runs).
- [`docs/DOOM_JEV_HEURISTICS_PLAN.md`](docs/DOOM_JEV_HEURISTICS_PLAN.md) — the
  schematic world model that rides inside `v3w` requests.
- [`docs/UI_IMPROVEMENT_PLAN.md`](docs/UI_IMPROVEMENT_PLAN.md) — the inspector
  redesign, fullscreen reflow and request/response detail.
- [`DESIGN.md`](DESIGN.md) — **current**: the HMI style guide (transmission
  SCADA discipline) that `panel/`, `theme.py` and `telemetry/` implement.
- [`docs/BACKEND.md`](docs/BACKEND.md) — **current**: the backend/frontend
  split, the terminal UI (`--tui`), the HTTP service and recording from the
  engine's own frames.
- [`docs/REFACTOR.md`](docs/REFACTOR.md) — the MVC/SOLID refactor of the big
  modules into packages, its frozen contracts and how to revert it.
- [`docs/AI_DECISION_STAGE_PLAN.md`](docs/AI_DECISION_STAGE_PLAN.md) — the
  decision-first layout for a live AI talk (now the single window).
- [`jev-duum/docs/JEV_INTEGRATION.md`](jev-duum/docs/JEV_INTEGRATION.md) —
  architecture, benchmarking, recording and replay.

## Licensing and attribution

Adapter code in this repository is **Apache-2.0**; see [LICENSE](LICENSE) and
[NOTICE](NOTICE) for the upstream attributions this distribution must carry.

- **Duum** is MPL-2.0 and remains an external dependency (never vendored).
- **Freedoom: Phase 1** is distributed under its BSD 3-Clause license; see
  [`jev-duum/FREEDOOM_LICENSE.txt`](jev-duum/FREEDOOM_LICENSE.txt).
- Commercial Doom WADs must never be committed to this repository.

This is an independent project, not an official Convai Innovations, Apple or
TypeSafe release.
