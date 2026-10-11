"""An opt-in smoke test that talks to the real TypeSafe System One API.

Skipped unless ``JEV_LIVE=1`` and a key is available (from the environment or the
git-ignored ``.env``). It costs a fraction of a cent and validates the whole wire
path end to end.
"""

import os
from pathlib import Path

import pytest

from jev_duum.controller import JevDuumController
from jev_duum.integration import DuumRuntime, load_duum
from jev_duum.prompts import PROMPT_VERSIONS
from jev_duum.snapshot import SnapshotBuilder
from jev_duum.types import AIMS, INTERACTIONS, MOVEMENTS

ROOT = Path(__file__).parents[1]
DUUM_ROOT = Path(os.environ.get("JEV_DUUM_PATH", ROOT.parent / "duum"))
WAD = ROOT / "freedoom1.wad"
HAS_FIXTURE = (DUUM_ROOT / "duum" / "engine.py").is_file() and WAD.is_file()


def _load_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


_load_env_file()
LIVE = os.environ.get("JEV_LIVE") == "1" and bool(os.environ.get("TYPESAFE_API_KEY"))

pytestmark = pytest.mark.skipif(
    not (LIVE and HAS_FIXTURE),
    reason="set JEV_LIVE=1 plus TYPESAFE_API_KEY, and keep the pinned Duum checkout",
)


@pytest.mark.parametrize("version", PROMPT_VERSIONS)
def test_live_decision_returns_valid_probabilities(version):
    modules = load_duum(DUUM_ROOT)
    with DuumRuntime(modules, WAD, "E1M1", 96, 64) as runtime:
        state = SnapshotBuilder(runtime.app, modules.engine).build(0)
    controller = JevDuumController(
        model=os.environ.get("TYPESAFE_MODEL", "jev-latest"), prompt_version=version
    )
    result = controller.decide(state)
    assert result.prediction_calls == 1
    assert result.model_id.startswith("jev")
    assert result.prompt_version == version
    assert set(result.probabilities) == {"movement", "aim", "interaction"}
    for name, labels in (
        ("movement", MOVEMENTS),
        ("aim", AIMS),
        ("interaction", INTERACTIONS),
    ):
        assert set(result.probabilities[name]) == set(labels)
        # Jev rounds each probability to two decimals, so a five-option
        # question can legitimately sum to 0.99 or 1.01.
        assert sum(result.probabilities[name].values()) == pytest.approx(1.0, abs=0.05)
    assert result.input_tokens["request"] > 0
    assert result.cost_usd > 0
