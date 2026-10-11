import hashlib

import pytest

from jev_duum.wad import resolve_wad


def test_local_wad_is_validated_and_fingerprinted(tmp_path):
    payload = b"IWAD" + (0).to_bytes(4, "little") + (12).to_bytes(4, "little") + b"data"
    path = tmp_path / "freedoom1.wad"
    path.write_bytes(payload)

    info = resolve_wad(path)

    assert info.path == path.resolve()
    assert info.filename == "freedoom1.wad"
    assert info.size == len(payload)
    assert info.sha256 == hashlib.sha256(payload).hexdigest()
    assert info.kind == "IWAD"
    assert "path" not in info.to_dict()


def test_missing_wad_is_actionable():
    with pytest.raises(FileNotFoundError, match="local WAD is required"):
        resolve_wad(None)


def test_non_wad_is_rejected(tmp_path):
    path = tmp_path / "not-a.wad"
    path.write_bytes(b"not doom data")
    with pytest.raises(ValueError, match="Not a Doom-format"):
        resolve_wad(path)
