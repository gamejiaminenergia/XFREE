# Documentation

Plans, architecture notes and measured results for the Jev pilot. The module
reference lives in [`../jev-duum/README.md`](../jev-duum/README.md).

| Document | What it covers |
|---|---|
| [`JEV_DUUM_PLAN.md`](JEV_DUUM_PLAN.md) | The pilot plan: request shapes (`v1`–`v3w`), token cost, guard interventions, live runs and the measured tables. |
| [`DOOM_JEV_HEURISTICS_PLAN.md`](DOOM_JEV_HEURISTICS_PLAN.md) | The schematic world model (`map/sense.py` + `map/heuristics.py`) and how it rides inside `v3w` requests as informative, not authoritative. |
| [`UI_IMPROVEMENT_PLAN.md`](UI_IMPROVEMENT_PLAN.md) | The Tk inspector redesign: sections and delta-update, meters with thresholds, mini-automap, fullscreen reflow and the request/response detail. |
| [`UI_IMPROVEMENTS_V2.md`](UI_IMPROVEMENTS_V2.md) | Iteration 2: an offline (\$0, no-Jev) audit of the shipped inspector, the concrete defects found and the phased improvement plan. |
| [`AI_DECISION_STAGE_PLAN.md`](AI_DECISION_STAGE_PLAN.md) | Iteration 3: a decision-first "stage" for a live AI congress — game demoted to PiP, the model's choice as protagonist, plus the offline mockup. |
| [`../jev-duum/docs/JEV_INTEGRATION.md`](../jev-duum/docs/JEV_INTEGRATION.md) | Architecture, benchmarking, recording and deterministic replay. |
