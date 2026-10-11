#!/usr/bin/env bash
# Graba la partida (o una demo) en video/<tipo>/ con nombre ordenable y ficha.
#
#   bash scripts/record.sh --launch              # lanza ./main.sh y graba la partida
#   bash scripts/record.sh --launch --window     # graba solo la ventana del panel
#   bash scripts/record.sh --tipo demo           # graba lo que ya tengas en pantalla
#
# `--window` recorta a la ventana del juego (no graba el resto del escritorio);
# `--windowed` es lo que hace que el juego se abra en una ventana en vez de a
# pantalla completa.  Son cosas distintas a propósito: en este equipo, a
# pantalla completa el juego ocupa un monitor y el otro se cuela en la captura.
#
# Se para con Ctrl-C (o `pkill -INT -f record.sh`), o sola a los --seconds (60
# por defecto).  El MP4 se cierra siempre: ffmpeg va en su propio grupo de
# procesos (setsid) y el trap le manda un único SIGINT, que es lo que finaliza
# el contenedor sin truncarlo.  El juego también va en su propia sesión, así que
# un Ctrl-C para la grabación pero no lo mata.  La captura usa píxeles del
# escritorio (x11grab): lo que tape la ventana, se graba.
#
# Codifica con NVENC si la GPU lo admite (menos CPU y memoria para el juego) y
# cae a libx264 si no; `--encoder` lo fuerza.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="${TMPDIR:-/tmp}/opencode"

DISPLAY_SPEC="${DISPLAY:-:0}"
TIPO="partida"
PILOT="jev-assisted"
PROMPT_VER="v3w"
ENCODER="auto"
FPS=30
CRF=23
SCALE=""
NOMBRE=""
OUT_DIR=""
LAUNCH=0
WINDOW=0
WINDOWED=0
FROM_BACKEND=0
FAKE=0
ENGINE_SIZE="320x200"
DUUM_PATH=""
WAD_PATH=""
WINDOW_NAME="Duum"
LAUNCH_CMD=""
WAIT_WINDOW=180
MIN_SECONDS=0
SECONDS_LIMIT=60
PASSTHRU=()

usage() {
  sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Opciones:
  --launch              lanza el juego y graba (por defecto: graba lo que haya)
  --window              recorta la captura a la ventana del juego
  --full                graba todo el escritorio (por defecto)
  --windowed            abre el juego en una ventana en vez de a pantalla completa
  --tipo partida|demo   subcarpeta y prefijo del nombre (por defecto: partida)
  --nombre SLUG         sufijo libre para el nombre del archivo
  --pilot NAME          pilot que se graba (por defecto: jev-assisted)
  --prompt VER          prompt_version (por defecto: v3w)
  --encoder E           auto|nvenc|hevc|x264 (por defecto: auto)
  --fps N               fotogramas por segundo (por defecto: 30)
  --crf N               calidad, menor = mejor y más pesado (por defecto: 23)
  --scale WxH           reescala la salida (p.ej. 2560:720) para archivos más ligeros
  --out-dir DIR         carpeta destino (por defecto: video/<tipo>)
  --display SPEC        pantalla X (por defecto: $DISPLAY)
  --from-backend        graba desde el raster del motor: sin X, sin escritorio y
                        sin panel (solo la vista del juego), frame a frame exacto
  --fake                con --from-backend, modelo local determinista (0 $, sin clave)
  --engine-size WxH     tamano del canvas del motor (por defecto: 320x200)
  --duum-path DIR       checkout pinneado del motor (solo --from-backend)
  --wad PATH            IWAD a jugar (solo --from-backend)
  --window-name PAT     patrón de la ventana a grabar (por defecto: Duum)
  --launch-cmd CMD      comando de arranque alternativo a ./main.sh
  --seconds N           para a los N segundos; 0 = sin límite (por defecto: 60)
  --min-seconds N       descarta grabaciones más cortas que N segundos
  -h, --help            esta ayuda

Todo lo que pongas tras `--` se pasa al juego.
EOF
}

sanitize() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9._-]\+/-/g; s/^-\+//; s/-\+$//'
}

# The biggest visible window whose name matches; Tk creates several children.
find_window() {
  local id best="" best_area=0 area
  for id in $(xdotool search --onlyvisible --name "$WINDOW_NAME" 2>/dev/null || true); do
    area="$(xdotool getwindowgeometry --shell "$id" 2>/dev/null \
      | awk -F= '/^WIDTH=/{w=$2} /^HEIGHT=/{h=$2} END{print (w?w:0)*(h?h:0)}')"
    if [ "${area:-0}" -gt "$best_area" ]; then best_area="$area"; best="$id"; fi
  done
  printf '%s' "$best"
  return 0
}

