# Plan: reemplazar Laya por Jev en el piloto de Duum

Fecha: 2026-10-11 · Estado: **ejecutado** (ver §7 Resultados)

## 1. Resumen

Crear el paquete hermano `jev-duum/` que controla el motor Duum (pin
`87f4827f…`) usando el modelo remoto **Jev** (TypeSafe System One) en lugar de
Laya. Reutiliza íntegro el motor, el snapshot semántico, la capa de asistencia
determinista, el scheduler de 60 Hz, la grabación y el replay ya probados en
`laya-duum`; sólo se sustituye el backend de decisión. `laya-duum`,
`laya-coreml` y `duum` quedan intactos.

Es más liviano que Laya (sin PyTorch/CUDA ni checkpoint de ~0.8 GB; sólo stdlib
+ `duum`). A cambio, los pilotos `jev` no son offline: cada decisión es una
llamada HTTP a `api.typesafe.ai`.

## 2. Decisiones fijadas

| Decisión | Elección |
|---|---|
| Estructura | Paquete hermano nuevo `jev-duum/`; `laya-duum` y `laya-coreml` intactos |
| Credencial | `TYPESAFE_API_KEY` (gana si está exportada) + `.env` local ignorado por git |
| Alcance | Paridad completa: headless + ventana Tk + evaluación + record/replay + tests |

## 3. Interfaces públicas

- `jev_duum/jev_client.py`: `JevClient(api_key=None, model="jev-latest",
  endpoint=..., timeout=30, retries=3)` con `.ask(state, questions)` y
  `.models()`; stdlib puro; reintenta 429/529/5xx/`URLError` con backoff
  respetando `retry-after` y falla sin reintentar en 400/401/403/404/422; nunca
  imprime ni adjunta la clave. `JevError` para fallos irrecuperables.
- `jev_duum/controller.py`: `JevDuumController(*, client, assisted, api_key,
  model, endpoint)`. Reusa `QUESTIONS` (movement/aim/interaction) y `_assist()`
  sin cambios. `DecisionResult` añade `model_id`, `confidence`, `cost_usd`,
  `request_ms`; `input_tokens = {"request": n}`; `prediction_calls = 1`;
  `execution = "single-request"`.
- CLI `jev-duum`: pilotos `manual, scripted, random, heuristic, jev,
  jev-assisted`; `--model` es el id de Jev (default `jev-latest`), `--endpoint`.
  `jev-duum-eval` conserva la matriz de 8 experimentos con nombres `jev-*`.
- Esquemas: `jev-duum-episode-v1` y `jev-duum-evaluation-v1`. El campo `network`
  es `"online: api.typesafe.ai"` cuando hay controller y `"offline"` en los
  baselines y en la reproducción.

## 4. Cambios de implementación

- `pyproject.toml`: nombre `jev-duum`, dependencia única `duum` vía
  `[tool.uv.sources] path = "../duum"`, entrypoints `jev-duum` / `jev-duum-eval`.
- Se copian y adaptan `types, actions, scheduler, checkpoint, snapshot,
  observation, integration, pilots, worker, wad, recording, replay, benchmark,
  panel, evaluation, cli`; sólo `controller.py`, `jev_client.py` y `env.py` son
  nuevos.
- **Una petición por decisión**: `combined_state()` arma un `state` objeto
  (`tick`, `map`, `movement`, `aim`, `interaction`, tomados de las reducciones
  `full`) y las tres `choice` viajan en la misma llamada.
- Sin presupuesto de tokens: se elimina el `_fit_one`/`capacity` de Laya; los
  tokens salen de `usage` y el costo es `input_tokens × 0.042 / 1e6`.
- Red explícita: fuera `HF_HUB_OFFLINE`; `JevError` fail-closed (headless aborta
  con `model_error`; la ventana marca el error y deja de enviar).
- WAD: `default_wad_path()` cae a `../laya-duum/freedoom1.wad` si no hay copia
  local (no se duplican 28 MB).
