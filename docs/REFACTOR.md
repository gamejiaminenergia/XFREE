# REFACTOR.md — MVC + SOLID en `jev_duum`

Registro del refactor estructural del paquete `jev_duum`. El objetivo era
**cero cambio de comportamiento**: los tests, los hashes de contrato y el árbol
de widgets debían quedar idénticos. La estructura cambia; lo que viaja a Jev y
lo que se dibuja, no.

## Por qué

`panel.py` tenía 1842 líneas mezclando cinco responsabilidades (constantes de
layout, helpers de formato, widgets primitivos, seis zonas de pantalla y el bucle
de juego). `snapshot.py` (1289) y `prompts.py` (839) tenían el mismo problema.
El código era inmanejable para escalar.

## Mapeo MVC

| Capa | Módulos |
|---|---|
| **Model** | `snapshot/`, `prompts/`, `controller.py`, `strategy.py`, `hunt.py`, `adversary.py`, `world_model.py`, `world_readout.py` |
| **View** | `panel/`, `telemetry/`, `overlays/`, `theme.py` |
| **Presenter** | `panel/session.py` (`SessionModel`: agrega decisiones en series de display; sin Tk) |
| **Controller** | `panel/loop.py` (`run_jev_window`), `worker.py` |

## Regla de compatibilidad

Cada módulo grande se convirtió en un **paquete con el mismo nombre punteado**
cuyo `__init__.py` es la fachada que re-exporta la superficie pública. Así
`from jev_duum.panel import Dashboard` sigue funcionando sin tocar `cli.py`,
`tools/preview_panel.py` ni los tests. `tests/test_jev_api_surface.py` lo
verifica nombre por nombre.

## Resultado

| Antes | Líneas | Ahora | Mayor módulo |
|---|---:|---|---:|
| `panel.py` | 1842 | `panel/` (16 archivos) | 348 |
| `snapshot.py` | 1289 | `snapshot/` (8 archivos) | 327 |
| `prompts.py` | 839 | `prompts/` (10 archivos) | 306 |
| `prompt_eval.py` | 492 | `prompt_eval/` (4 archivos) | 258 |
| `telemetry.py` | 420 | `telemetry/` (6 archivos) | 120 |
| `overlays.py` | 382 | `overlays/` (3 archivos) | 339 |

Ningún módulo del paquete supera las ~400 líneas. Los únicos por encima son
`_map/sense.py` y `_map/heuristics.py` (vendidos, excluidos de lint), y quedan
`strategy.py` (396) y `controller.py` (353) como los dos módulos planos más
grandes: no estaban en el alcance del plan y se pueden partir con la misma
técnica si vuelven a molestar.

### Estructura

```
jev_duum/
├── theme.py                     única paleta (pantalla + unifilar)
├── snapshot/    models · geometry · entities · navigation · mesh · routes · builder
├── prompts/     conventions · v1 · v2 · v3 · v3w · v4 · questions · state · codec
├── panel/       layout · format · delta · render · widgets · session · frame
│                zones/{banner,game,decision,link,events} · dashboard · loop
├── telemetry/   canvas · sparks · bars · series · policy
├── overlays/    minimap · stale
└── prompt_eval/ corpus · metrics · evaluate
```

`panel/frame.py` es el contrato de un refresco (`HmiFrame`) y su `WorkerLike`
(`Protocol`): hace de `ports` sin un módulo aparte para una sola forma.

### SOLID, en concreto

- **SRP** — un módulo, un motivo de cambio: `format.py` sólo formatea, `session.py`
  sólo agrega series, cada zona sólo construye y refresca su región.
- **OCP** — una zona nueva es un módulo nuevo en `zones/` más su base en
  `Dashboard`; un instrumento nuevo es un módulo en `telemetry/`; una versión de
  prompt nueva es un archivo en `prompts/` registrado en `questions.py`. La
  telemetría se añade sin tocar el bucle.
- **LSP** — las secciones de `snapshot/` y `panel/` comparten forma (`build`/
  `update` sobre el objeto anfitrión) y ninguna rompe el contrato base.
- **ISP** — `Dashboard.update(...)` construye un `HmiFrame`
  (`@dataclass(frozen=True, slots=True)`) y el trabajo real va por
  `render(view)`: la vista recibe un valor, no el controlador ni el worker
  entero.
- **DIP** — `panel/frame.py` declara `WorkerLike` como `Protocol`; la vista
  depende de la forma, no de la clase. Los tests ya usaban `SimpleNamespace`.