duration_of() {
  local raw
  raw="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$1" 2>/dev/null || true)"
  awk -v d="${raw:-0}" 'BEGIN{printf "%d", d+0.5}'
}

# A real 0.1 s encode: the encoder being listed is not the same as it working.
# NVENC refuses frames below its minimum size, so the probe must be a real one
# (64x64 fails with "Frame Dimension less than the minimum supported value").
nvenc_works() {
  ffmpeg -hide_banner -loglevel error -f lavfi -i nullsrc=s=320x240:d=0.1 \
    -c:v h264_nvenc -f null - >/dev/null 2>&1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --launch) LAUNCH=1; shift ;;
    --no-launch) LAUNCH=0; shift ;;
    --window) WINDOW=1; shift ;;
    --windowed) WINDOWED=1; shift ;;
    --full) WINDOW=0; shift ;;
    --from-backend) FROM_BACKEND=1; shift ;;
    --fake) FAKE=1; shift ;;
    --engine-size) ENGINE_SIZE="${2:?}"; shift 2 ;;
    --duum-path) DUUM_PATH="${2:?}"; shift 2 ;;
    --wad) WAD_PATH="${2:?}"; shift 2 ;;
    --tipo) TIPO="${2:?--tipo necesita un valor}"; shift 2 ;;
    --nombre) NOMBRE="${2:?}"; shift 2 ;;
    --pilot) PILOT="${2:?}"; shift 2 ;;
    --prompt) PROMPT_VER="${2:?}"; shift 2 ;;
    --encoder) ENCODER="${2:?}"; shift 2 ;;
    --fps) FPS="${2:?}"; shift 2 ;;
    --crf) CRF="${2:?}"; shift 2 ;;
    --scale) SCALE="${2:?}"; shift 2 ;;
    --out-dir) OUT_DIR="${2:?}"; shift 2 ;;
    --display) DISPLAY_SPEC="${2:?}"; shift 2 ;;
    --window-name) WINDOW_NAME="${2:?}"; shift 2 ;;
    --launch-cmd) LAUNCH_CMD="${2:?}"; shift 2 ;;
    --seconds) SECONDS_LIMIT="${2:?}"; shift 2 ;;
    --min-seconds) MIN_SECONDS="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; PASSTHRU=("$@"); break ;;
    *) echo "record.sh: opción desconocida: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for tool in ffmpeg ffprobe xdotool xwininfo; do
  command -v "$tool" >/dev/null 2>&1 || { echo "record.sh: falta $tool" >&2; exit 1; }
done

# ── codificador ─────────────────────────────────────────────────────────────
case "$ENCODER" in
  auto)
    if nvenc_works; then CODEC="h264_nvenc"; else CODEC="libx264"; fi ;;
  nvenc|h264|h264_nvenc) CODEC="h264_nvenc" ;;
  hevc|hevc_nvenc)        CODEC="hevc_nvenc" ;;
  x264|libx264)           CODEC="libx264" ;;
  *) echo "record.sh: encoder desconocido: $ENCODER" >&2; exit 2 ;;
esac
if [ "$CODEC" = "libx264" ]; then
  ENC_ARGS=(-c:v libx264 -preset veryfast -crf "$CRF")
else
  # NVENC no entiende -crf: calidad constante es -rc vbr con -cq y -b:v 0.
  ENC_ARGS=(-c:v "$CODEC" -preset p5 -tune hq -rc vbr -cq "$CRF" -b:v 0)
  if [ "$CODEC" = "hevc_nvenc" ]; then ENC_ARGS+=(-tag:v hvc1); fi
fi

case "$TIPO" in
  partida|partidas) SUBDIR="partidas" ;;
  demo|demos)       SUBDIR="demos" ;;
  gif|gifs)         SUBDIR="gifs" ;;
  raw|_raw)         SUBDIR="_raw" ;;
  *)                SUBDIR="$TIPO" ;;
esac
OUT_DIR="${OUT_DIR:-$ROOT/video/$SUBDIR}"
mkdir -p "$OUT_DIR" "$TMP"

STAMP_DATE="$(date +%Y-%m-%d)"
STAMP_TIME="$(date +%H%M%S)"
GAME_LOG="$TMP/record-game-$STAMP_TIME.log"
GAME_PID=""

