# Plan y diseño: Jev jugando Duum

Fecha: 2026-10-11 · Estado: **ejecutado**

## 1. Resumen

`jev-duum/` controla el motor Duum (pin `87f4827f…`) con el modelo remoto
**Jev** (TypeSafe System One). Reutiliza íntegro el motor, el snapshot
semántico, la capa de asistencia determinista, el scheduler de 60 Hz, la
grabación y el replay; el backend de decisión es lo único propio del paquete.
Las peticiones a Jev están versionadas: `v3` (default) manda estado estructurado
con campos nombrados, rúbricas por opción y el plan que arma el código (§11);
`v2` conserva la forma estructurada sin estrategia (§10) y `v1` la original,
para poder medir todas sobre los mismos snapshots.

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
| Peticiones | `prompts.py` con tres versiones congeladas; `v3` (estrategia + rúbricas) es la default |

## 3. Interfaces públicas

- `jev_duum/jev_client.py`: `JevClient(api_key=None, model="jev-latest",
  endpoint=..., timeout=30, retries=3)` con `.ask(state, questions)` y
  `.models()`; stdlib puro; reintenta 429/529/5xx/`URLError` con backoff
  respetando `retry-after`, reintenta también cortes de conexión sueltos y falla
  sin reintentar en 400/401/403/404/422; nunca imprime ni adjunta la clave.
  `JevError` para fallos irrecuperables.
- `jev_duum/controller.py`: `JevDuumController(*, client, assisted, api_key,
  model, endpoint, prompt_version)`. `parse_answers` valida la respuesta,
  `argmax_controls` la reduce y `DecisionResult` expone `probabilities`,
  `confidence`, `proposed_controls`, `applied_controls`, `assistance_events`,
  `observations`, `input_tokens`, `model_id`, `cost_usd`, `request_ms`,
  `decision_ms`, `prediction_calls`, `execution` y `prompt_version`.
- `jev_duum/prompts.py`: `PROMPT_VERSIONS`, `build_state(snapshot, version)`,
  `build_questions(version, reverse_order=False)` y `snapshot_from_dict`.
  `v1` congela las preguntas y el estado aplanado originales; `v2` es el estado
  estructurado con rúbricas; `v3` añade el bloque `strategy` y el `progress` por
  opción y es la default. Los umbrales compartidos con el guardia viven en
  `types.py`.
- `jev_duum/strategy.py`: `StrategyTracker`, `compute_strategy`,
  `enforce_strategy` y `guide_bearing`. El código decide misión, prioridad,
  foco, plan, reglas de enfrentamiento y permiso de quietud; `DecisionResult`
  expone `strategy`.
- `jev_duum/geometry.py`: `progress_scores`, `best_progress_movement` y
  `best_clear_movement`, compartidos por la estrategia, el guardia y el loop de
  60 Hz para que nadie empuje en direcciones distintas.
- `jev_duum/assistance.py`: `apply_assistance(snapshot, proposed)`,
  `reference_controls(snapshot)` y `reference_fire_allowed(snapshot)`. El
  guardia determinista es una función pura reutilizada como referencia etiquetada.
- CLI `jev-duum`: pilotos `manual, scripted, random, heuristic, jev,
  jev-assisted`; `--model` es el id de Jev (default `jev-latest`), más
  `--endpoint`, `--prompt-version` y `--record-snapshots`. `jev-duum-eval` corre
  la matriz de 8 experimentos y `jev-duum-prompt-eval` compara prompts sobre un
  corpus grabado.
- Esquemas: `jev-duum-episode-v2` (acepta v1 para replay),
  `jev-duum-evaluation-v1` y `jev-duum-prompt-eval-v1`. El campo `network`
  es `"online: api.typesafe.ai"` cuando hay controller, y `"offline"` en los
  baselines y en la reproducción.

## 4. Implementación

- `pyproject.toml`: nombre `jev-duum`, dependencia única `duum` vía
  `[tool.uv.sources] path = "../duum"`, entrypoints `jev-duum` / `jev-duum-eval`.
