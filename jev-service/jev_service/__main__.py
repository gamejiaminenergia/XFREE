"""``python -m jev_service`` runs the service, same as the console script."""

from __future__ import annotations

from .server import main

if __name__ == "__main__":
    raise SystemExit(main())