- Clave: `play.sh` y el CLI cargan `.env` (sin sobreescribir el entorno); `.env`
  queda en `.gitignore`.

## 5. Plan de pruebas

- `uv run --no-sync pytest`: todo verde con `FakeJevClient` y `urllib`
  monkeypatcheado; ningún test unitario toca la red.
- `test_jev_controller.py`: una sola llamada por decisión; argmax → controles;
  asistencia conserva la propuesta cruda; rechazo de probabilidad no finita o
  muy desnormalizada; aceptación del redondeo real a dos decimales; error claro
  si falta la clave.
- `test_jev_client.py`: header `Authorization`, no filtración de la clave,
  reintento en 429 (respetando `retry-after`) y 529, sin reintento en 401, y
  cálculo de costo.
- `test_jev_offline.py`: el piloto `scripted` no abre ningún socket y reporta
  `network == "offline"`.
- `test_jev_live.py`: smoke opcional contra la API real, saltado salvo
  `JEV_LIVE=1` + clave.
- Copias adaptadas de `integration/snapshot/actions/scheduler/recording/worker/
  panel/evaluation/wad`.

## 6. Supuestos y defaults

- Modelo `jev-latest`; endpoint `https://api.typesafe.ai/v1/systemone`; precio
  $0.042/Mtok de entrada (salida gratis).
- El gating por umbral de confianza queda desactivado por defecto: la política
  es el argmax, igual que en `laya-duum`; la confianza sólo se registra.
- `laya-duum`, `laya-coreml` y `duum` no se modifican; el pin de Duum se respeta.
- Latencia esperada ~0.3 s por decisión; en headless el tiempo de pared lo
  domina la red y en la ventana el worker descarta resultados viejos.

## 7. Resultados (ejecución)

Entorno: `uv sync` instaló 10 paquetes, sin torch.

- `pytest`: **67 passed, 1 skipped** (el skip es el smoke en vivo). `ruff check`:
  limpio.
- Baseline offline: `jev-duum --pilot scripted --headless --ticks 3` →
  `network=offline`, `model_inference=false`, `cost_usd=null`, 0 conexiones.
- Smoke en vivo (`JEV_LIVE=1`): 1 decisión válida contra `jev-1.13.0`,
  probabilidades normalizadas y `cost_usd > 0`.
- Run real: `jev-assisted --headless --ticks 600` (10 s simulados) →
  100 decisiones, `prediction_calls == complete_decisions == 100`,
  `mean_decision_ms ≈ 275`, `p95 ≈ 384`, `cost_usd ≈ $0.0025`, 2 bajas, 0 daño.
- Replay del run grabado: `matched=true`, 10 checkpoints verificados,
  `model_inference=false`. El registro guarda `model_id=jev-1.13.0`,
  `confidence`, `tokens` y `cost_usd` por decisión.
- Evaluación: `jev-duum-eval --ticks 180` completó los 8 experimentos en 66 s de
  pared con 249 llamadas y un costo total de **$0.0047**.

Hallazgo de campo: Jev redondea las probabilidades a dos decimales y a veces una
pregunta de cinco opciones suma `0.99` (p. ej. `0.07+0.17+0.20+0.28+0.27`). La
validación se ajustó a esa realidad con tolerancia `0.05`; el argmax es
insensible a la normalización.

## 8. Ajuste posterior: el lanzador de siempre

`laya-duum/play.sh` ya no descarga PyTorch ni el checkpoint de Laya: ahora es un
lanzador fino que delega en `../jev-duum/play.sh`, conservando los mismos flags
(`--headless`, `--ticks`, …). Así el comando que siempre se usó sigue siendo uno
solo y simple, pero el piloto es Jev. Si el paquete `jev-duum` no está junto al
de `laya-duum`, el script falla con un mensaje claro en vez de arrancar Laya por
accidente. El código Python de `laya-duum` queda intacto: sólo cambia a qué
backend apunta el arranque.
