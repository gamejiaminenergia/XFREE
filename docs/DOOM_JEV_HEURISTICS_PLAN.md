# Plan: entregar la eurística de `sense.py` y `heuristics.py` al modelo Jev

Fecha: 2026-10-11 · Estado: **ejecutado (fases 1–3)** · Inteligible con
[`JEV_DUUM_PLAN.md`](JEV_DUUM_PLAN.md) y
[`../jev-duum/docs/JEV_INTEGRATION.md`](../jev-duum/docs/JEV_INTEGRATION.md)

## 0. Resultado de la ejecución (verificado)

| Pieza | Dónde quedó | Evidencia |
|---|---|---|
| Adaptador `world_model` | `jev_duum/world_model.py` + `jev_duum/_map/` (copia vendorizada de `map/` con imports relativos) | `build_world_model` sobre snapshots reales: spawn → `position_px [140.0, 168.0]`, `room START`, `route [START, NUKAGE YARD, ARENA, EXIT]`, 17 foes (1 en vista), top-3 amenazas y aspiraciones, `calibration.src = svg-approx`; falla en blando (`None`) ante cualquier error |
| Estado `v3w` | `prompts.py` (`build_state(..., world_model=...)`) | `state.world_model` viaja en la petición; las tres preguntas siguen siendo `choice` con las mismas etiquetas |
| Controlador | `controller.py` (`_world_model`, `world_model_used`) + `cli.py` (`--prompt-version v3w`, `--no-world-model`) | default = `v3w`; `v2`/`v3` quedan reproducibles byte a byte |
| Auditoría en Mongo | `jev_duum/jev_log.py` + `jev-log/server.js` + `docker-compose.yml` | 100 documentos por corrida de 600 ticks en `jevlog.jev_calls`, cada uno con `request.state.world_model` y `response.raw` completos |
| Tests | `tests/test_jev_world_model.py`, `tests/test_jev_log.py`, más los de `prompts`/`controller` | `122 passed, 4 skipped`; `ruff` limpio |

Medición en vivo (E1M1, 10 Hz, misma semilla, `jev-assisted`):

| | `v3` | `v3w` |
|---|---|---|
| 600 ticks · intervenciones del guardia | 15 | 15 |
| kills / items / daño / sectores | 3 / 6 / 12 / 15 | 3 / 6 / 12 / 15 |
| tokens por decisión (~) | 3.3k | 3.9k |
| costo de 100 decisiones | $0.0133 | $0.0175 |

Lectura honesta: el bloque `world_model` **no cambió el argmax** en 100
decisiones consecutivas. El criterio de éxito de la Fase 2 (intervenciones del
guardia ≤ 0.196 por decisión) sí se cumple —0.15—, pero lo cumple `v3`. La
eurística viaja, queda auditada y es el insumo que la Fase 4 (`react`) necesita;
con la política actual, que ya resuelve táctica en código, el modelo no llega a
usarla. No es un defecto del adaptador: es el resultado de que la estrategia
determinista domine la decisión.

## 1. Problema

La integración actual (`jev-duum`) manda a Jev un estado estructurado `v2`
compuesto **solo** de lo que el snapshot del motor Duum puede observar: enemigos
visibles, projectiles, pickups a la vista, clearance de movimiento y un waypoint
de ruta. Ese estado es *táctico* y *miope*.

Los scripts `map/sense.py` y `map/heuristics.py` ya resuelven la capa que Duum
no puede ni conocer por diseño — la "eurística" del juego:

| Lo que el agente NO sabe hoy | Quién lo resuelve | Salida JSON |
|---|---|---|
| 17 enemigos con posiciones fijas del nivel, amenaza fuera de vista | `heuristics.analyze_foes` | `foe_analysis` |
| Riesgo sectorial 360° (16 sectores ponderados por distancia) | `heuristics.sector_risk` | `sector_risk` |
| Piso tóxico (nukage, 8 dmg/tick) bajo pies y celdas adyacentes | `heuristics.terrain_danger` | `terrain_danger` |
| 22 ítems ocultos + 2 secrets del nivel | `heuristics.hidden_information` | `hidden_information` |
| Gradiente de aspiración contextual (salud baja duplica medikits) | `heuristics.aspirations` | `aspirations` |
| Ruta fiable por grafo de salas hasta la salida | `heuristics.room_route` | `room_route` |
| Localización exacta en la sala (celda, `${nearest_room}`) | `sense.locate` | `where` |
| Raycast perimetral de 32 direcciones | `sense.raycast_fan` | `walls` |

