"""Load the git-ignored local ``.env`` without ever overriding the environment."""

from __future__ import annotations

import os
from pathlib import Path


def env_file_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".env"


def load_local_env(path: Path | None = None) -> None:
    """Populate missing variables from ``.env``; an exported value always wins."""

    env_path = env_file_path() if path is None else Path(path)
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        os.environ.setdefault(name.strip(), value.strip())
