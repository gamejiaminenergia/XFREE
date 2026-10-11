# video/ — grabaciones de la partida y demos

Índice de los clips. **El medio no se versiona** (`.gitignore`: `mp4`, `mkv`,
`mov`, `webm`, `gif`); este README y los `.gitkeep` sí, para que la estructura
exista en el repo.

## Cómo se graba

```bash
bash scripts/record.sh --launch              # lanza ./main.sh y graba la partida
bash scripts/record.sh --launch --window     # graba solo la ventana del juego
bash scripts/record.sh --tipo demo           # graba lo que ya tengas en pantalla
```

Por defecto graba **60 s** y para sola (`--seconds 0` para que no pare hasta que
tú quieras; `Ctrl-C` también para, y el MP4 se cierra siempre, nunca a medias).

Dos opciones que conviene no confundir:

- **`--window`**: recorta la captura a la ventana del juego. Sin esto se graba
  todo el escritorio; en este equipo son dos monitores de 1920×1080, así que
  cualquier cosa que tengas abierta al lado **sale en el vídeo**. Úsalo siempre
  para material que vaya a ver alguien más.
- **`--windowed`**: abre el juego en una ventana en vez de a pantalla completa.

Otras: `--fps 30`, `--crf 23`, `--scale 2560:720`, `--encoder auto|nvenc|hevc|x264`,
`--nombre <slug>`, `--pilot`, `--prompt`, `--out-dir`.

## Codificación

Con `--encoder auto` (por defecto) se usa **NVENC** si la GPU lo admite y si no
`libx264`. Medido en este equipo (RTX 3050, 3840×1080 @ 30 fps, 6 s):

| Codificador | CPU | RSS máx | Tamaño |
|---|---|---|---|
| `libx264 -preset veryfast -crf 23` | 104 % | 1.2 GB | 316 KB |
| `h264_nvenc -preset p5 -tune hq -cq 23` | 65 % | 624 MB | 464 KB |

NVENC deja la CPU al juego y el archivo sale algo más grande a igual `cq`;
bajar a `--crf 26` lo empareja. `hevc_nvenc` comprime mejor pero tarda más en
reproducirse. AV1 **no**: es Ampere y NVENC AV1 pide Ada.

## Post-proceso

Recortar sin recomprimir:

```bash
ffmpeg -ss 20 -i video/partidas/<clip>.mp4 -c copy video/partidas/<clip>-corte.mp4
```

GIF ligero para el README del repo (12 fps, 1280 de ancho):

```bash
ffmpeg -i video/partidas/<clip>.mp4 -t 15 -vf \
  "fps=12,scale=1280:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" \
  -loop 0 video/gifs/<clip>.gif
```

## Estructura

| Carpeta | Qué va aquí |
|---|---|
| `partidas/` | clips del juego (Jev jugando, con el panel SCADA) |
| `demos/` | grabaciones de terminal, del refactor, de una revisión |
| `gifs/` | recortes ligeros para embeber en el README |
| `_raw/` | capturas sin recortar; descartables en cualquier momento |

## Convención de nombres

```
<YYYY-MM-DD>_<HHMMSS>_<tipo>_<pilot>_<prompt>_<WxH>[_<slug>].mp4
```

La fecha va primero para que `ls` salga cronológico; sin espacios ni acentos
para que sea seguro en scripts y URLs. Cada `.mp4` lleva su ficha al lado, con
el mismo nombre y extensión `.json`:

```json
{
  "archivo": "2026-10-11_094838_partida_jev-assisted_v3w_1920x1080.mp4",
  "tipo": "partida",
  "pilot": "jev-assisted",
  "prompt_version": "v3w",
  "encoder": "h264_nvenc",
  "resolucion": "1920x1080",
  "origen": "window",
  "fps": 30,
  "calidad": 23,
  "limite_s": 60,
  "duracion_s": 20,
  "bytes": 14153551,
  "motor_commit": "87f4827f88b005515d92e6ed3c3756641ad2b0d0",
  "display": ":1",
  "fecha": "2026-10-11T09:49:02-05:00"
}
```

## Índice de clips

| Clip | Tipo | Pilot | Prompt | Resolución | Duración | Códec |
|---|---|---|---|---|---|---|
| `partidas/2026-10-11_095332_partida_jev-assisted_v3w_1920x1080.mp4` | partida | jev-assisted | v3w | 1920×1080 | 1:00 | h264_nvenc |
| `partidas/2026-10-11_094838_partida_jev-assisted_v3w_1920x1080.mp4` | partida | jev-assisted | v3w | 1920×1080 | 0:20 | h264_nvenc |
