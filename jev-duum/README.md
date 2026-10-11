# Jev Duum

`jev-duum` is a focused demo in which **Jev** (TypeSafe System One) plays the
pure-Python [Duum](https://github.com/hmofet/duum) engine from compact semantic
state. Rendered pixels are never sent to the model.

Deployment is deliberately thin: only the standard library plus Duum — no
PyTorch, no CUDA, no local checkpoint. The trade-off is that Jev is a remote
API, so every decision is one HTTP request.

## Credential

Jev needs a TypeSafe API key. Put it in the git-ignored `./.env` or export it:

```bash
export TYPESAFE_API_KEY=...        # always wins over .env
```

The key is never embedded in the source, never printed, and never attached to
errors. A decision costs about $0.00003–$0.00005 of input tokens.

## Run

From this directory:

```bash
uv sync
uv run --no-sync jev-duum --pilot jev-assisted
```

Or through the wrapper, which reads `.env` for you:

```bash
bash play.sh              # windowed game with the decision panel
bash play.sh --headless   # no window, JSON summary
```

The bundled Freedoom Phase 1 IWAD (`freedoom1.wad`) is the default; it is
validated by header and SHA-256 on every run. Pass `--wad /path/to/file.wad`
for another legally obtained IWAD.

Useful modes:

```bash
# Manual window (human plays)
uv run --no-sync jev-duum --pilot manual

# Deterministic headless baseline (never touches the network)
uv run --no-sync jev-duum --pilot scripted --headless --ticks 600

# Eight paired policy experiments (this one costs real tokens)
uv run --no-sync jev-duum-eval --map E1M1 --ticks 3600
```

The interactive view uses one window: game in the center, state and controls on
the left, and model timing, probabilities, confidence, tokens and cost on the
right. Completed levels advance automatically.

## Questions the model answers

Every decision sends one request with three `choice` questions against a single
state:

| Question | Choices |
|---|---|
| movement | forward, back, strafe left, strafe right, hold |
| aim | left, straight, right |
| interaction | fire, use, neither |

Three frozen request shapes live in `jev_duum/prompts.py`:

| Version | State | Questions |
|---|---|---|
| `v1` | one flattened line per question (`hp=100 ... route=left/near/exit`) | one-line instructions, one-word criteria |
| `v2` | named JSON fields: `player`, `objective`, `threats`, `projectiles_inbound`, `pickups`, `usable_geometry`, `movement_options`, `situation`, and a `conventions` block | structured `instructions` and per-option rubrics (`what`, `use_when`, `not_for`) |
| `v3` | as `v2` plus a `strategy` block (mission, priority, focus, step-by-step plan, rules of engagement, `must_move`) and a `progress` score per movement option | rubrics that execute the plan instead of restating the policy |
| `v3w` (default) | as `v3` plus a `world_model` block from the schematic level map: room, route to the exit, nukage underfoot, 360-degree sector risk, hidden foes and hidden pickups | `v3` rubrics plus world-model rules; the block is published as *informative, not authoritative* |

`v2` follows
[Structure](https://docs.typesafe.ai/primitives/advanced). The model judges;
code computes. Every comparison that matters (`safe` flags, `shot_would_hit`,
tolerance degrees, distances) is precomputed into the state and quoted in the
rubric, and the bearing sign convention is stated explicitly. Select a version
with `--prompt-version v1|v2|v3|v3w` or `JEV_PROMPT_VERSION`; the packaged default is
the measured winner.

`v3` puts the strategy in code, not in the model: `jev_duum/strategy.py` decides
the mission ("reach the exit and keep moving"), the priority (`dodge` >
`resupply` > `retreat` > `fight` > `advance`), which threats deserve a reaction,
the step-by-step plan and whether standing still is allowed. Jev only answers
the three tactical `choice` questions inside that frame, and `enforce_strategy`
guarantees the plan: an unjustified `hold` is replaced by the safe direction
with the most progress and recorded as a `strategy-progress` event.

Record the snapshots behind every decision and compare prompts offline on
identical states:

```bash
uv run --no-sync jev-duum --pilot heuristic --headless --ticks 900 \
  --record artifacts/corpus.json --record-snapshots
uv run --no-sync jev-duum-prompt-eval --corpus artifacts/corpus.json \
  --versions v1,v2,v3 --order-probe --output artifacts/prompt-eval.json
```

Measured on a 397-snapshot E1M1 corpus (see
[`../docs/JEV_DUUM_PLAN.md`](../docs/JEV_DUUM_PLAN.md) for the full table):

| | `v1` | `v2` |
|---|---|---|
| guard interventions per decision | 1.07 | **0.20** |
| aim agreement with the reference | 0.59 | **0.96** |
| fire without a corridor | 0.41 | **0.00** |
| unsafe movement | 0.10 | **0.00** |
| answer stability with reversed criteria | 0.55–0.98 | **0.995–1.0** |
| input tokens per decision | 615 | 2595 |

A paired 600-tick live run dropped guard interventions from 134 to 14 with the
same kills; the structured prompt costs ~4.2x the tokens (~$0.0001 per
decision).

`v3` adds the code-owned strategy on top. Offline, over the same 397 snapshots:
moving 99.7% of decisions (was 59% with `v2`), longest freeze 1 decision (was
28), zero unsafe movement and zero shots without a firing corridor. Live, 600
ticks at 10 Hz: moving 86/100 (was 47/100), longest freeze 5 (was 30), 3 kills
and 15 sectors (was 2 and 9). It costs ~3.1k tokens per decision (~$0.00013, 5x
`v1`); 10 minutes at 10 Hz is ~$0.78. Full tables in
[`../docs/JEV_DUUM_PLAN.md`](../docs/JEV_DUUM_PLAN.md) §11.

## What the engine cannot see: the schematic world model

The canonical snapshot is tactical and myopic — visible enemies, projectiles in
flight, pickups on screen. The gameplay layer the engine cannot know by design
lives in `map/sense.py` and `map/heuristics.py` (stdlib only, vendored into
`jev_duum/_map/`): hidden foes with expected damage and line of sight,
360-degree sector risk, nukage underfoot, hidden items, and the room graph to
the exit. `jev_duum/world_model.py` adapts them into one JSON block that rides
inside `v3w` requests as `state.world_model`:

```bash
uv run --no-sync jev-duum --pilot jev-assisted --prompt-version v3w --headless --ticks 600
uv run --no-sync jev-duum --pilot jev-assisted --no-world-model   # A/B without it
```

Two things matter about this block. It is **informative, not authoritative**:
the prompt says so, and the snapshot plus the deterministic guard still own
navigation and safety. And it is **approximate by construction**: the schematic
SVG is not a faithful projection of the WAD (aspect 1.16 vs 1.79), so the
adapter anchors the transform at the player spawn and carries a `calibration`
field (`src: svg-approx`) inside the block for audit. Every failure returns
`None` — gameplay never depends on it.

## Every request and response is stored in MongoDB

The repository root ships a small stack (`docker-compose.yml`): MongoDB 7, the
Express API in `jev-log/`, and Mongo Express for browsing.

```bash
docker compose up -d                     # mongo :27017, api :3000, express :8081
curl -s localhost:3000/health            # {"ok":true,"db":"jevlog",...}
docker compose down                      # add -v to drop the volume
```

`jev_client` logs every call through `jev_duum/jev_log.py`: one document per
decision in `jevlog.jev_calls` holding the **full request state and questions**
plus the full raw response, tokens, cost, latency, model id and the metadata
(pilot, prompt version, strategy, logger stats). Logging is fire-and-forget on
a daemon thread: it never blocks a decision, never raises, and counts failures
in `stats` instead. `JEV_NO_LOG=1` disables it, `JEV_LOG_URL` points elsewhere,
`JEV_LOG_DEBUG=1` prints dropped documents.

```bash
curl -s "localhost:3000/calls?limit=5&pilot=jev-assisted"   # newest first
curl -s "localhost:3000/calls/<id>"                         # one complete call
```

## Project boundaries

- Duum remains an external, pinned engine dependency and imports no model code.
- Jev receives semantic snapshots, not the framebuffer.
- Raw model proposals and deterministic assistance remain separately recorded.
- Assisted play prioritizes critical health/ammo, restores a usable gun after
  collecting ammunition, and rejects melee targets blocked by walls or height.
- Jev pilots are online; the `scripted`, `random` and `heuristic` baselines are
  fully offline.
- Commercial Doom WADs must never be committed.

See [docs/JEV_INTEGRATION.md](docs/JEV_INTEGRATION.md) for architecture,
benchmarking, recording and replay details, and
[`../docs/JEV_DUUM_PLAN.md`](../docs/JEV_DUUM_PLAN.md) for the plan and measured
results.

## Licensing

Adapter code is Apache-2.0. Duum is MPL-2.0 and remains an external dependency.
See [NOTICE](NOTICE) for the upstream attribution this code is required to
carry. Freedoom Phase 1 is distributed under Freedoom's BSD 3-Clause license;
see [FREEDOOM_LICENSE.txt](FREEDOOM_LICENSE.txt).
