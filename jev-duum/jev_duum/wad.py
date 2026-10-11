"""Resolve and fingerprint a local IWAD without networking."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WadInfo:
    path: Path
    filename: str
    size: int
    sha256: str
    kind: str

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "size": self.size,
            "sha256": self.sha256,
            "kind": self.kind,
            "source": "local path",
        }


def default_wad_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    for candidate in (
        root / "freedoom1.wad",
        root / "assets" / "freedoom1.wad",
        root.parent / "laya-duum" / "freedoom1.wad",
    ):
        if candidate.is_file():
            return candidate
    return root / "freedoom1.wad"


def resolve_wad(value) -> WadInfo:
    if value is None:
        raise FileNotFoundError(
            "A local WAD is required. This source project includes Freedoom Phase 1 as "
            "./freedoom1.wad; otherwise pass --wad /path/to/file.wad."
        )
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Local WAD does not exist: {path}")
    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12 or header[:4] not in (b"IWAD", b"PWAD"):
            raise ValueError(f"Not a Doom-format IWAD/PWAD: {path}")
        digest = hashlib.sha256()
        digest.update(header)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return WadInfo(path, path.name, path.stat().st_size, digest.hexdigest(), header[:4].decode())
