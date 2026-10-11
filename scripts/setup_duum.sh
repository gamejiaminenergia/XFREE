#!/usr/bin/env bash
# Clone the pinned Duum engine (MPL-2.0) next to the jev-duum package.
#
# The adapter checks the engine's git HEAD against an exact commit, so the demo
# never follows a moving branch silently. Duum is not vendored in this
# repository: this script puts it where ``default_duum_checkout`` looks for it.
#
#   bash scripts/setup_duum.sh
#
# Override with DUUM_REPO / DUUM_COMMIT / JEV_DUUM_PATH if you keep the engine
# somewhere else.
set -euo pipefail

DUUM_REPO="${DUUM_REPO:-https://github.com/hmofet/duum.git}"
DUUM_COMMIT="${DUUM_COMMIT:-87f4827f88b005515d92e6ed3c3756641ad2b0d0}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${JEV_DUUM_PATH:-$ROOT/duum}"

if [ -d "$TARGET/.git" ]; then
  current="$(git -C "$TARGET" rev-parse HEAD 2>/dev/null || true)"
  if [ "$current" = "$DUUM_COMMIT" ]; then
    echo "duum is already at $DUUM_COMMIT"
    exit 0
  fi
  echo "updating duum: $current -> $DUUM_COMMIT"
  git -C "$TARGET" fetch --tags origin
  git -C "$TARGET" checkout "$DUUM_COMMIT"
elif [ -e "$TARGET" ]; then
  echo "refusing to touch $TARGET: it exists and is not a git checkout" >&2
  exit 1
else
  echo "cloning $DUUM_REPO into $TARGET"
  git clone "$DUUM_REPO" "$TARGET"
  git -C "$TARGET" checkout "$DUUM_COMMIT"
fi

echo "duum ready at $TARGET ($DUUM_COMMIT)"
