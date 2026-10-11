#!/usr/bin/env bash
# Lanza el demo: Jev (TypeSafe System One) jugando Doom/Freedoom con el motor Duum.
#
#   bash play.sh              -> ventana de juego con panel de decisiones
#   bash play.sh --headless   -> sin ventana, resumen JSON (kills, salud, tiempo)
#
# La clave viaja en TYPESAFE_API_KEY. Se toma del entorno o de .env (ignorado por
# git). Cada decisión es una llamada a https://api.typesafe.ai (~$0.00005 c/u).
# No descarga PyTorch ni checkpoints: sólo stdlib + el motor Duum.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if [ -z "${TYPESAFE_API_KEY:-}" ]; then
  echo "Falta TYPESAFE_API_KEY: expórtala o ponla en jev-duum/.env" >&2
  exit 1
fi

echo "[1/2] Sincronizando entorno (uv sync)..." >&2
uv sync

echo "[2/2] Arrancando Jev jugando (modo: ${*:-jev-assisted})..." >&2
exec uv run --no-sync jev-duum --pilot jev-assisted "$@"