- Módulos: `types, actions, scheduler, checkpoint, snapshot, observation,
  integration, pilots, worker, wad, recording, replay, benchmark, panel,
  evaluation, cli, env`; el backend propio son `controller.py` y `jev_client.py`.
- **Una petición por decisión**: `combined_state()` arma un `state` objeto
  y las tres `choice` viajan en la misma llamada. En `v2` el estado son campos
  nombrados (`conventions`, `player`, `objective`, `threats`,
  `projectiles_inbound`, `pickups`, `usable_geometry`, `movement_options`,
  `situation`): el código calcula los booleanos y las tolerancias, el modelo
  juzga.
- **Corpus y A/B**: `--record-snapshots` guarda el snapshot canónico y el estado
  de cada decisión (también para pilotos offline); `jev-duum-prompt-eval`
  re-consulta cada versión sobre los mismos estados y reporta acuerdo con la
  referencia, intervenciones del guardia predichas, confianza, tokens y costo.
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
  reintento en 429 (respetando `retry-after`), 529 y cortes de conexión, sin
  reintento en 401, y cálculo de costo.
- `test_jev_prompts.py`: `v1` congelado, etiquetas de `criteria` idénticas en
  ambas versiones, forma estructurada de `instructions`/`criteria`, inversión de
  orden sin cambio de contenido, estado `v2` numérico y acotado, y round-trip
  `snapshot → dict → snapshot` con el mismo hash.
- `test_jev_prompt_eval.py`: la referencia geométrica, separación `v1`/`v2` en
  un corpus sintético (intervenciones, disparo sin corredor, movimiento
  inseguro), sonda de orden y lectura del corpus desde grabación o lista.
- `test_jev_recording.py`: captura de snapshots con pilotos offline (sin red),
  esquema v2, grabaciones v1 todavía cargables y replay del registro magro.
- `test_jev_strategy.py`: precedencia de misión, relevancia de amenazas,
  geometría de `progress`, permiso de quietud, anti-congelamiento, escape de
  proyectiles, retroceso por salud crítica y reinicio del tracker.
- `test_jev_offline.py`: el piloto `scripted` no abre ningún socket y reporta
  `network == "offline"`.
- `test_jev_live.py`: smoke opcional contra la API real, saltado salvo
  `JEV_LIVE=1` + clave.
- Cubren además `integration, snapshot, actions, scheduler, recording, worker,
  panel, evaluation, wad`.

## 6. Supuestos y defaults

- Modelo `jev-latest`; endpoint `https://api.typesafe.ai/v1/systemone`; precio
  $0.042/Mtok de entrada (salida gratis).
- Prompt default `v3` (estrategia + rúbricas), con `v1` y `v2` disponibles por
  `--prompt-version` para reproducir las comparaciones; `JEV_PROMPT_VERSION`
  permite fijarlo por entorno.
- Estrategia: misión "avanzar siempre"; amenaza relevante = ataca, <240, melee o
  en corredor; `hold` prohibido mientras exista una dirección segura con
  `progress > 0` y tope de 5 decisiones quieto (0.5 s a 10 Hz); retroceso bajo
  40 de salud.
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

## 10. Peticiones estructuradas (v2) — ejecutado el 2026-10-11

**Diagnóstico (grabación `artifacts/e1m1-jev.json`, 100 decisiones con `v1`).**
El modelo pidió `hold` 61 veces (confianza media 0.34), `straight` 86 veces con
el objetivo a 27° de lado, disparó sin corredor en 18 decisiones y la capa
determinista tuvo que corregirlo 120 veces. Causa: el estado aplanado
(`hitscan-enemy/left-small/far/not-aligned/melee-blocked`) no lleva números,
umbrales ni convención de signo, y las preguntas son de una línea con criterios
de una palabra.