# ── grabacion desde el backend: raster del motor -> ffmpeg, sin X ────────────
if [ "$FROM_BACKEND" = 1 ]; then
  case "$ENGINE_SIZE" in
    *x*) ;;
    *) echo "record.sh: --engine-size quiere WxH (p.ej. 320x200)" >&2; exit 2 ;;
  esac
  EGW="${ENGINE_SIZE%x*}"
  EGH="${ENGINE_SIZE#*x}"
  SLUG="$(sanitize "${NOMBRE:-}")"
  BASE="${STAMP_DATE}_${STAMP_TIME}_${TIPO}_$(sanitize "$PILOT")_$(sanitize "$PROMPT_VER")_${EGW}x${EGH}"
  [ -n "$SLUG" ] && BASE="${BASE}_${SLUG}"
  MP4="$OUT_DIR/$BASE.mp4"
  SIDECAR="$OUT_DIR/$BASE.json"
  FAKE_ARG=""
  [ "$FAKE" = 1 ] && FAKE_ARG="--fake"
  DUUM_ARG=""
  [ -n "$DUUM_PATH" ] && DUUM_ARG="--duum-path $DUUM_PATH"
  WAD_ARG=""
  [ -n "$WAD_PATH" ] && WAD_ARG="--wad $WAD_PATH"
  echo "· grabando desde el backend ${EGW}x${EGH} a ${FPS} fps → $MP4"
  echo "  (Ctrl-C lo para y cierra el MP4; es la vista del juego, sin panel)"
  SUMMARY="$(cd "$ROOT/jev-duum" && uv run --no-sync python tools/record_headless.py \
      --out "$MP4" --seconds "$SECONDS_LIMIT" --fps "$FPS" --crf "$CRF" \
      --encoder "$ENCODER" --size "$ENGINE_SIZE" \
      --pilot "$PILOT" --prompt-version "$PROMPT_VER" $FAKE_ARG $DUUM_ARG $WAD_ARG \
      2>/dev/null | tail -1)"
  if [ ! -s "$MP4" ]; then
    echo "record.sh: no se generó el vídeo; resumen del grabador: $SUMMARY" >&2
    exit 1
  fi
  getnum() { printf '%s' "$SUMMARY" | sed -n "s/.*\"$1\": \([0-9.]*\).*/\1/p"; }
  getstr() { printf '%s' "$SUMMARY" | sed -n "s/.*\"$1\": \"\([^\"]*\)\".*/\1/p"; }
  FRAMES="$(getnum frames)"
  SECS="$(getnum seconds)"
  CODEC="$(getstr encoder)"
  MODEL_ID="$(getstr model)"
  BYTES="$(stat -c %s "$MP4")"
  COMMIT="$(getstr engine_commit)"
  DUR="$(awk -v seconds="${SECS:-0}" 'BEGIN{printf "%d", seconds+0.5}')"
  MM=$((DUR / 60)); SS=$((DUR % 60))
  printf '%s\n' \
    '{' \
    "  \"archivo\": \"$BASE.mp4\"," \
    "  \"tipo\": \"$TIPO\"," \
    "  \"pilot\": \"$PILOT\"," \
    "  \"prompt_version\": \"$PROMPT_VER\"," \
    "  \"modelo\": \"$MODEL_ID\"," \
    "  \"encoder\": \"$CODEC\"," \
    "  \"resolucion\": \"${EGW}x${EGH}\"," \
    "  \"origen\": \"backend\"," \
    "  \"fps\": $FPS," \
    "  \"calidad\": $CRF," \
    "  \"frames\": ${FRAMES:-0}," \
    "  \"duracion_s\": ${SECS:-0}," \
    "  \"bytes\": $BYTES," \
    "  \"motor_commit\": \"$COMMIT\"," \
    "  \"fecha\": \"$(date -Iseconds)\"" \
    '}' >"$SIDECAR"
  echo
  echo "✔ $MP4"
  echo "  $((BYTES / 1048576)) MB · ${MM}:$(printf '%02d' "$SS") · ${EGW}x${EGH} @ ${FPS}fps · $CODEC · ${FRAMES:-0} frames · ficha: $(basename "$SIDECAR")"
  echo
  echo "Fila para video/README.md:"
  echo "| \`$SUBDIR/$BASE.mp4\` | $TIPO | $PILOT | $PROMPT_VER | ${EGW}x${EGH} | ${MM}:$(printf '%02d' "$SS") | $CODEC |"
  exit 0
fi

