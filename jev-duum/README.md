# Jev Duum

`jev-duum` is a focused demo in which **Jev** (TypeSafe System One) plays the
pure-Python [Duum](https://github.com/hmofet/duum) engine from compact semantic
state. Rendered pixels are never sent to the model.

It is the sibling of [`laya-duum`](https://github.com/hadlock/laya-duum): the
same engine, snapshot, deterministic assistance, recording and replay, with the
local Laya checkpoint swapped for a remote judgment model. Deployment is
therefore much lighter — only the standard library plus Duum, no PyTorch, no
CUDA, no 0.8 GB checkpoint — at the cost of being **online**: every decision is
one HTTP request.

## Credential

Jev needs a TypeSafe API key. Put it in the git-ignored `./.env` (see
`./.env`, already present locally) or export it:

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

Duum is pinned to the same commit as `laya-duum`. The Freedoom Phase 1 IWAD is
not copied here; the default resolves to `../laya-duum/freedoom1.wad`. Pass
`--wad /path/to/file.wad` for another legally obtained IWAD.

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
named-field state:

| Question | Choices |
|---|---|
| movement | forward, back, strafe left, strafe right, hold |
| aim | left, straight, right |
| interaction | fire, use, neither |

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
benchmarking, recording and replay details. The implementation plan that
produced this package lives at [`../docs/JEV_DUUM_PLAN.md`](../docs/JEV_DUUM_PLAN.md).

## Licensing

Adapter code is Apache-2.0. Duum is MPL-2.0 and remains an external dependency.
Freedoom Phase 1 is distributed under Freedoom's BSD 3-Clause license; see
[FREEDOOM_LICENSE.txt](FREEDOOM_LICENSE.txt).