Jev (TypeSafe System One) es un juez probabilístico: **no hace aritmética ni
conoce el WAD** (los tokens del archivo de nivel no viajan, viajan campos
pre-cálculados). Precisamente por eso, entregarle estos cálculos resueltos en
campos nombrados, como ya hace la petición `v2`, es coherente con la filosofía
del sistema: el código calcula, el modelo juzga.

Este plan define el camino para integrar esa capa sin romper el guardia
determinista, la política argmax ni los esquemas ya congelados.

## 2. Principios

1. **El agente jamás calcula**: se le dan bearings numéricos, distancias y
   booleanos pre-computados; nunca fórmulas ni celdas crudas.
2. **Complemento, no reemplazo**: `v2` sigue siendo el estado canónico; la capa
   eurística viaja como un campo adicional `world_model`.
3. **Snapshot inmutable**: la instancia `DuumSnapshot` de Duum se deja intacta;
   la eurística vive en un adaptador aparte con sus propias coordenadas SVG
   (mapa clásico E1M1 en `map/doom_map.svg`).
4. **Fail-soft**: si el adaptador no puede invocar a `heuristics.py` (por path
   relativo o módulo faltante), el campo `world_model` se envía `null` y el
   prompt lo menciona; Jev juzga solo con `v2` tal como hoy.
5. **Costo acotado**: presupuesto objetivo `≤ 4x` la petición `v1` (2.5k tokens
   en `v2`). Un bloque `world_model` resumido debe sumar **≤ 1.2k tokens
   adicionales**, llevando la decisión a ~3.7k tokens (~$0.00016 por decisión a
   $0.042/Mtok).

## 3. Fuentes (`sense.py` y `heuristics.py`) — Qué ya hacen

Ambos viven en `map/`, son stdlib puro, sin dependencias:

- `sense.py` construye una **rejilla de ocupación 50×37** (celdas de 20 px)
  rasterizando los muros del SVG; expone `locate(x, y)`,
  `survey(x, y, heading_deg, fov_deg, radius_px)`, raycast DDA (`cast_ray` /
  `raycast_fan`), catálogos de salas/ítems/foes/pozos.
- `heuristics.py` importa `sense` y compone `compute_playbook(x, y, heading,
  health, armor)` → un dict con `location`, `micro_perception`, `foe_analysis`,
  `sector_risk`, `terrain_danger`, `aspirations`, `hidden_information`,
  `room_route` y `route_to_exit` (BFS por celda, con la salida conocida:
  *bolsillo EXIT sellado en la rasterización* — la ruta fiable es `room_route`).

El contrato de invocación por tick es determinista:

```python
from sense import survey
from heuristics import compute_playbook

playbook = compute_playbook(x, y, heading_deg, health, armor)
# → dict listo para json.dumps, ya serializable, sin estado vivo
```

Cada llamada es O(17 foes + 23 items × LOS-march + BFS ≤ 1850 celdas): < 5 ms
en hardware de escritorio, despreciable frente a la latencia de red de ~0.3 s
por decisión.

## 4. Contrato de integración: el campo `world_model`

Se extiende la petición `v2` con una clave nueva. Ejemplo del bloque nuevo
(derivado del playbook real medido en ARENA, salud 30):

```json
{
  "world_model": {
    "map": "E1M1",
    "position_px": [480.0, 430.0],
    "cell": [24, 21],
    "room": "ARENA",
    "room_kind": "normal",
    "nearest": { "room": "ARENA", "distance_px": 0.0 },
    "floor": "floor",
    "hazards": {
      "standing_on": "floor",
      "nukage": false,
      "nukage_damage_per_tick": 0,
      "adjacent": [{ "offset": [0, 1], "kind": "wall" }],
      "on_teleporter": false,
      "on_stairs": false
    },
    "route": {
      "rooms": ["ARENA", "EXIT"],
      "doors": ["pasillo sur"],
      "steps_remaining": 1,
      "first_step": "east"
    },
    "sector_risk": {
      "worst_sector": 8,
      "worst_risk": 0.312,
      "safest_sector": 0,
      "recommended_heading_deg": 0.0,
      "avoid_heading_deg": 180.0
    },
    "hidden_foes": {
      "total": 17,
      "in_sight": 1,
      "hidden": 16,
      "top_threats": [
        { "bearing_deg": 345.9, "distance_px": 205.2, "threat_score": 0.9,
          "line_of_sight": false, "expected_damage_per_hit": 28 },
        { "bearing_deg": 270.1, "distance_px": 25.0, "threat_score": 0.423,
          "line_of_sight": true, "expected_damage_per_hit": 12.7 }
      ]
    },
    "hidden_items": {
      "count": 22,
      "secrets_remaining": 2,
      "top_aspirations": [
        { "kind": "medikit", "bearing_deg": 10.5, "distance_px": 82.4,
          "aspiration_score": 1.204 },
        { "kind": "rocket", "bearing_deg": 92.1, "distance_px": 129.3,
          "aspiration_score": 0.547 }
      ]
    }
  }
}
```

