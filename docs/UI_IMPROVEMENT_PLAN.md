# Plan de mejora de la interfaz gráfica — solo Tk, sin web

Fecha: 2026-10-11 · Estado: **implementado** · Restricción del usuario: **la sesión
se ejecuta como hoy — ventana Tk + terminal; no se agrega nada web**

## 0. Estado de implementación (2026-10-11)

Las tres fases quedaron aplicadas con Tk puro y sin dependencias nuevas:

| Fase | Qué se implementó | Dónde |
|---|---|---|
| 1 | Columnas con widgets por sección, delta-update por caché, meters con umbral (ámbar/rojo + parpadeo), badges de asistencia | `jev_duum/panel.py` (`DeltaCache`, `Meter`, `BarRow`, `Pill`, `Card`) |
| 2 | Mini-automapa con muros, riesgo sectorial (16 arcos), flecha del agente, objetivo resaltado y HUD de stale/error | `jev_duum/overlays.py` (`MiniMap`, `StaleOverlay`) |
| 3 | Lectura in-process de la heurística para el panel + bitácora pasiva con opt-in explícito | `jev_duum/world_readout.py`, flag `--log-calls` en `jev_duum/cli.py` |

Dos añadidos que el plan no pedía pero el usuario pidió ver: el inspector
derecho ahora es **pestañado** (DECISIÓN · RESPUESTA · PETICIÓN · MUNDO), y la
**petición y la respuesta al modelo** tienen su propio espacio — el `state`
exacto que viaja a Jev (JSON con colores), las preguntas, las tres
distribuciones con el argmax resaltado y las `confidence` como pills. Para eso,
`DecisionResult` guarda `request_state` y `request_questions` (nada nuevo viaja
al modelo; es una copia para mostrar).

Verificación: `uv run --no-sync python -m pytest -q` (131 pasan, 4 skip) y una
sesión real con `run_jev_window` sobre E1M1 (motor Duum renderizando en vivo).

**Pantalla completa y reflow (añadido después del plan).** La ventana arranca
llenando la pantalla y se recompone al cambiar de tamaño (`<Configure>`): las
columnas ajustan su ancho, el canvas de Duum sube al mayor zoom entero que
quepa y el mini-automapa crece manteniendo la proporción del esquemático. F11
alterna pantalla completa y `--windowed` arranca en ventana normal. Los
umbrales de color y el delta-update siguen igual: sólo se redibuja lo que
cambió, así que redimensionar no cuesta fotogramas.

A pantalla completa no hay barra de título, así que el inspector lleva arriba a
la derecha dos botones: `□ F11` (alterna pantalla completa) y `✕ salir` (cierra
por el mismo `app.quit` de Menu → Quit, sin callbacks pendientes).

**Detalle de la petición (añadido después del plan).** La pestaña PETICIÓN se
rehizo para aprovechar el alto disponible: una fila de chips (modelo, prompt,
tokens, tamaño en bytes, nº de claves del `state`, nº de preguntas) y tres
secciones que se reparten el espacio — el `state` completo que viaja a Jev (JSON
con colores y sin wrapping, 5/8 del alto), las preguntas con sus `instructions`
y `criteria` verbatim (3/8) y un índice del `state` con el tipo y tamaño de cada
clave. La pestaña RESPUESTA añade el `JSON crudo de la respuesta` para auditar
lo que devolvió el modelo, no sólo las distribuciones interpretadas.

## 1. Estado actual (auditado, no imaginado)

### 1.1 Ventana de juego — `jev-duum/jev_duum/panel.py` (Tk)

`Dashboard` monta una ventana única con tres columnas:

| Zona | Implementación actual | Limitaciones observadas |
|---|---|---|
| **Izquierda (230px)** | Título + 3 `Meter` (health/armor/ammo con canvas de barra fija 188×10) + bloque `stats` de texto plano (MAP/TIME/WEAPON/ENEMIES/KILLS/ITEMS/DAMAGE/SECTORS) | Las barras no cambian de color según umbral; nada indica peligro; sin hint de qué arma está en recarga |
| **Centro** | Canvas Duum intacto (`window.tkcv`), borde 3px azul `#65d8ff` | Sin overlay del automapa (`map/doom_map.svg` no se usa); sin indicador de heading; no se marca el enemigo que el modelo eligió apuntar |
| **Derecha (470px)** | Un único `tkinter.Text` de 38 líneas con TODA la información en texto monoespaciado: worker stats, probabilidades MOVEMENT/AIM/INTERACTION con barras ASCII (█·), model/confidence, proposed vs applied, latencias, cost, assistance events, STRATEGY y 3 observaciones | Saturación: todo es texto corriendo; buscar "cuánto costó la última decisión" exige leer; sin separación visual entre secciones; sin resaltado de la respuesta argmax |
| **Refresco** | `panel.update(...)` llamado cada 4 ticks, reescribe el `Text` completo con `delete(1.0, end)` cada vez | Parpadeo/flicker del bloque derecho en cada refresco; coste de re-render inútil (el texto no cambió) |