**Cambio.** `prompts.py` con dos versiones congeladas. `v2` manda campos
nombrados (`conventions`, `player`, `objective`, `threats`,
`projectiles_inbound`, `pickups`, `usable_geometry`, `movement_options`,
`situation`) con bearings numéricos y booleanos calculados en código
(`shot_would_hit`, `safe`, tolerancias), y pregunta con `instructions` en objeto
y `criteria` por opción (`what`, `use_when`, `not_for`). Las reglas espejan los
umbrales exactos del guardia determinista, que sigue intacto.

**Corpus.** 397 snapshots de E1M1 en `artifacts/corpus.json`: heuristic 900
ticks, random 600, scripted 480 y una corrida `jev-assisted` de 400 ticks; el
A/B re-consulta ambas versiones sobre los mismos estados.

| Métrica (397 snapshots pareados) | `v1` | `v2` | Criterio |
|---|---|---|---|
| Intervenciones del guardia por decisión | 1.071 | **0.196** | −≥30% ✓ (−82%) |
| Acuerdo de `aim` con la referencia | 0.589 | **0.957** | — |
| Giro en dirección contraria | 0.018 | 0.023 | <5% ✓¹ |
| `straight` fuera de tolerancia | 0.393 | **0.020** | <10% ✓ |
| Disparo sin corredor | 0.408 | **0.000** | <3% ✓ |
| Disparo con arma en recarga | 0.055 | **0.000** | — |
| Movimiento inseguro | 0.096 | **0.000** | 0 ✓ |
| Acuerdo de movimiento con la referencia | 0.395 | **0.771** | — |
| Confianza media (mov/aim/inter) | 0.26/0.45/0.62 | **0.86/0.80/0.99** | — |
| Tokens de entrada por decisión | 615 | 2595 | ≤4x ⚠ (4.2x) |
| p95 de latencia | 438 ms | 455 ms | +≤50 ms ✓ |

¹ `v1` casi no gira (`straight` en 55% de las decisiones), así que su error de
dirección es bajo por omisión, no por acierto; el acuerdo con la referencia y
las demás filas muestran la diferencia real.

**Sesgo de orden** (200 snapshots, mismos estados con las claves de `criteria`
invertidas): `v1` coincide 0.545/0.860/0.975 (movimiento/aim/interacción) y `v2`
**0.995/1.000/1.000**; la estructura elimina casi por completo la preferencia por
la primera opción.

**Verificación en vivo** (E1M1, 600 ticks, 10 Hz, 100 decisiones por versión,
misma semilla):

| | `v1` | `v2` |
|---|---|---|
| Intervenciones del guardia | 134 | **14** (−90%) |
| Kills / salud final / sectores | 2 / 100 / 8 | 2 / 103 / 9 |
| Latencia media / p95 | 297 / 421 ms | 298 / 432 ms |
| Costo de la corrida | $0.0025 | $0.0107 |

**Corrida de integración real (v2, default).** `--record-snapshots` sobre 400
ticks asistidos: 67 decisiones, 9 intervenciones y 2 kills; el registro guarda
versión de prompt, estado estructurado y snapshot de cada decisión.

**Desviación conocida.** El costo es 4.2x `v1` en el corpus offline y 4.3x en
la corrida en vivo (~$0.00010–0.00011 por decisión) contra un presupuesto de 4x;
10 minutos a 10 Hz cuestan ~$0.65, aún despreciable frente al ahorro de
intervenciones. Recortar más texto exigiría re-medir la calidad, así que se
documenta en vez de asumirse.

**Cola de trabajo identificada.** Las 59 intervenciones restantes son el modelo
intentando desatascarse (`situation.stuck`) mientras el guardia quiere girar en
el sitio; y unos pocos casos donde el modelo sigue la ruta en vez de apuntar a
un enemigo despierto a más de 900 unidades. Ambos son juicios defendibles; si se
quiere converger, el siguiente paso es decidir cuál política es la correcta y
mover el umbral en código, no en el texto.

## 11. Estrategia en código (v3) — ejecutado el 2026-10-11