**Reglas de traducción** — cómo se derivan los campos JSON:

- `bearing_deg` nuevo: se recalcula **relativo al player.heading** (drift
  0 = enfrente, + = izquierda match CONVENTIONS de `prompts.py`);
  el playbook de `sense.py`/`heuristics.py` da bearing absoluto (0 = este), y
  el adaptador debe convertirlo: `bearing_relative = (abs - heading) % 360`.
- `top_threats / top_aspirations`: máx. **3** entradas cada una, ya truncadas
  para respetar el presupuesto de tokens.
- `route_to_exit` (BFS por celda) **no viaja** — se sabe que se queda ciega en
  el bolsillo de la EXIT; sólo `room_route` es fiable. Esto se documenta, no
  se arregla, para no enviarle información errónea al modelo.
- Todo número queda **redondeado a 1 decimal** como el resto del estado v2.

## 5. Preguntas nuevas para Jev (opcional, fase 2)

Con las aspiraciones del `world_model` disponibles, `build_questions` v2
puede agregar una pregunta opcional de alto nivel:

```json
"react": {
  "type": "choice",
  "instructions": { "role": "...", "task": "Decide la reacción de alto nivel frente a lo oculto", "rules": ["..."] },
  "criteria": {
    "engage_hidden": { "what": "Ir por un foe oculto amenazante", "use_when": "hidden_foes.top_threats[0].threat_score > 0.5 y salud > 50", "not_for": "salud crítica" },
    "seek_health": { "what": "Ir por el medikit más aspirante", "use_when": "health <= 35 y aspirations.recommended_target.kind == medikit", "not_for": "salud alta" },
    "continue_route": { "what": "Seguir la ruta de salas a la EXIT", "use_when": "riesgo global bajo y no hay aspiración mejor", "not_for": "enemigos visibles en rango" },
    "avoid_nukage": { "what": "Retirarse del sector tóxico o de riesgo", "use_when": "terrain_danger.standing_on == nukage o sector_risk.worst_risk > 0.5", "not_for": "riesgo bajo" },
    "hold": { "what": "Nada de lo anterior", "use_when": "siempre decidible", "not_for": "—" }
  }
}
```

Su argmax se traduce en una **estrategia** (el tercer parámetro de
`_structured_state(snapshot, strategy)`), así que no chocan con las tres
preguntas de control existentes: la nueva información estratégica condiciona el
estado que Jev ya recibe, no le cambia la firma.

## 6. Módulos a crear / modificar

| Módulo | Operación | Qué hace |
|---|---|---|
| `jev-duum/jev_duum/world_model.py` | **nuevo** | Adaptador: dada la posición px/heading/health del snapshot, invoca `compute_playbook`, traduce a bearing relativo, recorta top-3, devuelve el dict o `None` |
| `jev-duum/jev_duum/prompts.py` | modificar | `build_state(..., world_model=None)` acepta el dict y lo inserta como campo `world_model`; si es `None` lo omite (fail-soft); no modifica `v1` |
| `jev-duum/jev_duum/controller.py` | modificar | `combined_state` calcula `world_model` (con try/except → `None`) y lo pasa a `build_state`; `DecisionResult` expone `world_model_used: bool` para auditoría |
| `map/sense.py` y `map/heuristics.py` | sin cambios | Son la fuente de verdad; se copian a `jev-duum/jev_duum/_map/` como módulos internos (o se leen por ruta relativa configurable en `_map/__init__.py`) |
| `jev-duum/tests/test_world_model.py` | **nuevo** | Unit: bearing relativo correcto conjugado con CONVENTIONS; truncado a top-3; fail-soft si falta el mapa; JSON-serializable |
| `jev-duum/tests/test_jev_prompts.py` | ampliar | `build_state(v2, world_model=...)` produce el campo; `v1` lo ignora; round-trips y congelado intactos |

## 7. Fases

### Fase 1 — Adaptador de sólo lectura (sin red)
1. Copiar `map/sense.py` + `map/heuristics.py` a `jev-duum/jev_duum/_map/`
   (vaciar `__pycache__`).