Otros datos del código: `run_jev_window` ya recolecta `latencies[]`, `stale`,
`worker.stats` y expone `on_decision(latest)` como hook — la mejora puede
aprovecharlos sin tocar el loop de 60 Hz.

### 1.2 Lo que ya existe y PUEDE reutilizarse dentro de la terminal

- **Stack Docker auditable**: MongoDB 7 (`:27017`, db `jevlog`), API Express
  (`:3000`, colección única `jev_calls` con request+response por documento).
  La sesión NO dependerá de él; el API queda como **bitácora pasiva**: el loop
  Tk puede POST-ear su decisión (opcional, Fase 3) y el análisis posterior se
  hace con curl/mongosh o scripts Python — nunca con una interfaz web del juego.
- **Datos de percepción ya existentes**: `sense.py` arroja `where` + 32
  raycasts; `heuristics.py` arroja `foe_analysis`, `sector_risk`,
  `aspirations`, `room_route` — el panel Tk puede leerlos para pintar el
  mini-automapa y el riesgo sectorial **en el propio panel**.
- **SVG del mapa**: `map/doom_map.svg` — sus polilíneas están ya derivadas a
  `WALL_SEGMENTS` en Python; se pueden redibujar sobre un `Canvas` Tk.

### 1.3 Conclusión del diagnóstico

La deuda no es de datos (todo ya existe: snapshot, consejos del guardia,
latencias, cost) sino de **configuración visual**: un `Text` plano que lo
vuelca todo contra una jerarquía de widgets. El plan ataca eso con Tk puro,
por fases baratas de mover, empezando por lo de mayor retorno y sin tocar el
motor. **Todo dentro de la ventana que ya se ejecuta.**

## 2. Objetivos medibles

| # | Objetivo | Métrica actual | Meta |
|---|---|---|---|
| O1 | El jugador identifica el estado del agente en <2 s | leer texto plano | semáforos de color + secciones separadas |
| O2 | Eliminar flicker del panel | re-render completo cada 4 ticks | delta-only (widgets por sección, actualización por campo) |
| O3 | Decisiones de Jev visualmente auditables | probabilities + conf en lista | resaltar argmax en barra y colorear guard interventions ≠ 0 |
| O4 | Percepción eurística visible en la ventana | no existe | mini-automapa + riesgo sectorial en el panel (datos de `sense.py`/`heuristics.py`) |
| O5 | No tocar duum ni la lógica del loop | panel.py threads/loop | panel aislado: cambios solo en `Dashboard` y un módulo nuevo |
| O6 | Sin dependencias web nuevas | — | Tk únicamente; si hay logging, es POST pasivo a la API existente |

## 3. Fases

### Fase 1 — Tk: jerarquía y color en el panel derecho (sin librerías nuevas)

1. **Sustituir el `Text` único** por un contenedor con **secciones fijas**:
   - `DecisionFrame` — las 3 preguntas en 3 grupos, cada opción su propia
     línea de barra `Canvas`, **argmax resaltado** en color verde `#8ee8a8`
     y el resto en gris; las `confidence` como pequeñas pill-labels.
   - `ControlFrame` — proposed vs applied en dos líneas de labels con color
     por control (amber si el guardia lo cambió).
   - `MetricsFrame` — latencia p50/p95 de la sesión (ya existe en las
     `latencies` de `run_jev_window`), tokens y cost acumulado.
   - `StrategyFrame` — solo si `strategy` existe; pasos como bullets.
   - `ObservationsFrame` — colapsable (Toggle que pliegue 3 en 1).
2. **Delta-update en vez de re-render**: guardar por widget su último valor
   (`self._cache[key]`) y solo tocar `configure(text=...)` si cambió — mata
   O2 flicker.
3. **Umbral de color en meters** (`health.set` ampliado a `set(value, max,
   text=None, warn_at=None, crit_at=None)`): health <35 rojo neón parpadeo
   (toggle color cada 4 ticks), <70 ámbar, resto verde; ammo <10 crit.
4. **Assistance events**: hoy corren como línea de texto — pasarlos a badges
   de color por `kind` (naranja por intervene).

### Fase 2 — Tk: overlays del centro (mapa y foco de decisión)