**Diagnóstico (grabación en vivo con `v2`).** El bot estuvo quieto 53 de 100
decisiones, con una racha de **30 seguidas (3 s) girando** hacia un enemigo lejano
que no atacaba, mientras la salida quedaba a 60° de lado. La causa era el propio
prompt: heredaba la regla del guardia "avanza solo si la ruta está a ≤4.6°", y la
ruta está a 60° de mediana (>90° en el 38% de los estados). Solo el 16% de los
estados tenía una amenaza real (ataca, <240 o melee) y solo el 2% tenía arma lista
+ corredor de tiro.

**Cambio: el código planea, Jev ejecuta.** Nuevo módulo `strategy.py` que por
decisión calcula misión, prioridad, foco, plan en pasos, reglas de enfrentamiento
y una garantía anti-congelamiento; el bloque viaja dentro de la petición
(`state.strategy`) y Jev solo resuelve las tres `choice`.

- Misión fija: "llegar a la salida sin dejar de moverse".
- Prioridad con precedencia: `dodge` (impacto inminente <0.4 s) → `resupply`
  (pickup crítico) → `retreat` (salud <40 bajo fuego) → `fight` (amenaza
  relevante) → `advance`.
- Amenaza relevante = ataca, está a <240, es alcanzable a melee o ya está en el
  corredor; el resto es paisaje y no merece un giro.
- `progress` geométrico por opción (`cos(ángulo − bearing del objetivo)`): el
  código y el prompt comparten el mismo número, y `hold` solo es legal si
  ninguna dirección segura progresa (o si el plan es usar la puerta de enfrente).
- Garantía: `must_move` prohíbe `hold`; si el modelo insiste, `enforce_strategy`
  lo reemplaza por la mejor opción segura con progreso y lo registra como
  evento `strategy-progress`.
- El guardia determinista deja de preferir "girar en el sitio" y también usa el
  `progress` compartido; `settle_assisted_controls` mantiene el movimiento
  mientras el giro continúa.

**Corpus offline** (397 snapshots pareados, mismas condiciones que §10):

| Métrica | `v1` | `v2` | `v3` | Criterio |
|---|---|---|---|---|
| Decisiones moviendo | 0.977 | 0.592 | **0.997** | ≥0.70 ✓ |
| Con progreso hacia la meta | 0.723 | 0.592 | **0.997** | — |
| Racha máxima quieto | 3 | 28 | **1** | ≤5 ✓ |
| Tasa de `hold` | 0.023 | 0.408 | **0.003** | — |
| Movimiento inseguro (aplicado) | 0.000 | 0.000 | **0.000** | 0 ✓ |
| Propuesta insegura del modelo | 0.091 | 0.000 | **0.000** | — |
| Disparo sin corredor | 0.401 | 0.000 | **0.000** | <3% ✓ |
| Acuerdo de `aim` con el guardia | 0.574 | 0.955 | 0.927 | — |
| Errores de giro contra el plan | — | — | **0.000** | — |
| Acuerdo de `aim` con el plan de código | — | — | **0.987** | — |
| Intervenciones del guardia | 1.403 | 0.358 | **0.073** | — |
| Tokens por decisión | 615 | 2595 | 3069 | — |

