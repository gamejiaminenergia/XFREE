# Jev-controlled Duum

This adapter lets **Jev** (TypeSafe System One, `POST /v1/systemone`) play the
external pure-Python [Duum](https://github.com/hmofet/duum) engine from compact
semantic state. Rendered pixels are never sent to the model.

## Reproducible inputs

Duum is pinned to commit:

```text
87f4827f88b005515d92e6ed3c3756641ad2b0d0
```

The adapter installs with only the standard library and Duum:

```bash
uv sync                      # no torch, no CUDA, no local checkpoint
uv run --no-sync jev-duum --pilot scripted --headless --ticks 600
```

The bundled `freedoom1.wad` is the default (BSD-3 licensed Freedoom 0.13.0,
`28795076` bytes, sha256
`7323bcc168c5a45ff10749b339960e98314740a734c30d4b9f3337001f9e703d`). Each run
validates the WAD header and reports filename, size, kind and SHA-256 without
persisting the absolute path.

## Credential and network posture

Jev is a remote API, so Jev pilots are **online**. The key is read, in order,
from an explicit argument, `TYPESAFE_API_KEY`, or the git-ignored `./.env`
(loaded by `cli.py`/`evaluation.py` and by `play.sh`). It is never embedded in
the source, printed, or attached to exceptions. The `scripted`, `random` and
`heuristic` baselines remain fully offline and are covered by a socket-level
test that forbids any connection.

Endpoint `https://api.typesafe.ai/v1/systemone` (override with `--endpoint` or
`TYPESAFE_URL`). Pricing is $0.042 per million input tokens; output is free, so
the adapter records `input_tokens × 0.042 / 1e6` per decision.

## Play

The recommended mode is the guarded pilot at 10 decisions per simulated second
while physics and rendering stay at 60 Hz:

```bash
bash play.sh
# equivalent to:
uv run --no-sync jev-duum --pilot jev-assisted --decision-rate 10
```

Other modes:

```bash
# Model proposals without deterministic assistance
uv run --no-sync jev-duum --pilot jev

# Human control in Duum's normal Tk frontend
uv run --no-sync jev-duum --pilot manual

# Deterministic headless baseline (offline)
uv run --no-sync jev-duum --pilot scripted --headless --ticks 600
```

The single window has stats and resource bars on the left, Duum's unchanged
pixel render in the center, and live Jev probabilities, confidence, semantic
observations, the current strategy (mission, priority, plan steps, hold streak),
latency, tokens, cost and guard interventions on the right.

## Controller architecture

One decision is **one HTTP request**. The controller composes a single
named-field state from the canonical snapshot and asks all three `choice`
questions against it, which is how System One is meant to be used: the questions
are evaluated in parallel and only the extra tokens are paid. The request shape
is versioned; `--prompt-version v1` reproduces the original one-line questions,
`v2` sends the structured request below, `v3` adds the code-owned `strategy`
block that `v3`-era rubrics execute, and the default `v3w` adds the schematic
`world_model` (section below).

### The schematic world model (`v3w`)

`jev_duum/world_model.py` adapts `map/sense.py` and `map/heuristics.py`
(vendored into `jev_duum/_map/`) into one JSON block that travels as
`state.world_model`: current room and floor, `hazards` (nukage, damage per
tick, adjacent cells, teleporter, stairs), `route` over the room graph to the
exit, `sector_risk` (worst/safest 16-sector risk plus recommended and avoided
relative bearings), `hidden_foes` (counts plus top-3 threats with bearing,
distance, threat score, line of sight and expected damage) and `hidden_items`
(hidden count, secrets, top-3 aspirations). Bearings are published relative to
the player with the same sign convention as every other block (positive =
left), so the model never decodes a compass.

Three properties are deliberate. It is **informative, not authoritative**: the
prompt repeats that the snapshot and the deterministic guard win, so the block
widens context without moving authority away from code. It is **approximate and
labelled as such**: the schematic automap is not a faithful projection of the
WAD (vertex bounds aspect 1.16 versus wall bounds 1.79), so the adapter anchors
the transform at the measured spawn correspondence and reports
`calibration.src = "svg-approx"` inside the block. And it is **fail-soft**:
any exception returns `None`, which the prompt renders as a null field rather
than dropping the decision. `--no-world-model` gives a zero-cost A/B, and
`DecisionResult.world_model` / `world_model_used` record what actually shipped.

### Strategy in code, tactics in Jev

Jev is a System One model: it judges, it does not plan. `jev_duum/strategy.py`
makes the plan from the snapshot and the run history —
mission, priority (`dodge` > `resupply` > `retreat` > `fight` > `advance`),
focus, a step-by-step plan, rules of engagement, a `progress` score per movement
option, and an explicit permission (or prohibition) to stand still — and ships
it inside `state.strategy`. The model then only answers the three tactical
questions.

`StrategyTracker` remembers how many decisions in a row the player has held;
`enforce_strategy` guarantees the plan by replacing an unjustified `hold` with
the safe direction that makes the most progress and recording a
`strategy-progress` event. The deterministic guard shares the same `progress`
geometry, so guard and plan never fight each other.

```json
{
  "state": {
    "tick": 240, "map": "E1M1",
    "conventions": { "bearing_degrees": "Degrees to turn: positive means LEFT, negative means RIGHT.", "...": "..." },
    "player": { "health": 74, "armor": 0, "weapon": "pistol", "ammo": 50, "weapon_ready": true },
    "objective": { "kind": "exit", "bearing_degrees": 27.7, "route_length": 16,
                   "reachable": true, "aim_tolerance_degrees": 2.29, "forward_tolerance_degrees": 4.58 },
    "threats": [ { "bearing_degrees": 11.4, "distance_units": 100.7, "attacking": true,
                   "shot_would_hit": true, "melee_reachable": true } ],
    "projectiles_inbound": [],
    "pickups": [ { "category": "health", "bearing_degrees": 0.0, "need": "useful" } ],
    "usable_geometry": [],
    "movement_options": { "forward": { "safe": false, "clear_distance_units": 0.0 }, "...": "..." },
    "situation": { "stuck": false, "game_time": 4.0, "damage_received": 27, "kills": 0 },
    "strategy": {
      "mission": "advance",
      "priority": "advance",
      "status": "No relevant threat. The exit is left at near range.",
      "plan": ["Turn toward the objective and advance along the route.",
                "Move while turning; never idle in place.",
                "Standing still is not allowed this decision: pick a safe direction that makes progress."],
      "rules_of_engagement": ["Fire whenever a shot reaches a threat; ammunition is plentiful.", "..."],
      "must_move": true,
      "hold_streak": 0,
      "max_hold_streak": 5,
      "guide_bearing_degrees": 63.9,
      "progress": { "forward": 0.441, "strafe_left": 0.898, "strafe_right": -0.898, "back": -0.441 },
      "recommended_movement": "strafe_left"
    }
  },
  "model": "jev-latest",
  "questions": {
    "movement": {
      "type": "choice",
      "instructions": { "role": "...", "task": "...", "rules": ["..."] },
      "criteria": { "forward": { "what": "...", "use_when": "...", "not_for": "..." }, "...": "..." }
    },
    "aim": { "type": "choice", "instructions": { "...": "..." }, "criteria": { "...": "..." } },
    "interaction": { "type": "choice", "instructions": { "...": "..." }, "criteria": { "...": "..." } }
  }
}
```

The observation contains player resources, ranked visible threats, incoming
projectiles, one relevant pickup, nearby usable geometry, movement-clearance
probes, and an exit-route waypoint. In `v2`/`v3` those become named JSON fields
with numeric bearings and code-computed booleans, so the model never does
arithmetic and never has to decode a compressed token string; `v1` kept the
flattened per-question text produced by `build_observations`. Jev's 64k context
is large enough that no capacity-fitting fallback is needed. `v3` adds the
`strategy` block and a `progress` number per movement option, and marks each
threat `relevant` true or false.

Responses are validated before use: labels must match exactly, each value must
be a finite number in `[0, 1]`, and the sum must be within `0.05` of `1.0`
(Jev rounds to two decimals, so a five-option question can legitimately sum to
`0.99`). The argmax of each question yields `DuumControls`; the reported
`confidence` is recorded but does not gate behavior by default. On any transport
or validation failure the decision raises and the run is **fail-closed**:
headless aborts with `model_error`, and the windowed worker stops submitting
decisions.

Retry policy: `429`, `529`, `5xx` and transport errors retry with exponential
backoff (honoring `retry-after`, capped at 10 s); `400`, `401`, `403`, `404` and
`422` fail immediately without retrying.

## Audit log: every call in MongoDB

The root `docker-compose.yml` brings up MongoDB 7, the Express API in `jev-log/`
and Mongo Express (`:8081`). `JevClient.ask` calls `JevCallLogger` from
`jev_duum/jev_log.py` after each request, so one document per decision lands in
`jevlog.jev_calls` with the **complete** `state` and `questions` that were sent
plus the full raw response, tokens, cost, latency, resolved model id and
metadata (pilot, prompt version, stage, strategy, logger stats).

```bash
docker compose up -d
curl -s localhost:3000/health
curl -s "localhost:3000/calls?limit=5&pilot=jev-assisted"
```

The logger is fire-and-forget: documents are queued on a daemon thread and
posted with `urllib`, so a slow or missing API can never delay or fail a
decision; failures are counted in `logger.stats["dropped"]` and surfaced in each
document's metadata. `JEV_NO_LOG=1` turns it off, `JEV_LOG_URL` retargets it,
`JEV_LOG_DEBUG=1` prints drops. The log is the audit trail: any decision in the
database can be replayed against the exact prompt that produced it.

## Deterministic assistance

The assisted pilot preserves the raw proposal and records every override. Its
deterministic layer dodges predicted projectile impacts, rejects blocked
movement, pulse-controls turning between slower model decisions, fires only
through a valid corridor, uses doors and switches, restores a usable weapon,
prioritizes critical health/ammo, and follows a WAD-derived subsector route to
the exit.

The route uses Doom's actual SEGS/SSECTORS topology plus sampled within-sector
connectivity, and the adapter adds Doom linedef special 23 (E1M2's blue-key
platform) at the boundary without editing Duum's source.

## Evaluation and tuning

```bash
# Offline prompt A/B over snapshots recorded once (no engine, no gameplay)
uv run --no-sync jev-duum --pilot heuristic --headless --ticks 900 \
  --record artifacts/corpus.json --record-snapshots
uv run --no-sync jev-duum-prompt-eval --corpus artifacts/corpus.json \
  --versions v1,v2,v3,v3w --order-probe --output artifacts/prompt-eval.json
```

`jev-duum-prompt-eval` re-asks every version over the exact same snapshots and
reports, per version: agreement with the deterministic reference policy and the
assisted layer's own labels, agreement with the code's own plan, how many guard
interventions the proposal would trigger, the moving/progress/hold-streak
profile of the applied controls, mean confidence, tokens, request latency, cost,
and (with
`--order-probe`) how stable the answer is when the `criteria` keys are reversed.

```bash
uv run --no-sync jev-duum-eval \
  --map E1M1 --ticks 3600 \
  --output artifacts/jev-evaluation.json
```

The matrix compares scripted, random, heuristic, raw Jev at 12 Hz, and assisted
Jev at 5, 10, 12 and 20 Hz. A short 180-tick smoke run (3 simulated seconds)
completed the whole matrix with 249 prediction calls and a total cost of
`$0.0047`, which confirms the bookkeeping; longer runs are the tuning surface.
A Jev decision takes roughly 275 ms round-trip on the test machine, so the
windowed worker replaces stale snapshots instead of blocking the 60 Hz loop, and
headless wall time is dominated by the network. The `v2` state is larger
(~2.5k tokens per decision versus ~0.6k for `v1`), so the windowed worker's
latest-snapshot replacement matters more; the measured offline comparison is in
[`../../docs/JEV_DUUM_PLAN.md`](../../docs/JEV_DUUM_PLAN.md).

## Recording and replay

```bash
uv run --no-sync jev-duum \
  --pilot jev-assisted --headless --ticks 3600 \
  --record artifacts/e1m1.json

uv run --no-sync jev-duum --headless --replay artifacts/e1m1.json
```

Replay performs no inference and rejects a mismatched Duum commit or WAD hash.
Every recorded decision carries its probabilities, per-question confidence, the
resolved model id (`jev-1.13.0`, not the alias), the input tokens and the cost,
its `prompt_version`, and the guard's overrides, so a run can be audited and
re-priced after the fact. `--record-snapshots` additionally stores the canonical
snapshot and the request state behind each decision (schema
`jev-duum-episode-v2`); `v1` recordings still load and replay unchanged.

## Engine boundary

The integration uses Duum's existing mount, fixed clock, input bitmap, key,
tick, draw, collision, BSP and state interfaces; the pinned Duum checkout is not
modified. `Duum.tick()` remains authoritative at exactly 60 simulation ticks per
game second, and decision scheduling never changes engine time. The model is a
probabilistic selector over engineered semantic features — not learning Doom
from pixels. Raw mode exposes that policy directly; assisted mode is the
practical demonstration that combines it with deterministic geometry and safety.