# ── 1. lanzar el juego si nos lo piden ───────────────────────────────────────
if [ "$LAUNCH" = 1 ]; then
  if [ -n "$LAUNCH_CMD" ]; then
    RUN_CMD=(bash -c "$LAUNCH_CMD")
  else
    RUN_CMD=("$ROOT/main.sh")
    if [ "$WINDOWED" = 1 ]; then RUN_CMD+=(--windowed); fi
    RUN_CMD+=(--pilot "$PILOT" --prompt-version "$PROMPT_VER")
    if [ "${#PASSTHRU[@]}" -gt 0 ]; then RUN_CMD+=("${PASSTHRU[@]}"); fi
  fi
  echo "· lanzando el juego (log: $GAME_LOG)"
  ( cd "$ROOT" && exec setsid "${RUN_CMD[@]}" ) >"$GAME_LOG" 2>&1 &
  GAME_PID=$!
fi

# ── 2. esperar a que la ventana exista y esté pintada ────────────────────────
if [ "$LAUNCH" = 1 ] || [ "$WINDOW" = 1 ]; then
  echo "· esperando la ventana '$WINDOW_NAME' (hasta ${WAIT_WINDOW}s)"
  waited=0
  while [ -z "$(find_window)" ]; do
    sleep 0.5
    waited=$((waited + 1))
    if [ "$waited" -ge $((WAIT_WINDOW * 2)) ]; then
      echo "record.sh: la ventana no apareció; abortando (log: $GAME_LOG)" >&2
      if [ -n "$GAME_PID" ]; then kill "$GAME_PID" 2>/dev/null || true; fi
      exit 1
    fi
    if [ -n "$GAME_PID" ] && ! kill -0 "$GAME_PID" 2>/dev/null; then
      echo "record.sh: el juego terminó antes de abrir ventana (log: $GAME_LOG)" >&2
      tail -n 20 "$GAME_LOG" >&2 || true
      exit 1
    fi
  done
  sleep 1  # deja que pinte el primer fotograma
fi

# ── 3. geometría de la captura, recortada a la pantalla ─────────────────────
ROOTINFO="$(xwininfo -root)"
SCREEN_W="$(awk '/Width:/{print $2}' <<<"$ROOTINFO")"
SCREEN_H="$(awk '/Height:/{print $2}' <<<"$ROOTINFO")"

if [ "$WINDOW" = 1 ]; then
  WID="$(find_window)"
  [ -n "$WID" ] || { echo "record.sh: no hay ventana '$WINDOW_NAME' que grabar" >&2; exit 1; }
  GEO="$(xdotool getwindowgeometry --shell "$WID")"
  GW="$(awk -F= '/^WIDTH=/{print $2}' <<<"$GEO")"
  GH="$(awk -F= '/^HEIGHT=/{print $2}' <<<"$GEO")"
  GX="$(awk -F= '/^X=/{print $2}' <<<"$GEO")"
  GY="$(awk -F= '/^Y=/{print $2}' <<<"$GEO")"
  SOURCE="window"
else
  GW="$SCREEN_W"
  GH="$SCREEN_H"
  GX=0
  GY=0
  SOURCE="full"
fi

# Una ventana puede asomar fuera de la pantalla (o el gestor dejarla en
# coordenadas negativas) y x11grab exige un rectángulo dentro de ella.
if [ "$GX" -lt 0 ]; then GX=0; fi
if [ "$GY" -lt 0 ]; then GY=0; fi
if [ $((GX + GW)) -gt "$SCREEN_W" ]; then GW=$((SCREEN_W - GX)); fi
if [ $((GY + GH)) -gt "$SCREEN_H" ]; then GH=$((SCREEN_H - GY)); fi
if [ "$GW" -lt 16 ] || [ "$GH" -lt 16 ]; then
  echo "record.sh: la región a grabar quedó vacía (${GW}x${GH}+${GX},${GY})" >&2
  exit 1
fi

VF="scale=trunc(iw/2)*2:trunc(ih/2)*2"
[ -n "$SCALE" ] && VF="$VF,scale=$SCALE"

SLUG="$(sanitize "${NOMBRE:-}")"
BASE="${STAMP_DATE}_${STAMP_TIME}_${TIPO}_$(sanitize "$PILOT")_$(sanitize "$PROMPT_VER")_${GW}x${GH}"
[ -n "$SLUG" ] && BASE="${BASE}_${SLUG}"
MP4="$OUT_DIR/$BASE.mp4"
SIDECAR="$OUT_DIR/$BASE.json"
FFLOG="$OUT_DIR/.ffmpeg-$STAMP_TIME.log"