El 0.927 frente al guardia es la política pedida ("solo combatir lo que ataca o
está cerca"): el guardia sigue apuntando a enemigos despiertos a 900 unidades y
`v3` prefiere la ruta. Medido contra el plan del propio código, el acuerdo de
apuntado es 0.987 con cero giros en dirección contraria.

**Verificación en vivo** (E1M1, 600 ticks, 10 Hz, 100 decisiones, misma semilla):

| | `v2` | `v3` |
|---|---|---|
| Decisiones moviendo | 47/100 | **86/100** |
| Racha máxima quieto | **30** | **5** |
| Disparos | 5 | **11** |
| Kills / sectores / objetos | 2 / 9 / 3 | **3 / 15 / 6** |
| Daño recibido | 0 | 12 |
| Prioridades usadas | — | advance 46 · fight 50 · dodge 4 |
| Costo de la corrida | $0.0107 | $0.0133 |

**Corrida larga de 30 s** (`--ticks 1800`): `v2` sobrevive los 30 s sin daño con
2 kills y 9 sectores (no se mueve del arranque); `v3` hace **5 kills, 21
sectores y 8 objetos** y muere a los 19.2 s tras 106 de daño. Es el precio
medido de dejar de ser pasivo: `v3` pelea con pistola en campo abierto en vez de
quedarse quieto. `strategy.RETREAT_HEALTH` es el dial de cautela; subirlo de 40 a
60 no cambió la trayectoria medida porque a esa altura el bot ya está esquivando
proyectiles, no intercambiando disparos.

**Costo.** `v3` ronda 3.1k tokens por decisión (~$0.00013, 5x `v1`); 10 minutos a
10 Hz cuestan ~$0.78. Aceptado explícitamente por el usuario a cambio de que el
personaje deje de quedarse quieto.

## 12. Eurística del mapa (`v3w`) y auditoría en MongoDB — ejecutado

Se ejecutó [`DOOM_JEV_HEURISTICS_PLAN.md`](DOOM_JEV_HEURISTICS_PLAN.md): la capa
que el motor no puede conocer (`map/sense.py` + `map/heuristics.py`) viaja ahora
dentro de cada petición como `state.world_model`, y **cada petición y cada
respuesta quedan guardadas en MongoDB**.

**Qué se envió.** `jev_duum/world_model.py` traduce el playbook a un bloque JSON:
sala actual y piso, `hazards` (nukage, daño por tick, celdas adyacentes,
teleporter, escaleras), `route` por el grafo de salas hasta EXIT, `sector_risk`
(16 sectores: peor y mejor, con bearings relativos recomendado/evitado),
`hidden_foes` (conteos + top-3 amenazas con bearing relativo, distancia, score,
line of sight y daño esperado) y `hidden_items` (ocultos, secrets, top-3
aspiraciones). Los bearings van relativos al jugador con la convención de
siempre (positivo = izquierda). El bloque se publica como *informativo, no
autoritativo*: el snapshot y el guardia determinista siguen mandando. Fallo en
blando (`None`), y `calibration.src = "svg-approx"` viaja dentro porque el SVG
no es una proyección fiel del WAD (aspecto 1.16 vs 1.79: se ancla en el spawn
medido, `(-416,256) → (140,168)`).

**Medición en vivo** (E1M1, 10 Hz, misma semilla, `--pilot jev-assisted`):

| 600 ticks / 100 decisiones | `v3` | `v3w` |
|---|---|---|
| Intervenciones del guardia | 15 | 15 |
| Kills / objetos / daño / sectores | 3 / 6 / 12 / 15 | 3 / 6 / 12 / 15 |
| Tokens por decisión (~) | 3.3k | 3.9k |
| Costo de la corrida | $0.0133 | $0.0175 |

El criterio de la Fase 2 (intervenciones del guardia ≤ 0.196 por decisión) se
cumple: **0.15**. Ahora bien, en 100 decisiones consecutivas el bloque
`world_model` **no cambió el argmax**: la política ya resuelve la táctica en
código y el modelo sigue el plan sin necesitar la eurística. La eurística queda
disponible, auditada y lista como insumo de la Fase 4 (`react`); no se reporta
como mejora de juego porque las medidas no la respaldan. Verificable con
`--no-world-model`, que produce la misma trayectoria.

**Auditoría.** `docker compose up -d` levanta Mongo 7 (`:27017`), la API
Express `jev-log` (`:3000`, colección única `jevlog.jev_calls`) y Mongo Express
(`:8081`, `admin`/`admin123`). `jev_duum/jev_log.py` guarda un documento por
llamada con `request.state` y `request.questions` **completos** (incluido
`world_model` y `strategy`) más `response.raw`, tokens, costo, latencia, modelo
resuelto y metadata. Es fire-and-forget en un hilo daemon: nunca bloquea ni
rompe una decisión, cuenta los fallos en `logger.stats["dropped"]`,
`JEV_NO_LOG=1` lo apaga y `JEV_LOG_URL` lo redirige. Comprobado: una corrida de
600 ticks deja 100 documentos recuperables por `GET /calls`.