5. **Mini-automapa**: un `Canvas` Tk abajo-centro que pinte las polilíneas de
   `WALL_SEGMENTS` (de `sense.py`, importando solo esos datos, sin ejecutar el
   raycast) y **la posición del jugador como flecha rotada por heading**.
   Fuente de datos: `DuumSnapshot` (posición ya la traa) + heading.
6. **Riesgo sectorial en el mini-automapa**: los 16 sectores de
   `heuristics.sector_risk` como sector-arcs coloreados de verde→rojo en la
   posición del jugador; `recommended_heading_deg` dibujado como un triángulo
   delante de la flecha.
7. **Marcado del enemigo elegido**: circundar en verde el enemigo objetivo
   (coincide con `aim` argmax actual); si el guardia interviene, naranja.
   Si el snapshot no expone el id del enemigo apuntado, se marca el más
   cercano en línea de vista (documentado como aproximación).
8. **HUD de stale/error**: barra semitransparente sobre el canvas cuando
   `stale>3` o `model_error` — hoy solo vive como texto en la columna derecha.

### Fase 3 — Tk: lectura pasiva de la eurística + bitácora opcional

9. **`eje runner`**: el panel puede leer los JSON ya generados por
   `sense.py`/`heuristics.py` (por invocación in-process import, no subprocess:
   `from heuristics import compute_playbook`) y volcar los datos útiles en
   una sección nueva `WorldModelFrame` del panel derecho:
   - foes fuera de vista (`foe_analysis.foes_hidden`)
   - toxicidad del piso (`terrain_danger.standing_on`)
   - ruta de salas restante (`room_route.steps_remaining`)
   Esto **no** toca el estado que viaja a Jev (ver plan
   `DOOM_JEV_HEURISTICS_PLAN.md` para la integración al modelo; aquí es
   solo visual).
10. **Bitácora pasiva (opcional, detrás de flag)**: `--log-calls` envía por
    HTTP POST la decisión completa a la API Express ya levantada (`:3000`);
    falla en silencio si el stack no está corriendo. El análisis posterior se
    sigue haciendo en terminal: curl, mongosh o scripts Python.

## 4. Módulos a crear / modificar

| Módulo | Operación | Riesgo |
|---|---|---|
| `jev-duum/jev_duum/panel.py` | modificar: `Dashboard` secciones + delta-update + meters-umbral | bajo (loop intacto) |
| `jev-duum/jev_duum/overlays.py` | **nuevo**: mini-map + sector risk + enemigo objetivo (Fase 2) | medio — requiere confirmar campos de posición/heading/enemy-id del snapshot |
| `jev-duum/jev_duum/world_readout.py` | **nuevo**: adaptador de lectura in-process de `sense.py`/`heuristics.py` para `WorldModelFrame` (Fase 3) | bajo — cero subprocess, cero red |
| `jev-duum/jev_duum/cli.py` | modificar: flag `--log-calls` que activa el POST pasivo (Fase 3, opcional) | menor |
| tests: `test_panel.py` | cubrir el cache de delta-update, el color por umbral y el adaptador de lectura | bajo |

Fases 1–3 es Tk puro + stdlib: pip nada nuevo, sin ninguna dependencia de
renderizado alternativo.

## 5. Verificación propuesta

1. **Fase 1**: correr `uv run --no-sync jev-duum --pilot jev-assisted` 30 s y
   confirmar — (a) no hay flicker capturando dos screenshots consecutivos y
   comparando píxeles de la columna derecha; (b) health parpadea bajo 35.
2. **Fase 2**: mismo run, verificar que la flecha del jugador rota con el
   heading, que los arcos de riesgo sectorial se colorean, y que el overlay
   stale aparece si se simula worker lento.
3. **Fase 3**: con `map/sense.py` y `map/heuristics.py` presentes, confirmar
   que `WorldModelFrame` muestra datos coherentes (foes hidden, standing_on,
   ruta restante); con `--log-calls`, verificar `POST /calls` y el conteo de
   documentos desde mongosh.
4. Todo sin modificar duum, guardia, scheduler, ni los args existentes del CLI
   (solo un flag opcional nuevo).

## 6. Fuera de alcance (explícito)

- **Cero interfaces web para la sesión**: no dashboard `:3001`, ni tiles, ni
  actualización por navegador. El usuario no la pidió y la sesión sigue
  ejecutándose en la ventana Tk actual.
- No reemplazar Tk por Qt/GTK/Electron (el empaque y la portabilidad cambian
  de seriousness).
- No enviar píxeles al modelo: la mejora es de presentación, el estado que
  viaja a Jev queda siendo semántico.
- El único uso de la API del stack Docker es OPCIONAL y pasivo (bitácora
  `--log-calls`), no forma parte de la presentación del juego.