# ── 4. grabar ───────────────────────────────────────────────────────────────
echo "· grabando ${GW}x${GH}+${GX},${GY} en $DISPLAY_SPEC a ${FPS} fps con $CODEC → $MP4"
LIMIT_ARGS=()
if [ "$SECONDS_LIMIT" -gt 0 ]; then LIMIT_ARGS=(-t "$SECONDS_LIMIT"); fi
setsid ffmpeg -hide_banner -loglevel warning -nostdin \
  -f x11grab -draw_mouse 0 -framerate "$FPS" -thread_queue_size 1024 \
  -video_size "${GW}x${GH}" -i "${DISPLAY_SPEC}.0+${GX},${GY}" \
  "${LIMIT_ARGS[@]}" -vf "$VF" "${ENC_ARGS[@]}" -pix_fmt yuv420p \
  -movflags +faststart -an "$MP4" >"$FFLOG" 2>&1 &
FFPID=$!

stop() {
  [ "${STOPPING:-0}" = 1 ] && return 0
  STOPPING=1
  if kill -0 "$FFPID" 2>/dev/null; then
    echo "· cerrando el vídeo..."
    kill -INT "$FFPID" 2>/dev/null || true
    for _ in $(seq 1 100); do
      kill -0 "$FFPID" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$FFPID" 2>/dev/null; then kill -KILL "$FFPID" 2>/dev/null || true; fi
  fi
  return 0
}
trap 'stop; exit 0' INT TERM

if [ "$LAUNCH" = 1 ]; then
  # La grabación termina sola cuando la ventana del juego desaparece.
  miss=0
  while kill -0 "$FFPID" 2>/dev/null; do
    if [ -z "$(find_window)" ]; then
      miss=$((miss + 1))
      [ "$miss" -ge 3 ] && break
    else
      miss=0
    fi
    sleep 0.5
  done
  stop
else
  while kill -0 "$FFPID" 2>/dev/null; do sleep 0.5; done
fi

if [ -n "$GAME_PID" ] && kill -0 "$GAME_PID" 2>/dev/null; then
  echo "· nota: el juego sigue en marcha (pid $GAME_PID)"
fi

# ── 5. ficha y resumen ──────────────────────────────────────────────────────
if [ ! -s "$MP4" ]; then
  echo "record.sh: no se generó el vídeo; log de ffmpeg:" >&2
  cat "$FFLOG" >&2 || true
  rm -f "$MP4" "$FFLOG"
  exit 1
fi

DUR="$(duration_of "$MP4")"
if [ "$DUR" -lt "$MIN_SECONDS" ]; then
  echo "record.sh: grabación de ${DUR}s, por debajo de --min-seconds ${MIN_SECONDS}; se descarta" >&2
  rm -f "$MP4" "$FFLOG"
  exit 0
fi

BYTES="$(stat -c %s "$MP4")"
COMMIT="$(grep -m1 '^DUUM_COMMIT' "$ROOT/jev-duum/jev_duum/integration.py" 2>/dev/null \
  | sed 's/.*"\(.*\)".*/\1/' || true)"
ISO="$(date -Iseconds)"
MM=$((DUR / 60))
SS=$((DUR % 60))
printf '%s\n' \
  '{' \
  "  \"archivo\": \"$BASE.mp4\"," \
  "  \"tipo\": \"$TIPO\"," \
  "  \"pilot\": \"$PILOT\"," \
  "  \"prompt_version\": \"$PROMPT_VER\"," \
  "  \"encoder\": \"$CODEC\"," \
  "  \"resolucion\": \"${GW}x${GH}\"," \
  "  \"origen\": \"$SOURCE\"," \
  "  \"fps\": $FPS," \
  "  \"calidad\": $CRF," \
  "  \"limite_s\": $SECONDS_LIMIT," \
  "  \"duracion_s\": $DUR," \
  "  \"bytes\": $BYTES," \
  "  \"motor_commit\": \"$COMMIT\"," \
  "  \"display\": \"$DISPLAY_SPEC\"," \
  "  \"fecha\": \"$ISO\"" \
  '}' >"$SIDECAR"
rm -f "$FFLOG"

echo
echo "✔ $MP4"
echo "  $((BYTES / 1048576)) MB · ${MM}:$(printf '%02d' "$SS") · ${GW}x${GH} @ ${FPS}fps · $CODEC cq/crf $CRF · ficha: $(basename "$SIDECAR")"
echo
echo "Fila para video/README.md:"
echo "| \`$SUBDIR/$BASE.mp4\` | $TIPO | $PILOT | $PROMPT_VER | ${GW}x${GH} | ${MM}:$(printf '%02d' "$SS") | $CODEC |"
