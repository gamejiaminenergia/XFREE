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
observations, latency, tokens, cost and guard interventions on the right.

## Controller architecture

One decision is **one HTTP request**. The controller composes a single
named-field state from the canonical snapshot and asks all three `choice`
questions against it, which is how System One is meant to be used: the questions
are evaluated in parallel and only the extra tokens are paid.

```json
{
  "state": { "tick": 0, "map": "E1M1",
             "movement": "...", "aim": "...", "interaction": "..." },
  "model": "jev-latest",
  "questions": {
    "movement":    { "type": "choice", "criteria": { "forward": "...", "...": "..." } },
    "aim":         { "type": "choice", "criteria": { "left": "...", "...": "..." } },
    "interaction": { "type": "choice", "criteria": { "fire": "...", "...": "..." } }
  }
}
```

The observation contains player resources, ranked visible threats, incoming
projectiles, one relevant pickup, nearby usable geometry, movement-clearance
probes, and an exit-route waypoint. The three `state` fields are the fullest
per-question reductions produced by `build_observations`; Jev's 64k context is
large enough that no capacity-fitting fallback is needed.

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
headless wall time is dominated by the network.

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
so a run can be audited and re-priced after the fact.

## Engine boundary

The integration uses Duum's existing mount, fixed clock, input bitmap, key,
tick, draw, collision, BSP and state interfaces; the pinned Duum checkout is not
modified. `Duum.tick()` remains authoritative at exactly 60 simulation ticks per
game second, and decision scheduling never changes engine time. The model is a
probabilistic selector over engineered semantic features — not learning Doom
from pixels. Raw mode exposes that policy directly; assisted mode is the
practical demonstration that combines it with deterministic geometry and safety.
