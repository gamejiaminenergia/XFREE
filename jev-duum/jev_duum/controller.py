"""Three factorized Jev decisions over one semantic Duum snapshot.

Jev is a System One model: one ``state`` per request, answered with typed values
and probabilities. The adapter therefore assembles a single named-field state
from the canonical snapshot and asks the three Duum choices in that same
request. The deterministic assistance layer is model-agnostic and unchanged
from the Laya adapter; it only sees the argmax controls.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import asdict, dataclass, replace

from .jev_client import DEFAULT_MODEL, JevClient, input_cost_usd
from .observation import build_observations
from .snapshot import DuumSnapshot
from .types import AIMS, INTERACTIONS, MOVEMENTS, DuumControls

# English instructions: the provider states English is where accuracy is best.
QUESTIONS = {
    "movement": {
        "type": "choice",
        "instructions": "Choose the safest useful immediate movement.",
        "criteria": {
            "forward": "advance",
            "back": "retreat",
            "strafe_left": "dodge left",
            "strafe_right": "dodge right",
            "hold": "stay",
        },
    },
    "aim": {
        "type": "choice",
        "instructions": "Turn toward the best visible target.",
        "criteria": {"left": "turn left", "straight": "keep aim", "right": "turn right"},
    },
    "interaction": {
        "type": "choice",
        "instructions": "Choose the useful immediate action.",
        "criteria": {"fire": "shoot", "use": "open or activate", "neither": "wait"},
    },
}

DEFINITIONS = (
    ("movement", MOVEMENTS),
    ("aim", AIMS),
    ("interaction", INTERACTIONS),
)


@dataclass(frozen=True, slots=True)
class AssistanceEvent:
    kind: str
    reason: str
    proposed: str
    applied: str


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


class JevDuumController:
    """Turn one canonical snapshot into one Jev request and three controls."""

    def __init__(
        self,
        model: str | None = None,
        *,
        client: JevClient | None = None,
        assisted: bool = False,
        api_key: str | None = None,
        endpoint: str | None = None,
    ):
        self.assisted = bool(assisted)
        self.model = model or os.environ.get("TYPESAFE_MODEL") or DEFAULT_MODEL
        if client is None:
            client = JevClient(api_key=api_key, model=self.model, endpoint=endpoint)
        self.client = client
        self.metadata = {
            "name": "jev",
            "engine": "typesafe-systemone",
            "hardware": "remote",
            "network": "online",
            "model_source": "typesafe api",
            "model_id": self.model,
            "endpoint": getattr(client, "endpoint", None),
            "policy": "One Jev request with three choices over semantic Duum snapshots; "
            "pixels are never model input",
        }

    # -- observations --------------------------------------------------------
    def combined_state(self, snapshot: DuumSnapshot) -> tuple[dict, dict[str, str]]:
        """Compose the fullest per-question reductions into one named-field state."""

        candidates = build_observations(snapshot)
        observations = {name: getattr(candidates, name)[0][1] for name, _ in DEFINITIONS}
        state = {
            "tick": candidates.tick,
            "map": snapshot.map_name,
            "movement": observations["movement"],
            "aim": observations["aim"],
            "interaction": observations["interaction"],
        }
        return state, observations

    # -- decision ------------------------------------------------------------
    def decide(self, snapshot: DuumSnapshot) -> DecisionResult:
        started = time.perf_counter()
        state, observations = self.combined_state(snapshot)
        request_started = time.perf_counter()
        response = self.client.ask(state, QUESTIONS)
        request_ms = (time.perf_counter() - request_started) * 1000

        try:
            answers = response["answers"]
        except (KeyError, TypeError) as error:
            raise ValueError("Jev returned no answers") from error

        probabilities: dict[str, dict[str, float]] = {}
        confidence: dict[str, float | None] = {}
        for name, labels in DEFINITIONS:
            try:
                answer = answers[name]
            except (KeyError, TypeError) as error:
                raise ValueError(f"Jev returned no {name} answer") from error
            probabilities[name] = _probabilities(answer, labels, name)
            confidence[name] = _confidence(answer, name)

        usage = response.get("usage") or {}
        try:
            tokens = int(usage.get("input_tokens") or 0)
        except (TypeError, ValueError):
            tokens = 0
        model_id = str(response.get("model") or self.model)

        proposed = DuumControls(
            movement=max(MOVEMENTS, key=probabilities["movement"].__getitem__),
            aim=max(AIMS, key=probabilities["aim"].__getitem__),
            interaction=max(INTERACTIONS, key=probabilities["interaction"].__getitem__),
        )
        applied, events = self._assist(snapshot, proposed)
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
        )

    # -- deterministic assistance (unchanged from the Laya adapter) ----------
    def _assist(self, snapshot: DuumSnapshot, proposed: DuumControls):
        if not self.assisted:
            return proposed, ()
        applied = proposed
        events = []
        options = {option.name: option for option in snapshot.movement_options}
        projectile = next(
            (item for item in snapshot.incoming_projectiles if item.impact), None
        )
        if projectile and applied.movement != projectile.dodge:
            events.append(
                AssistanceEvent(
                    "projectile-dodge",
                    f"predicted impact in {projectile.impact_time:.2f}s",
                    applied.movement,
                    projectile.dodge,
                )
            )
            applied = replace(applied, movement=projectile.dodge)
        selected = options.get(applied.movement)
        if selected is not None and not selected.safe:
            alternatives = [option for option in options.values() if option.safe]
            if alternatives:
                replacement = max(
                    alternatives, key=lambda option: (option.clear_distance, option.name)
                ).name
            else:
                crawl = max(
                    options.values(),
                    key=lambda option: (option.clear_distance, option.name),
                    default=None,
                )
                replacement = (
                    crawl.name if crawl is not None and crawl.clear_distance > 0 else "hold"
                )
            events.append(
                AssistanceEvent(
                    "blocked-movement",
                    f"{applied.movement} has only {selected.clear_distance:.0f} clear units",
                    applied.movement,
                    replacement,
                )
            )
            applied = replace(applied, movement=replacement)
        if snapshot.player.weapon_name == "fist":
            combat_enemies = tuple(
                enemy
                for enemy in snapshot.visible_enemies
                if enemy.melee_reachable
                and (
                    enemy.attacking
                    or (enemy.active and enemy.distance < 160)
                    or enemy.distance < 64
                )
            )
        else:
            combat_enemies = (
                tuple(
                    enemy
                    for enemy in snapshot.visible_enemies
                    if enemy.active or enemy.attacking or enemy.distance < 560
                )
                if snapshot.player.ammo > 0
                else ()
            )
        target = min(
            combat_enemies,
            key=lambda enemy: (abs(enemy.bearing), enemy.distance, enemy.id),
            default=None,
        )
        route = snapshot.navigation
        near_exit = (
            route is not None
            and route.reachable
            and route.objective == "exit"
            and route.route_length <= 7
        )
        urgent_pickup = next(
            (
                pickup
                for pickup in snapshot.visible_pickups
                if pickup.need in ("critical", "urgent")
            ),
            None,
        )
        if (
            near_exit
            and urgent_pickup is not None
            and urgent_pickup.need != "critical"
            and snapshot.player.health >= 25
        ):
            urgent_pickup = None
        if urgent_pickup is not None and urgent_pickup.need == "critical":
            target = None
        if (
            target is not None
            and snapshot.player.health < 50
            and applied.movement in ("forward", "hold")
        ):
            evasive = [
                options[name]
                for name in ("strafe_left", "strafe_right")
                if options.get(name) is not None and options[name].safe
            ]
            if evasive:
                replacement = max(
                    evasive, key=lambda option: option.clear_distance
                ).name
                events.append(
                    AssistanceEvent(
                        "combat-evasion",
                        "low health while an enemy has line of sight",
                        applied.movement,
                        replacement,
                    )
                )
                applied = replace(applied, movement=replacement)
        if target is not None:
            desired_aim = (
                "straight"
                if target.aligned
                else "left"
                if target.bearing > 0
                else "right"
            )
            aim_reason = f"visible target is {target.bearing_word}"
        elif urgent_pickup is not None:
            desired_aim = (
                "straight"
                if abs(urgent_pickup.bearing) <= 0.04
                else "left"
                if urgent_pickup.bearing > 0
                else "right"
            )
            aim_reason = (
                f"{urgent_pickup.need} {urgent_pickup.category} pickup is "
                f"{urgent_pickup.bearing_word}"
            )
        elif route is not None and route.reachable:
            desired_aim = (
                "straight"
                if abs(route.bearing) <= 0.04
                else "left"
                if route.bearing > 0
                else "right"
            )
            aim_reason = f"{route.objective.replace('-', ' ')} route is {route.bearing_word}"
        else:
            desired_aim = applied.aim
            aim_reason = "no target or route"
        if applied.aim != desired_aim:
            events.append(
                AssistanceEvent("aim-guidance", aim_reason, applied.aim, desired_aim)
            )
            applied = replace(applied, aim=desired_aim)

        if (
            projectile is None
            and target is None
            and (urgent_pickup is not None or (route is not None and route.reachable))
        ):
            guide_bearing = (
                urgent_pickup.bearing if urgent_pickup is not None else route.bearing
            )
            guide_name = (
                f"{urgent_pickup.need} {urgent_pickup.category}"
                if urgent_pickup is not None
                else f"{route.objective.replace('-', ' ')} route"
            )
            preferred = "hold" if abs(guide_bearing) > 0.08 else "forward"
            # `hold` intentionally has no MovementOptionSnapshot because it
            # cannot collide.  Do not mistake that absence for a blocked
            # movement and replace a turn-in-place with back/strafe.  At a
            # lift threshold that fallback can pull the player back onto the
            # platform just after they have stepped off it.
            if preferred != "hold" and (
                not options.get(preferred) or not options[preferred].safe
            ):
                lateral = [
                    options[name]
                    for name in ("strafe_left", "strafe_right")
                    if options.get(name) is not None and options[name].safe
                ]
                preferred = (
                    max(lateral, key=lambda option: option.clear_distance).name
                    if preferred == "forward" and lateral
                    else "hold"
                )
                if preferred == "hold":
                    crawl = max(
                        options.values(),
                        key=lambda option: option.clear_distance,
                        default=None,
                    )
                    if crawl is not None and crawl.clear_distance > 0:
                        preferred = crawl.name
            if applied.movement != preferred:
                events.append(
                    AssistanceEvent(
                        "navigation-progress",
                        f"{guide_name} is "
                        f"{urgent_pickup.bearing_word if urgent_pickup else route.bearing_word}",
                        applied.movement,
                        preferred,
                    )
                )
                applied = replace(applied, movement=preferred)

        interaction = (
            snapshot.nearby_interactions[0] if snapshot.nearby_interactions else None
        )
        if interaction is not None and not interaction.locked and (
            target is None or not target.aligned
        ):
            if applied.interaction != "use":
                events.append(
                    AssistanceEvent(
                        "navigation-use",
                        f"usable {interaction.kind} is directly ahead",
                        applied.interaction,
                        "use",
                    )
                )
                applied = replace(applied, interaction="use")
        elif applied.interaction == "fire" and (target is None or not target.aligned):
            events.append(
                AssistanceEvent(
                    "fire-alignment",
                    "no target intersects the firing corridor",
                    "fire",
                    "neither",
                )
            )
            applied = replace(applied, interaction="neither")
        if (
            snapshot.player.weapon_name == "rockets"
            and proposed.interaction == "fire"
            and target is not None
            and target.distance < 160
        ):
            events.append(
                AssistanceEvent(
                    "rocket-self-damage",
                    "aligned target is inside the close explosive radius",
                    applied.interaction,
                    "neither",
                )
            )
            applied = replace(applied, interaction="neither")
        return applied, tuple(events)
