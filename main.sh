#!/usr/bin/env bash
# Lanzador unico: hace todo y abre el juego.
#
#   ./main.sh                      # Jev juega (una sola ventana: decision + inspector)
#   ./main.sh --windowed           # ventana normal
#   ./main.sh --headless --ticks 600
#   ./main.sh --pilot manual       # juegas tu
#   ./main.sh --prompt-version v3
#
# Localiza (o crea) un checkout de Duum EN EL COMMIT FIJADO que el adaptador
# valida, sincroniza el entorno y arranca. Cualquier argumento extra se pasa a
# jev-duum. Nada de esto modifica tu checkout duum/: si su HEAD no coincide con
# el pin, se usa un worktree aparte.
#
# Por defecto aplica el mod de balance (10x vida, 10x dano, 20x municion) al
# motor que use; es idempotente y reversible. Con JEV_VANILLA=1 arranca el
# juego original.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$ROOT/jev-duum"
PARENT="$(cd "$ROOT/.." && pwd)"

DUUM_REPO="${DUUM_REPO:-https://github.com/hmofet/duum.git}"
PIN="${DUUM_COMMIT:-87f4827f88b005515d92e6ed3c3756641ad2b0d0}"
WORKTREE="${JEV_PINNED_DUUM:-$PARENT/duum-${PIN:0:7}}"

die() { echo "main.sh: $*" >&2; exit 1; }

at_pin() {
  [ -f "$1/duum/engine.py" ] || return 1
  [ "$(git -C "$1" rev-parse HEAD 2>/dev/null || true)" = "$PIN" ]
}

# 1) el sibling duum/ si ya esta en el commit fijado
if at_pin "$ROOT/duum"; then
  DUUM="$ROOT/duum"
# 2) un worktree fijado ya preparado
elif at_pin "$WORKTREE"; then
  DUUM="$WORKTREE"
# 3) crear el worktree desde tu propio checkout (no lo modifica)
elif [ -d "$ROOT/duum/.git" ]; then
  if [ -e "$WORKTREE" ]; then
    die "$WORKTREE existe pero no esta en $PIN; borralo o define JEV_PINNED_DUUM"
  fi
  echo "main.sh: $(basename "$ROOT/duum") no esta en el pin; creando worktree en $WORKTREE" >&2
  git -C "$ROOT/duum" worktree add --detach "$WORKTREE" "$PIN" >/dev/null
  DUUM="$WORKTREE"
# 4) clonar el motor desde cero
else
  echo "main.sh: clonando Duum en $WORKTREE" >&2
  git clone --quiet "$DUUM_REPO" "$WORKTREE"
  git -C "$WORKTREE" checkout --quiet "$PIN"
  DUUM="$WORKTREE"
fi

# Credencial: variable de entorno o jev-duum/.env. La primera vez se pide una
# sola vez y se guarda (git-ignored, nunca se imprime).
if [ -z "${TYPESAFE_API_KEY:-}" ]; then
  if [ ! -f "$PKG/.env" ]; then
    cp "$PKG/.env.example" "$PKG/.env"
  fi
  if ! grep -qE '^TYPESAFE_API_KEY=.+' "$PKG/.env"; then
    if [ -t 0 ]; then
      printf 'Pega tu TYPESAFE_API_KEY y pulsa Enter (se guarda en %s): ' "$PKG/.env" >&2
      read -rs _key
      echo >&2
      if [ -n "${_key:-}" ]; then
        _tmp="$(mktemp)"
        grep -v '^TYPESAFE_API_KEY=' "$PKG/.env" > "$_tmp" || true
        printf 'TYPESAFE_API_KEY=%s\n' "$_key" >> "$_tmp"
        mv "$_tmp" "$PKG/.env"
        unset _key
      fi
    fi
    grep -qE '^TYPESAFE_API_KEY=.+' "$PKG/.env" \
      || die "falta TYPESAFE_API_KEY en $PKG/.env (pega la clave y reintenta)"
  fi
fi

command -v uv >/dev/null || die "falta 'uv' (https://docs.astral.sh/uv)"
command -v git >/dev/null || die "falta 'git'"

echo "main.sh: motor en $DUUM" >&2
( cd "$PKG" && uv sync --quiet )

if [ "${JEV_VANILLA:-0}" = "1" ]; then
  echo "main.sh: JEV_VANILLA=1 -> sin mod de balance" >&2
else
  python3 "$ROOT/mods/balance.py" --duum "$DUUM" \
    || echo "main.sh: aviso: no pude aplicar el mod de balance; sigo sin el" >&2
fi

echo "main.sh: arrancando (Ctrl-C para cortar; en pantalla completa: F11 alterna, 'salir' cierra)" >&2
cd "$PKG"
exec uv run --no-sync jev-duum --pilot jev-assisted --duum-path "$DUUM" "$@"
