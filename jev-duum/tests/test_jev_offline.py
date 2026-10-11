import json
import os
import socket
from pathlib import Path

import pytest

from jev_duum.cli import main

ROOT = Path(__file__).parents[1]
DUUM_ROOT = Path(os.environ.get("JEV_DUUM_PATH", ROOT.parent / "duum"))
WAD = ROOT / "freedoom1.wad"
if not WAD.is_file():
    WAD = ROOT.parent / "laya-duum" / "freedoom1.wad"
HAS_FIXTURE = (DUUM_ROOT / "duum" / "engine.py").is_file() and WAD.is_file()


@pytest.mark.skipif(
    not HAS_FIXTURE,
    reason="needs the pinned sibling Duum checkout and a local freedoom1.wad",
)
def test_headless_cli_performs_no_network_calls(monkeypatch, capsys):
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    result = main(
        [
            "--duum-path",
            str(DUUM_ROOT),
            "--wad",
            str(WAD),
            "--pilot",
            "scripted",
            "--headless",
            "--ticks",
            "3",
            "--size",
            "96x64",
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    assert result == 0
    assert summary["network"] == "offline"
    assert summary["pilot"] == "scripted"
    assert summary["model_inference"] is False
    assert attempts == []
