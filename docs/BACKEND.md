# BACKEND.md — el backend independiente

El piloto quedó partido en dos: un **núcleo sin interfaz** y varios **frontends**
encima. El panel Tk y el vídeo con `x11grab` no cambiaron; esto es lo que se
añadió.

```
                       núcleo (sin Tk, sin HTTP)
   session/policy.py   la política de tick, como funciones puras y testeadas
   session/core.py     Session: motor + SnapshotBuilder + DecisionWorker
                       publica un Frame por tick (estado + rgb)
                            │
        ┌───────────────────┼──────────────────────┬─────────────────────┐
   TkVideoHost        (panel Tk, intacto)     panel/ --tui          jev-service
   panel/loop.py       + scripts/record.sh    (curses, SSH)         (FastAPI)
```

## El núcleo

`jev_duum/session/` no importa Tk, ni motor, ni red. `Session` es la **única**
dueña del motor: nadie más lo avanza.

- **`policy.py`** — las decisiones que antes vivían dentro de `run_jev_window`:
  cuándo preguntar al modelo, si un resultado sigue sirviendo (frescura y cambio
  de nivel), cuándo termina el intermedio, cada cuánto se repinta, y que `use` es
  de un solo uso. Son funciones puras; `tests/test_jev_policy_equivalence.py`
  comprueba *exhaustivamente* que son las mismas condiciones de antes.
- **`core.py`** — `Session`, con `Frame` como valor (`dataclass` frozen): tick,
  `snapshot`, `decision`, `controls`, `stale`, `error`, stats del worker y `rgb`
  (los píxeles del propio buffer del motor, sin X). `pixels=False` para quien
  solo quiera datos.

El bucle Tk (`panel/loop.py`) y el núcleo **comparten la política**, así que las
dos formas de correr el piloto se pisan el mismo terreno.

## Frontends

| Frontend | Cómo se lanza | Necesita |
|---|---|---|
| Panel Tk (el de siempre) | `./main.sh` / `bash play.sh` | X, Tk |
| TUI en la terminal | `jev-duum --tui --pilot jev-assisted` | nada (curses) |
| Servicio HTTP | `uv run --project jev-service jev-service` | nada (localhost) |
| Navegador | `GET /` del servicio | el servicio arriba |
| Vídeo (escritorio) | `bash scripts/record.sh --launch --window` | X |
| Vídeo (backend) | `bash scripts/record.sh --from-backend` | nada |

### `--tui`

`jev_duum/tui/` dibuja el mismo panel en la propia terminal: rejilla fija, la
paleta de `theme.py` traducida a ANSI y la vista del juego en medios bloques
UTF-8. Es `curses`, de la stdlib: **cero dependencias nuevas**, y funciona por
SSH sin X.

Pide los píxeles al motor **solo cuando los dibuja**: en rejilla estrecha (menos
de 112 columnas, sin vista del juego) apaga `Session.set_pixels`, porque copiar
el buffer RGB cada frame era la mayor parte del coste por paso. Medido: 59
ticks/s en estrecho (99 % del tiempo real) frente a 38 ticks/s en ancho (63 %),
que es lo que cuesta pintar el juego celda a celda.

Teclas: `q` salir, `p` pausa, `+`/`-` ritmo de decisión, `g` vista del juego.

**Y el mismo panel como cliente de este servicio**:

```bash
jev-duum-tui --url http://127.0.0.1:8000
```

`tui/remote.py` lee `/api/state`, pinta desde `/api/frame.raw` y manda
`p`/`+`/`-` a `/api/control`. No usa nada más que `urllib`, así que la sesión
puede correr en una máquina y verse desde otra por SSH. El mapeo
(`frame_from_state`) reconstruye el mismo valor que produce una sesión local, de
modo que `render.py` no distingue una fuente de la otra: por eso el formato de
red lleva los dos contadores (`keys`, `questions`) en vez del `request_state`
crudo, que serían kilobytes en cada sondeo.

### `--fake`: los mismos modos, 0 $

Cualquier modo en vivo admite `--fake`, que responde con un modelo local
determinista (`jev_duum/fake.py`, el único cliente falso del repositorio: lo
usan los tools, el servicio y la TUI). Sin clave, sin red, sin factura — y el
resumen lo dice (`network`, `model_source`, `fake_model`) en vez de inventarse
un coste.

### `jev-service`

Paquete aparte (`jev-service/`) para que `jev-duum` conserve
`dependencies = ["duum"]`. FastAPI + uvicorn viven ahí, como el log de auditoría
vive en `jev-log/`.

```bash
cd jev-service && uv sync
uv run --no-sync jev-service --fake     # modelo local: 0 $, sin clave
```

| Endpoint | Qué da |
|---|---|
| `GET /health` | vida, uptime, tick, secuencia |
| `GET /api/meta` | pilot, modelo, prompt, misión, commit del motor, WAD |
| `GET /api/state` | jugador, episodio, worker, decisión y el `snapshot` semántico completo (`?full=0` lo omite) |
| `GET /api/frame.png` | el frame del motor, en PNG |
| `GET /api/frame.raw` | el mismo frame en RGB crudo, para un cliente que compone sus propias celdas (la TUI) |
| `GET /api/frames.stream` | `multipart/x-mixed-replace` para un `<img>` |
| `WS /ws` | push `{seq, state}` |
| `POST /api/control` | `{"paused": true}`, `{"decision_rate": 8}` |
| `GET /` | el panel en el navegador |

Dos clientes vienen con él: la página del navegador (`GET /`) y
`jev-duum-tui --url`, el mismo panel en la terminal.

Detalles que importan: el motor no lo toca ninguna petición (la `Session` corre
en un hilo y un `Hub` guarda el último valor; un cliente lento pierde frames,
nunca frena la sesión), el PNG se escribe con `zlib` de la stdlib (nada de
Pillow), no hay `response_model` de pydantic por frame, la paleta de la portada
sale de `theme.py`, escucha en `127.0.0.1` y `--control-token` protege el
control. La clave de TypeSafe nunca sale del servidor.

Y una regla de robustez: si un frame no se puede serializar, `Hub.publish` lo
**cuenta y lo descarta** en vez de lanzar — el hilo del motor es único y un
fallo de serialización no puede llevarse la partida por delante. `/health`
publica ese contador (`dropped`), así que no pasa inadvertido.

### Vídeo desde el backend

El motor ya entrega su frame como RGB crudo, así que hay vídeo exacto sin
capturar pantalla:

```bash
bash scripts/record.sh --from-backend --fake --seconds 20 --duum-path /path/al/duum-pinneado
```

Frame a frame, a 60 fps, sin escritorio, sin recortes y sin frames perdidos. A
cambio graba **solo la vista del juego**: el panel no está ahí (para eso sigue
`--window`, que captura la ventana Tk).

## Qué no cambió

- El panel Tk, su geometría y su vídeo: mismo `run_jev_window`, mismos píxeles
  (verificado con `tools/dump_panel_tree.py`, byte a byte).
- Todos los modos de terminal: `./main.sh`, `--headless`, `--record`, `--replay`,
  `jev-duum-autopsy`, `jev-duum-eval`, `jev-duum-prompt-eval`, `scripts/record.sh`.
  Lo nuevo es opt-in y `tests/test_jev_cli_surface.py` lo congela.