## Desviaciones conscientes del plan

1. **Las fases 2-6 son un solo commit.** `panel.py` y `panel/` no pueden
   coexistir en el mismo directorio, así que la conversión a paquete es
   precondición de mover las zonas.
2. **Las zonas se combinan en `Dashboard`**, no se componen con re-export.
   `test_jev_hmi.py` mide la geometría de 45 widgets con nombre sobre un único
   objeto; mantenerlos ahí es lo que hace el invariante comprobable de una vez, y
   permite mover el código verbatim.
3. **`Dashboard.update(**kwargs)` conserva su firma** (construye el `HmiFrame`);
   así el único cambio de test es el destino del parche de `read_world` en
   `test_jev_hmi.py` (un seam de test, no comportamiento).
4. **`snapshot/navigation.py` se partió además en `mesh.py` + `routes.py`**
   porque quedaba en 649 líneas, por encima del objetivo de ~350.

## Verificación

- `ruff check jev_duum tests tools` — limpio.
- `pytest -q` — **219 passed, 5 skipped** (los 151 originales, los 28 de
  contrato y superficie del refactor, y los 40 que añadieron el núcleo
  headless, la política de tick, la TUI y el servicio).
- **Contrato de Jev congelado**: `tests/test_jev_prompt_contract.py` (hash de
  `build_questions` y `build_state` por versión) y
  `tests/test_jev_snapshot_contract.py` (`state_hash` + round-trip). Idénticos
  antes y después.
- **Equivalencia determinista del panel**: `tools/dump_panel_tree.py` vuelca
  `ruta de widget -> (clase, texto, nº de items de canvas)` para los cinco
  estados. `panel.py` (fase 1) y el paquete `panel/` dan **byte-idéntico**
  (80 056 bytes).

```bash
cd jev-duum
JEV_DUUM_PATH=/home/alde/Escritorio/duum-87f4827 uv run --no-sync python -m pytest -q
uv run --no-sync ruff check jev_duum tests tools
JEV_NO_LOG=1 uv run --no-sync python tools/dump_panel_tree.py \
  --duum-path /home/alde/Escritorio/duum-87f4827 --out /tmp/panel.json
```

Las capturas de `tools/preview_panel.py` **no** son un gate fiable: los KPI
imprimen `decision_ms`, que es reloj real, así que dos corridas difieren
legítimamente en unos píxeles. Úsense para revisar, no para comparar.

## Progreso

| Fase | Estado |
|---|---|
| 0 — red de seguridad (contratos + baseline) | hecho |
| 1 — paleta única en `theme.py` | hecho |
| 2-6 — `panel/` | hecho |
| 7 — `snapshot/` | hecho |
| 7b — `snapshot/` en navigation + mesh + routes | hecho |
| 8 — `prompts/` | hecho |
| 9 — `telemetry/`, `overlays/`, `prompt_eval/` | hecho |
| 10 — documentación | hecho |

## Cómo revertir

Cada fase es un commit aislado (8 commits, más el de fase 7b). `git revert <sha>`
de la fase a deshacer. No hay estado persistente ni migraciones.

## Arreglo posterior: el diagrama podía quedarse proyectado a un tamaño viejo

Síntoma observado una vez jugando con Jev real: el resto del panel seguía
refrescándose pero el diagrama se quedaba quieto.

El bucle no puede ser la causa: `panel.update` no está dentro de un `try` y el
`after(1, frame)` va después, así que una excepción habría congelado también el
juego. Lo que quedaba atrás era la **proyección del minimapa**: `MiniMap.fit`
solo se ejecuta cuando Tk reporta un tamaño distinto, y reproyecta releyendo
`winfo_width()`. Si un `<Configure>` llega mientras Tk todavía reporta la
geometría vieja, el mapa queda dibujado para una caja que ya no tiene y nada lo
redibuja hasta el siguiente redimensionado.

Arreglo: `MiniMap.render` re-sincroniza la proyección con el tamaño real del
canvas en cada dibujo. A igual tamaño, igual proyección, así que el estado
estacionario no cambia (verificado: 240 ticks de dinámica idénticos y árbol de
widgets byte-idéntico); solo se autocorrige el caso malo. Lo encierra
`tests/test_jev_overlays.py::test_every_render_resyncs_the_projection_with_the_canvas`,
que falla sin el arreglo.

No es una reproducción: el fallo original no se pudo reproducir, así que el
arreglo ataca el único mecanismo que encaja, no un caso confirmado.

