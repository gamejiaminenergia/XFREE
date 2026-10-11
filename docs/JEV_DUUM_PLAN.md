# Plan y diseño: Jev jugando Duum

Fecha: 2026-10-11 · Estado: **ejecutado**

## 1. Resumen

`jev-duum/` controla el motor Duum (pin `87f4827f…`) con el modelo remoto
**Jev** (TypeSafe System One). Reutiliza íntegro el motor, el snapshot
semántico, la capa de asistencia determinista, el scheduler de 60 Hz, la
grabación y el replay; el backend de decisión es lo único propio del paquete.

El despliegue es liviano: sólo la biblioteca estándar y `duum`, sin PyTorch, sin
CUDA y sin checkpoint local. A cambio, cada decisión es una llamada HTTP a
`api.typesafe.ai`.

## 2. Decisiones fijadas

| Decisión | Elección |
|---|---|
| Estructura | Paquete `jev-duum/`; `duum` es la única dependencia de código |
| Credencial | `TYPESAFE_API_KEY` (gana si está exportada) + `.env` local ignorado por git |
| Alcance | Headless + ventana Tk + evaluación + record/replay + tests |
| Política | Argmax de las probabilidades; la confianza se registra, no decide |

## 3. Interfaces públicas

- `jev_duum/jev_client.py`: `JevClient(api_key=None, model="jev-latest",
  endpoint=..., timeout=30, retries=3)` con `.ask(state, questions)` y
  `.models()`; stdlib puro; reintenta 429/529/5xx/`URLError` con backoff
  respetando `retry-after` y falla sin reintentar en 400/401/403/404/422; nunca
  imprime ni adjunta la clave. `JevError` para fallos irrecuperables.
- `jev_duum/controller.py`: `JevDuumController(*, client, assisted, api_key,
  model, endpoint)`. `QUESTIONS` define las tres `choice`. `DecisionResult`
  expone `probabilities`, `confidence`, `proposed_controls`, `applied_controls`,
  `assistance_events`, `observations`, `input_tokens`, `model_id`, `cost_usd`,
  `request_ms`, `decision_ms`, `prediction_calls` y `execution`.
- CLI `jev-duum`: pilotos `manual, scripted, random, heuristic, jev,
  jev-assisted`; `--model` es el id de Jev (default `jev-latest`), más
  `--endpoint`. `jev-duum-eval` corre la matriz de 8 experimentos.
- Esquemas: `jev-duum-episode-v1` y `jev-duum-evaluation-v1`. El campo `network`
  es `"online: api.typesafe.ai"` cuando hay controller, y `"offline"` en los
  baselines y en la reproducción.

## 4. Implementación

- `pyproject.toml`: nombre `jev-duum`, dependencia única `duum` vía
  `[tool.uv.sources] path = "../duum"`, entrypoints `jev-duum` / `jev-duum-eval`.
- Módulos: `types, actions, scheduler, checkpoint, snapshot, observation,
  integration, pilots, worker, wad, recording, replay, benchmark, panel,
  evaluation, cli, env`; el backend propio son `controller.py` y `jev_client.py`.
- **Una petición por decisión**: `combined_state()` arma un `state` objeto
  (`tick`, `map`, `movement`, `aim`, `interaction`, tomados de las reducciones
  `full`) y las tres `choice` viajan en la misma llamada.
- Tokens y costo salen de `usage`; el costo es `input_tokens × 0.042 / 1e6` y se
  acumula en el resumen y en la evaluación.
- Fail-closed ante `JevError`: headless aborta con `model_error`; la ventana
  marca el error y deja de enviar decisiones.
- WAD: `freedoom1.wad` viaja con el paquete y `default_wad_path()` lo resuelve.
- Clave: `play.sh`, el CLI y la evaluación cargan `.env` sin sobreescribir el
  entorno; `.env` está en `.gitignore`.

## 5. Pruebas

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
- Cubren además `integration, snapshot, actions, scheduler, recording, worker,
  panel, evaluation, wad`.

## 6. Supuestos y defaults

- Modelo `jev-latest`; endpoint `https://api.typesafe.ai/v1/systemone`; precio
  $0.042/Mtok de entrada (salida gratis).
- La confianza no decide por defecto: la política es el argmax; el gating por
  umbral queda como extensión explícita.
- `duum` no se modifica; el pin se respeta.
- Latencia esperada ~0.3 s por decisión; el tiempo de pared en headless lo
  domina la red y en la ventana el worker descarta resultados viejos.

## 7. Resultados medidos

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

## 8. Lanzador

`play.sh` es el punto de entrada: carga `.env`, sincroniza el entorno y arranca
`jev-duum --pilot jev-assisted` conservando los flags (`--headless`, `--ticks`,
`--size`, …). Su salida de estado va a stderr para que stdout quede como JSON
limpio cuando se usa `--headless`.

## 9. Licencias

El código del adaptador es Apache-2.0 y deriva de trabajo previo con esa misma
licencia; `jev-duum/NOTICE` conserva las atribuciones exigidas por Apache-2.0
§4(d). No hay pesos de modelo en el repositorio: Jev es una API remota.
