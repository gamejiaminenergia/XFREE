# REFACTOR.md — MVC + SOLID en `jev_duum`

Registro del refactor estructural del paquete `jev_duum` (ver el plan original en
`/home/alde/.opencode/plan/refactor-mvc-solid-jev-duum.md`). El objetivo es **cero
cambio de comportamiento**: los tests, los hashes de contrato y las capturas deben
quedar idénticos. La estructura cambia; lo que viaja a Jev y lo que se dibuja, no.

## Por qué

`panel.py` tenía 1842 líneas mezclando cinco responsabilidades (constantes de layout,
helpers de formato, widgets primitivos, seis zonas de pantalla y el bucle de juego).
`snapshot.py` (1289) y `prompts.py` (839) tenían el mismo problema. Eso hacía el
código inmanejable para escalar.

## Mapeo MVC

| Capa | Módulos |
|---|---|
| **Model** | `snapshot/`, `prompts/`, `controller.py`, `strategy.py`, `hunt.py`, `adversary.py`, `world_model.py`, `world_readout.py` |
| **View** | `panel/`, `telemetry/`, `overlays/`, `theme.py` |
| **Presenter** | `panel/session.py` (agrega decisiones en series de display; sin Tk) |
| **Controller** | `panel/loop.py` (`run_jev_window` + `FrameDriver`), `worker.py` |

## Regla de compatibilidad

Cada módulo grande se convirtió en un **paquete con el mismo nombre punteado** cuyo
`__init__.py` es la fachada que re-exporta la superficie pública. Así
`from jev_duum.panel import Dashboard` sigue funcionando sin tocar `cli.py`,
`tools/preview_panel.py` ni los tests. `tests/test_jev_api_surface.py` lo verifica.

## Baseline y red de seguridad (Fase 0)

Medido antes de tocar el paquete, con el motor pinneado
(`JEV_DUUM_PATH=/home/alde/Escritorio/duum-87f4827`, commit `87f4827`):

- `ruff check jev_duum tests` — limpio.
- `pytest -q` — **151 passed, 5 skipped**.
- `preview_panel.py` — 5 capturas, byte-idénticas entre corridas.

### Tamaños (antes)

| Archivo | Líneas |
|---|---:|
| `panel.py` | 1842 |
| `snapshot.py` | 1289 |
| `prompts.py` | 839 |
| `prompt_eval.py` | 492 |
| `telemetry.py` | 420 |
| `overlays.py` | 382 |

### Hashes de contrato (congelados)

`DuumSnapshot.state_hash()` sobre el snapshot sintético de `tests/conftest.py`:

```
06c61bb6b40a6f8b28bb772dedeb09d41d787f5300df7387434ef66229311bcf
```

`build_state(...)` por versión (SHA-256 del JSON ordenado):

| versión | state |
|---|---|
| v1 | `ade65e3956d62469a13f5f73ea963c821a5cb03d9f8ff8ea76172c10e6a0dc14` |
| v2 | `6fc7b47a49f358f5e9d59d4b7cbea8c9bb9388671863edfb67f99601e9fe1a9e` |
| v3 | `b42177f94ada0c36e357b1195be551cfe7f24236209d585e8d3c05664449f687` |
| v3w | `73c0b02ecd7463910d3005ed36dc661dd5358f0106558f9154463041e8e1ed0e` |
| v4 | `62e5bc333621de3c1f889298f8c5827ef0410dc132b25cbf0e269edfff15a5f1` |

## Progreso

| Fase | Estado |
|---|---|
| 0 — red de seguridad | hecho |
| 1 — paleta única | hecho |
| 2 — layout / format / delta | hecho |
| 3 — widgets | hecho |
| 4 — session / zones / dashboard | hecho |
| 5 — loop + FrameDriver | hecho |
| 6 — `panel/` como paquete | hecho |
| 7 — `snapshot/` como paquete | hecho |
| 8 — `prompts/` como paquete | hecho |
| 9 — telemetry / overlays / prompt_eval | hecho |
| 10 — documentación | hecho |

## Verificación

```bash
cd jev-duum
JEV_DUUM_PATH=/home/alde/Escritorio/duum-87f4827 uv run --no-sync python -m pytest -q
uv run --no-sync ruff check jev_duum tests
JEV_NO_LOG=1 uv run --no-sync python tools/preview_panel.py \
  --duum-path /home/alde/Escritorio/duum-87f4827 --out /tmp/opencode/ui-check
```

Las capturas de `/tmp/opencode/ui-check` deben compararse con el baseline
`/tmp/opencode/ui-baseline` (byte-idénticas).

## Cómo revertir

Cada fase es un commit aislado. `git revert <sha>` de la fase a deshacer. No hay
estado persistente ni migraciones.
