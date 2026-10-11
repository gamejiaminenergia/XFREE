import json
import os
from pathlib import Path

import pytest

from jev_duum.benchmark import run_headless
from jev_duum.integration import DuumRuntime, load_duum
from jev_duum.recording import SCHEMA, EpisodeRecorder, load_recording
from jev_duum.replay import replay_recording
from jev_duum.snapshot import SnapshotBuilder
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


def test_snapshot_capture_stores_the_state_for_offline_prompt_ab(tmp_path):
    modules = load_duum(DUUM_ROOT)
    wad = resolve_wad(WAD_PATH)
    with DuumRuntime(modules, wad.path, "E1M1", 96, 64) as runtime:
        snap = SnapshotBuilder(runtime.app, modules.engine).build(0)

    class Result:
        prompt_version = "v2"

        def to_dict(self):
            return {"observation_tick": 0, "prompt_version": "v2"}

    path = tmp_path / "capture.json"
    recorder = EpisodeRecorder(
        path,
        pilot="jev-assisted",
        duum={"commit": modules.commit, "source": modules.source},
        wad=wad.to_dict(),
        map_name="E1M1",
        tick_rate=60,
        decision_rate=10,
        network="online: api.typesafe.ai",
        capture_snapshots=True,
    )
    recorder.decision(Result(), snap)
    recorder.finish({"mode": "synchronous"})
    data = load_recording(path)
    assert data["schema"] == SCHEMA == "jev-duum-episode-v2"
    entry = data["snapshots"][0]
    assert entry["prompt_version"] == "v2"
    assert entry["snapshot"]["tick"] == snap.tick
    assert entry["state"]["player"]["health"] == snap.player.health
    assert "conventions" in entry["state"]


def test_recording_without_capture_stays_lean_and_v1_still_loads(tmp_path):
    path = tmp_path / "lean.json"
    EpisodeRecorder(
        path,
        pilot="scripted",
        duum={"commit": "x", "source": "y"},
        wad={"filename": "freedoom1.wad"},
        map_name="E1M1",
        tick_rate=60,
        decision_rate=12,
    ).finish({"mode": "synchronous"})
    assert load_recording(path)["snapshots"] == []

    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"schema": "jev-duum-episode-v1"}))
    assert load_recording(legacy)["schema"] == "jev-duum-episode-v1"


def test_offline_pilot_can_capture_a_corpus_without_any_model_call(tmp_path):
    modules = load_duum(DUUM_ROOT)
    wad = resolve_wad(WAD_PATH)
    path = tmp_path / "corpus.json"
    recorder = EpisodeRecorder(
        path,
        pilot="scripted",
        duum={"commit": modules.commit, "source": modules.source},
        wad=wad.to_dict(),
        map_name="E1M1",
        tick_rate=60,
        decision_rate=12,
        capture_snapshots=True,
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
    assert summary["complete_decisions"] == len(data["snapshots"])
    assert data["snapshots"]
    assert "conventions" in data["snapshots"][0]["state"]
    assert data["decisions"] == []
