import os
from pathlib import Path

import pytest

from jev_duum.benchmark import run_headless
from jev_duum.integration import load_duum
from jev_duum.recording import EpisodeRecorder, load_recording
from jev_duum.replay import replay_recording
from jev_duum.wad import resolve_wad

ROOT = Path(__file__).parents[1]
DUUM_ROOT = Path(os.environ.get("JEV_DUUM_PATH", ROOT.parent / "duum"))
WAD_PATH = ROOT / "freedoom1.wad"
HAS_FIXTURE = (DUUM_ROOT / "duum" / "engine.py").is_file() and WAD_PATH.is_file()

pytestmark = pytest.mark.skipif(
    not HAS_FIXTURE,
    reason="needs the pinned sibling Duum checkout and a local freedoom1.wad",
)


def test_synchronous_recording_replays_without_inference(tmp_path):
    modules = load_duum(DUUM_ROOT)
    wad = resolve_wad(WAD_PATH)
    path = tmp_path / "episode.json"
    recorder = EpisodeRecorder(
        path,
        pilot="scripted",
        duum={"commit": modules.commit, "source": modules.source},
        wad=wad.to_dict(),
        map_name="E1M1",
        tick_rate=60,
        decision_rate=12,
    )
    summary = run_headless(
        modules,
        wad,
        pilot="scripted",
        ticks=180,
        width=96,
        height=64,
        recorder=recorder,
    )
    data = load_recording(path)
    replay = replay_recording(modules, wad, data, width=96, height=64)
    assert replay["matched"] is True
    assert replay["model_inference"] is False
    assert replay["final_state_hash"] == summary["final_engine_hash"]
    assert data["wad"]["filename"] == "freedoom1.wad"
    assert "path" not in data["wad"]
    assert data["network"] == "offline"


def test_recorder_records_the_online_network_posture(tmp_path):
    modules = load_duum(DUUM_ROOT)
    wad = resolve_wad(WAD_PATH)
    path = tmp_path / "online.json"
    recorder = EpisodeRecorder(
        path,
        pilot="jev-assisted",
        duum={"commit": modules.commit, "source": modules.source},
        wad=wad.to_dict(),
        map_name="E1M1",
        tick_rate=60,
        decision_rate=10,
        network="online: api.typesafe.ai",
    )
    recorder.finish({"mode": "synchronous"})
    assert load_recording(path)["network"] == "online: api.typesafe.ai"
