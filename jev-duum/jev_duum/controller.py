"""Three factorized Jev decisions over one semantic Duum snapshot.

Jev is a System One model: one ``state`` per request, answered with typed values
and probabilities. The adapter therefore assembles one named-field state from
the canonical snapshot and asks the three Duum choices in that same request.
The deterministic assistance layer is model-agnostic; it only sees the argmax
controls.  Which state and which questions travel is selected by prompt version;
see ``prompts.py`` for the two frozen definitions.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import asdict, dataclass, replace

from .assistance import AssistanceEvent, apply_assistance
from .hunt import HuntTracker, compute_hunt, with_target
from .jev_client import DEFAULT_MODEL, JevClient, input_cost_usd
from .prompts import (
    DEFAULT_PROMPT_VERSION,
    PROMPT_VERSIONS,
    TARGET_CHOICES,
    build_questions,
    build_state,
)
from .snapshot import DuumSnapshot
from .strategy import StrategyTracker, compute_strategy, enforce_strategy
from .types import AIMS, INTERACTIONS, MOVEMENTS, DuumControls

try:  # The schematic world model is optional: gameplay must survive without it.
    from .world_model import build_world_model
except Exception:  # pragma: no cover - defensive import
    build_world_model = None

# Frozen legacy questions, kept importable for callers that predate versioning.
QUESTIONS = build_questions("v1")

DEFINITIONS = (
    ("movement", MOVEMENTS),
    ("aim", AIMS),
    ("interaction", INTERACTIONS),
)
DEFINITIONS_V4 = DEFINITIONS + (("target", TARGET_CHOICES),)


@dataclass(frozen=True, slots=True)
class DecisionResult:
    probabilities: dict[str, dict[str, float]]
    confidence: dict[str, float | None]
    proposed_controls: DuumControls
    applied_controls: DuumControls
    assistance_events: tuple[AssistanceEvent, ...]
    observation_tick: int
    application_tick: int | None
    snapshot_hash: str
    observations: dict[str, str]
    input_tokens: dict[str, int]
    model_id: str
    cost_usd: float
    request_ms: float
    inference_ms: float
    decision_ms: float
    prediction_calls: int
    execution: str
    prompt_version: str
    strategy: dict | None
    world_model: dict | None
    world_model_used: bool
    # The exact payload that travelled to Jev (state) and the questions asked.
    # They are kept for the Tk inspector so the requests can be shown verbatim;
    # nothing here changes what the model sees.
    request_state: dict | None = None
    request_questions: dict | None = None
    response_raw: dict | None = None
    hunt: dict | None = None
    target_choice: str | None = None

    def with_application_tick(self, tick: int) -> DecisionResult:
        return replace(self, application_tick=int(tick))

    def to_dict(self) -> dict:
        return asdict(self)


def _probabilities(answer: dict, labels: tuple[str, ...], name: str) -> dict[str, float]:
    try:
        values = answer["probabilities"]
    except (KeyError, TypeError) as error:
        raise ValueError(f"Jev returned malformed {name} probabilities") from error
    if set(values) != set(labels):
        raise ValueError(
            f"Jev returned unexpected {name} labels: {sorted(values)} != {sorted(labels)}"
        )
    parsed = {}
    for label in labels:
        value = values[label]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Jev returned malformed {name} probability")
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"Jev returned invalid {name} probability")
        parsed[label] = value
    # Jev reports probabilities rounded to two decimals, so a five-option
    # question can legitimately sum to 0.99 or 1.01. Reject only sums that are
    # far enough off to signal a malformed response; argmax is scale-invariant.
    if not math.isclose(sum(parsed.values()), 1.0, abs_tol=0.05):
        raise ValueError(f"Jev returned unnormalized {name} probabilities")
    return parsed


def _confidence(answer: dict, name: str) -> float | None:
    value = answer.get("confidence")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def parse_answers(
    response: dict, definitions=DEFINITIONS
) -> tuple[dict[str, dict[str, float]], dict[str, float | None]]:
    """Validate a Jev response and return ``(probabilities, confidence)``."""

    try:
        answers = response["answers"]
    except (KeyError, TypeError) as error:
        raise ValueError("Jev returned no answers") from error
    probabilities: dict[str, dict[str, float]] = {}
    confidence: dict[str, float | None] = {}
    for name, labels in definitions:
        try:
            answer = answers[name]
        except (KeyError, TypeError) as error:
            raise ValueError(f"Jev returned no {name} answer") from error
        probabilities[name] = _probabilities(answer, labels, name)
        confidence[name] = _confidence(answer, name)
    return probabilities, confidence


def argmax_controls(probabilities: dict[str, dict[str, float]]) -> DuumControls:
    """Reduce the three validated probability distributions to one control set."""

    return DuumControls(
        movement=max(MOVEMENTS, key=probabilities["movement"].__getitem__),
        aim=max(AIMS, key=probabilities["aim"].__getitem__),
        interaction=max(INTERACTIONS, key=probabilities["interaction"].__getitem__),
    )


def argmax_target(probabilities: dict[str, dict[str, float]]) -> str | None:
    """Reduce the optional ``target`` distribution to one label (``None`` if absent)."""

    values = probabilities.get("target")
    if not values:
        return None
    return max(TARGET_CHOICES, key=values.__getitem__)


class JevDuumController:
    """Turn one canonical snapshot into one Jev request and three controls."""

    def __init__(
        self,
        model: str | None = None,
        *,
        client: JevClient | None = None,
        assisted: bool = False,
        prompt_version: str | None = None,
        world_model: bool = True,
        pilot: str | None = None,
        api_key: str | None = None,
        endpoint: str | None = None,
        mission: str = "advance",
    ):
        self.assisted = bool(assisted)
        self.model = model or os.environ.get("TYPESAFE_MODEL") or DEFAULT_MODEL
        self.pilot = pilot
        self.use_world_model = bool(world_model)
        version = (
            prompt_version
            or os.environ.get("JEV_PROMPT_VERSION")
            or DEFAULT_PROMPT_VERSION
        )
        if version not in PROMPT_VERSIONS:
            raise ValueError(
                f"unknown prompt version: {version} (expected one of {PROMPT_VERSIONS})"
            )
        self.prompt_version = version
        self.questions = build_questions(version)
        self.definitions = DEFINITIONS_V4 if version == "v4" else DEFINITIONS
        self.tracker = StrategyTracker()
        self.hunt_tracker = HuntTracker()
        mission = str(mission or "clear").lower()
        if mission not in ("clear", "advance"):
            raise ValueError("mission must be 'clear' or 'advance'")
        self.mission = mission
        if client is None:
            client = JevClient(api_key=api_key, model=self.model, endpoint=endpoint)
        self.client = client
        self.client.log_context = {
            "pilot": self.pilot,
            "prompt_version": self.prompt_version,
            "stage": "decision",
        }
        self.metadata = {
            "name": "jev",
            "engine": "typesafe-systemone",
            "hardware": "remote",
            "network": "online",
            "model_source": "typesafe api",
            "model_id": self.model,
            "endpoint": getattr(client, "endpoint", None),
            "prompt_version": self.prompt_version,
            "mission": self.mission,
            "policy": "One Jev request with three choices over semantic Duum snapshots; "
            "pixels are never model input",
        }
        if mission == "clear":
            self.metadata["policy"] += (
                "; code-owned hunt plan, Jev picks the next kill"
                if version == "v4"
                else "; code-owned hunt plan"
            )

    # -- observations --------------------------------------------------------
    def combined_state(
        self,
        snapshot: DuumSnapshot,
        strategy=None,
        world_model: dict | None = None,
        hunt=None,
    ) -> tuple[dict, dict[str, str]]:
        """Build the request state for this controller's prompt version.

        Also returns the short human summary the panel renders, which stays the
        same for both prompt versions.
        """

        return build_state(snapshot, self.prompt_version, strategy, world_model, hunt)

    # -- decision ------------------------------------------------------------
    def decide(self, snapshot: DuumSnapshot) -> DecisionResult:
        started = time.perf_counter()
        hunt_plan = (
            compute_hunt(snapshot, self.hunt_tracker) if self.mission == "clear" else None
        )
        strategy = (
            compute_strategy(snapshot, self.tracker, hunt_plan)
            if self.prompt_version in ("v3", "v3w")
            else None
        )
        if self.prompt_version == "v4":
            strategy = compute_strategy(snapshot, self.tracker, hunt_plan)
        world = self._world_model(snapshot)
        state, observations = self.combined_state(snapshot, strategy, world, hunt_plan)
        request_started = time.perf_counter()
        response = self.client.ask(
            state,
            self.questions,
            context={
                "tick": snapshot.tick,
                "strategy": strategy.to_dict() if strategy else None,
                "hunt": hunt_plan.to_dict() if hunt_plan is not None else None,
            },
        )
        request_ms = (time.perf_counter() - request_started) * 1000

        probabilities, confidence = parse_answers(response, self.definitions)
        target_choice = argmax_target(probabilities)
        if self.prompt_version == "v4" and hunt_plan is not None:
            hunt_plan = self._apply_target_choice(snapshot, hunt_plan, target_choice)
            strategy = compute_strategy(snapshot, self.tracker, hunt_plan)

        usage = response.get("usage") or {}
        try:
            tokens = int(usage.get("input_tokens") or 0)
        except (TypeError, ValueError):
            tokens = 0
        model_id = str(response.get("model") or self.model)

        proposed = argmax_controls(probabilities)
        applied, events = self._assist(snapshot, proposed)
        if strategy is not None:
            applied, strategy_events = enforce_strategy(snapshot, strategy, applied)
            events = events + strategy_events
        self.tracker.observe(snapshot, applied)
        return DecisionResult(
            probabilities=probabilities,
            confidence=confidence,
            proposed_controls=proposed,
            applied_controls=applied,
            assistance_events=events,
            observation_tick=snapshot.tick,
            application_tick=None,
            snapshot_hash=snapshot.state_hash(),
            observations=observations,
            input_tokens={"request": tokens},
            model_id=model_id,
            cost_usd=input_cost_usd(tokens),
            request_ms=request_ms,
            inference_ms=(time.perf_counter() - started) * 1000,
            decision_ms=(time.perf_counter() - started) * 1000,
            prediction_calls=1,
            execution="single-request",
            prompt_version=self.prompt_version,
            strategy=strategy.to_dict() if strategy is not None else None,
            world_model=world,
            world_model_used=world is not None,
            request_state=state,
            request_questions=self.questions,
            response_raw=response,
            hunt=hunt_plan.to_dict() if hunt_plan is not None else None,
            target_choice=target_choice,
        )

    def _apply_target_choice(self, snapshot, hunt_plan, choice: str | None):
        """Let the model's ``target`` answer re-rank the hunt for this decision."""

        if hunt_plan is None or choice in (None, "advance"):
            return hunt_plan
        if choice == "exit":
            self.hunt_tracker.target_id = None
            return with_target(hunt_plan, None, snapshot)
        try:
            index = TARGET_CHOICES.index(choice)
        except ValueError:
            return hunt_plan
        if index >= len(hunt_plan.candidates):
            return hunt_plan
        monster = hunt_plan.candidates[index]
        self.hunt_tracker.target_id = monster.id
        return with_target(hunt_plan, monster, snapshot)

    def _world_model(self, snapshot: DuumSnapshot) -> dict | None:
        """Schematic playbook from ``map/``; None whenever it cannot be built."""

        if not self.use_world_model or self.prompt_version not in ("v3w",):
            return None
        if build_world_model is None:
            return None
        try:
            return build_world_model(snapshot)
        except Exception:  # pragma: no cover - the adapter is already fail-soft
            return None

    # -- deterministic assistance -------------------------------------------
    def _assist(self, snapshot: DuumSnapshot, proposed: DuumControls):
        if not self.assisted:
            return proposed, ()
        return apply_assistance(snapshot, proposed)