2. `world_model.py` implementa `build_world_model(snapshot) -> dict | None`:
   - Fix de escalado: los px del SVG (1000×750) y las unidades Duum no
     coinciden. Se fija `PX_PER_DUUM_UNIT` midiendo el punto de spawn del WAD
     contra la flecha blanca del SVG (140, 168) y se documenta el factor.
   - Convierte `bearing_deg` absoluto → relativo al heading del jugador.
   - `try/except Exception → None` (fail-soft), log a observación.
3. Test unitario con snapshot sintético (posiciones fijas), sin red.

### Fase 2 — Estado `v2+w` (petición con world_model, versión congelada)
4. `PROMPT_VERSIONS` agrega `v2w` (con `world_model` fijo, así se reproduce
   con `--prompt-version v2w`); `v2` queda intoc Salud para comparar A/B.
5. `controller.combined_state` recibe `world_model` y lo anexa.
6. `jev-duum-prompt-eval --versions v2,v2w --corpus ...` re-consulta ambos sobre
   los mismos 397 snapshots del corpus y reporta la tabla ya existente
   (intervenciones del guardia, acuerdo, confianza, tokens, costo).
   **Criterio de éxito:** intervenciones del guardia ≤ 0.196 por decisión
   (el récord `v2`), tokens ≤ 4x del total `v1` y latencia compatible
   (p95 +≤50 ms).

### Fase 3 — Piloto con eurística + evaluación completa
7. Run real de 600 ticks (100 decisiones) con `--pilot jev-assisted
   --prompt-version v2w --record-snapshots`: medir kills, salud final,
   sectors, intervenciones, contra la corrida `v2` histórica (100 decisiones,
   14 intervenciones, 2 kills, $0.0107).
8. `jev-duum-eval` con la matriz completa a 180 ticks para costo total y
   bookkeeping.

### Fase 4 — (opcional) pregunta `react`
9. Si la evaluación muestra que el guardia sigue corrigiendo >0.3 por decisión
   en desataques con foes ocultos, agregar la pregunta `react` de la §5,
   re-medir el corpus con y sin ella, y congelar `v2w` final con la pregunta
   incluida o `v2w2`.

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Auto-correlación: el modelo recibe a la vez el guardia determinista y el `world_model`, y podría confundir su autoridad | Publica el bloque `world_model` como "informativo, no autoritativo" en `instructions.role`; la palabra final del guardia queda intacta |
| Coordenadas Duum ≠ px SVG: el spawn del WAD no cae en la sala START del SVG | La Fase 1 calibra el `PX_PER_DUUM_UNIT` midiendo el spawn real; el test unitario fija el factor con tolerancia ±5% |
| El costo de tokens rebase el presupuesto | La Fase 2 se mide primero offline sobre el corpus A/B (sin coste real); se decide el recorte antes de correr en vivo |
| La ruta de salas (room_route) desajusta con la navegación real del motor Duum (que usa SEGS/SSECTORS del WAD) | `world_model.route` se etiqueta `"src: svg-approx"`; la navegación real del agente sigue siendo la capa del snapshot v2, no esta |
| `heuristics.py` importa `sense` por módulo de nivel superior (no empaque) | Al copiar ambos a `_map/` se ajusta al import relativo (`from . import sense`) |
| Sobreajuste del corpus de 397 snapshots a las salas que ese corpus cubre | Re-grabar un corpus ampliado (`--record-snapshots`, piloto `random` más largo) antes de medir `v2w` |

## 9. Esquema de auditoría

`DecisionResult.world_model_used` y la copia del bloque `world_model` en el
registro (`--record-snapshots`, esquema `jev-duum-episode-v2`) permiten:
- Repetir un run sin red y verificar qué bloque vía modelo.
- Comparar decisiones `with/without` sobre el mismo tick (A/B cero coste).

## 10. Criterios de aceptación globales

1. `pytest` sigue en verde (67 passed / 1 skipped hoy) más los tests nuevos de
   `world_model` y de `prompts` con `v2w`.
2. Cotejo en el corpus: `prompt-eval` → intervenciones ≤ 0.196 por decisión y
   tokens ≤ 4x `v1` (documentar el número real si excede el 4x).
3. Run en vivo `v2w` vs `v2` con misma semilla: igual o mejor en salud final
   y kills, menos intervenciones, costo ≤ 2x el run `v2`.
4. No se modifica `duum` (pin `87f4827f…`), ni el guardia, ni los esquemas
   existentes; `v1`/`v2` reproducibles byte a byte.
5. `docs/JEV_DUUM_PLAN.md` se actualiza con la tabla `v2w` final tras ejecutar
   la Fase 2, marcando esa fase como "ejecutada".
