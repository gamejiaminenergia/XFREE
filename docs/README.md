# Documentation

Plans, architecture notes and measured results for the Jev pilot. The module
reference lives in [`../jev-duum/README.md`](../jev-duum/README.md).

| Document | What it covers |
|---|---|
| [`JEV_DUUM_PLAN.md`](JEV_DUUM_PLAN.md) | The pilot plan: request shapes (`v1`–`v3w`), token cost, guard interventions, live runs and the measured tables. |
| [`DOOM_JEV_HEURISTICS_PLAN.md`](DOOM_JEV_HEURISTICS_PLAN.md) | The schematic world model (`map/sense.py` + `map/heuristics.py`) and how it rides inside `v3w` requests as informative, not authoritative. |
| [`UI_IMPROVEMENT_PLAN.md`](UI_IMPROVEMENT_PLAN.md) | Iteration 1 (superseded): the Tk inspector redesign — sections and delta-update, meters with thresholds, mini-automap, fullscreen reflow. |
| [`AI_DECISION_STAGE_PLAN.md`](AI_DECISION_STAGE_PLAN.md) | Iteration 3 (superseded): a decision-first "stage" for a live AI congress — game demoted to PiP, the model's choice as protagonist. |
| [`../DESIGN.md`](../DESIGN.md) | **Current**: the HMI style guide (transmission-SCADA discipline) implemented by `panel/`, `theme.py` (the single palette, screen and automap) and `telemetry/` (the session charts) — types, zones, telemetry, prohibitions. |
| [`../jev-duum/docs/JEV_INTEGRATION.md`](../jev-duum/docs/JEV_INTEGRATION.md) | Architecture, benchmarking, recording and deterministic replay. |
