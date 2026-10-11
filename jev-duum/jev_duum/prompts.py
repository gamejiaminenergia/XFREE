"""Versioned Jev requests: the state we send and the questions we ask.

``v1`` freezes the original one-line questions and the flattened text state so
a prompt change can be measured against it on identical snapshots.  ``v2``
follows https://docs.typesafe.ai/primitives/advanced: named JSON fields, numeric
bearings, facts computed in code, and rubric-shaped ``criteria``.

The model judges; it never does arithmetic that code can do.  Every comparison
that matters (which directions are safe, whether a shot reaches a target, how
far off axis the objective is) is precomputed here and quoted in the rubric.
"""

from __future__ import annotations

import math

from .observation import build_observations
from .snapshot import (
    DuumSnapshot,
    EnemySnapshot,
    EpisodeSnapshot,
    InteractionSnapshot,
    MovementOptionSnapshot,
    NavigationSnapshot,
    PickupSnapshot,
    PlayerSnapshot,
    ProjectileSnapshot,
)
from .types import (
    AIMS,
    INTERACTIONS,
    MOVEMENTS,
    ROUTE_AIM_TOLERANCE_RADIANS,
    ROUTE_FORWARD_TOLERANCE_RADIANS,
)

PROMPT_VERSIONS = ("v1", "v2", "v3", "v3w")
DEFAULT_PROMPT_VERSION = "v3w"

ROUTE_AIM_TOLERANCE_DEGREES = round(math.degrees(ROUTE_AIM_TOLERANCE_RADIANS), 2)
ROUTE_FORWARD_TOLERANCE_DEGREES = round(
    math.degrees(ROUTE_FORWARD_TOLERANCE_RADIANS), 2
)

V1_QUESTIONS = {
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

CONVENTIONS = {
    "bearing_degrees": "Degrees to turn: positive means LEFT, negative means RIGHT.",
    "shot_would_hit": "Computed by code: an unobstructed shot reaches that target now.",
    "safe": "false means geometry blocks that direction; hold is always safe.",
    "distance_units": "contact under 96, near 96-240, medium 240-560, far over 560.",
    "pickup_need": {
        "critical": "take now",
        "urgent": "worth a detour",
        "useful": "only if on the way",
    },
}

_SEE = "Read `conventions` for signs, safe flags and distances."

_MOVEMENT_INSTRUCTIONS = {
    "role": "Choose the movement a Doom player performs now.",
    "task": "Pick one movement for the next decision interval.",
    "rules": [
        "Never choose a movement whose `safe` flag is false.",
        "If an entry in `projectiles_inbound` has impact true, move in its `dodge` direction.",
        "A pickup with `need` critical or urgent outranks progress: move toward it when a safe direction exists, strafing when it lies to the side and holding to turn when it is far off axis.",
        "A `useful` pickup never changes the movement decision.",
        "Otherwise progress toward the objective: choose `forward` only when `forward.safe` is true and the absolute `objective.bearing_degrees` is at or below `objective.forward_tolerance_degrees`.",
        "When the objective is further off axis than that tolerance, choose `hold` and turn in place; do not strafe away toward a goal that is far off axis.",
        "When the objective is within the forward tolerance but `forward.safe` is false, choose the safer lateral strafe instead.",
        "An attacking threat at contact distance is a reason to `back` when `back.safe` is true.",
        "When `situation.stuck` is true, prefer any safe movement over repeating `hold`.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which movement should the player use now?",
}

_MOVEMENT_CRITERIA = {
    "forward": {
        "what": "Step forward.",
        "use_when": "`forward.safe` is true and the goal ahead is within its forward tolerance.",
        "not_for": "`forward.safe` is false, or the goal needs a turn in place first.",
    },
    "back": {
        "what": "Walk backwards.",
        "use_when": "a threat attacks at contact distance and `back.safe` is true.",
        "not_for": "no threat is in contact and the goal lies behind.",
    },
    "strafe_left": {
        "what": "Side-step left without turning.",
        "use_when": "`strafe_left.safe` is true and the reason is a projectile dodge, a needed pickup to the left, or a blocked forward with the objective nearly ahead.",
        "not_for": "`strafe_left.safe` is false, or the objective is more than its forward tolerance off axis to the right.",
    },
    "strafe_right": {
        "what": "Side-step right without turning.",
        "use_when": "`strafe_right.safe` is true and the reason is a projectile dodge, a needed pickup to the right, or a blocked forward with the objective nearly ahead.",
        "not_for": "`strafe_right.safe` is false, or the objective is more than its forward tolerance off axis to the left.",
    },
    "hold": {
        "what": "Stay in place.",
        "use_when": "the goal is more than `objective.forward_tolerance_degrees` off axis, or every goal-ward direction is unsafe.",
        "not_for": "an impacting projectile is inbound, or the goal is within the forward tolerance and forward is safe.",
    },
}

_AIM_INSTRUCTIONS = {
    "role": "Choose how far to turn now.",
    "task": "Point the weapon at the best threat, or at the objective when none is visible.",
    "rules": [
        "With ammunition above zero, the target is the visible threat with the smallest absolute `bearing_degrees` among those that are `attacking`, `active` or closer than 560 units.",
        "If the chosen target has `shot_would_hit` true, choose `straight`: the shot already reaches it.",
        "Otherwise turn toward the sign of its `bearing_degrees`: positive means `left`, negative means `right`.",
        "When no threat qualifies, or ammunition is zero, the target is the objective: apply the same sign rule to `objective.bearing_degrees` using `objective.aim_tolerance_degrees`.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which way should the player turn now?",
}

_AIM_CRITERIA = {
    "left": {
        "what": "Turn left.",
        "use_when": "the chosen target's `bearing_degrees` is positive and its `shot_would_hit` is false.",
        "not_for": "the target is already in the firing corridor, or it lies to the right.",
    },
    "straight": {
        "what": "Do not turn.",
        "use_when": "the chosen threat has `shot_would_hit` true, or the target is the objective and its absolute `bearing_degrees` is within `objective.aim_tolerance_degrees`.",
        "not_for": "the chosen target is off axis and the shot does not reach it.",
    },
    "right": {
        "what": "Turn right.",
        "use_when": "the chosen target's `bearing_degrees` is negative and its `shot_would_hit` is false.",
        "not_for": "the target is already in the firing corridor, or it lies to the left.",
    },
}

_INTERACTION_INSTRUCTIONS = {
    "role": "Choose the weapon or use action now.",
    "task": "Pick exactly one action: fire, use or neither.",
    "rules": [
        "`fire` needs `player.weapon_ready` true, `player.ammo` above zero and a threat with `shot_would_hit` true.",
        "`use` needs an unlocked entry in `usable_geometry`.",
        "Never fire at a threat whose `shot_would_hit` is false: the shot would miss.",
        "Otherwise choose `neither`.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which action should the player take now?",
}

_INTERACTION_CRITERIA = {
    "fire": {
        "what": "Shoot with the current weapon.",
        "use_when": "the weapon is ready, ammunition is above zero and a threat has `shot_would_hit` true.",
        "not_for": "the weapon is on cooldown, there is no ammunition, or no shot reaches a target.",
    },
    "use": {
        "what": "Open or activate the geometry ahead.",
        "use_when": "`usable_geometry` holds an entry whose `locked` is false.",
        "not_for": "no geometry is listed, or the entry is locked.",
    },
    "neither": {
        "what": "Take no weapon or use action.",
        "use_when": "no shot reaches a target and nothing usable is ahead.",
        "not_for": "a threat is in the firing corridor with a ready, loaded weapon.",
    },
}

V2_QUESTIONS = {
    "movement": {
        "type": "choice",
        "instructions": _MOVEMENT_INSTRUCTIONS,
        "criteria": _MOVEMENT_CRITERIA,
    },
    "aim": {
        "type": "choice",
        "instructions": _AIM_INSTRUCTIONS,
        "criteria": _AIM_CRITERIA,
    },
    "interaction": {
        "type": "choice",
        "instructions": _INTERACTION_INSTRUCTIONS,
        "criteria": _INTERACTION_CRITERIA,
    },
}

_MOVEMENT_V3_INSTRUCTIONS = {
    "role": "You execute a plan the code already made; your job is the tactical step.",
    "task": "Pick the movement that executes `strategy.plan` for this decision.",
    "rules": [
        "The mission and the plan are fixed data: execute them, do not replace them.",
        "Never choose a movement whose `safe` flag is false.",
        "`movement_options.<name>.progress` is how much that direction closes the distance to `strategy.guide_bearing_degrees`: 1 aims straight at it, 0 is sideways, negative walks away.",
        "If `strategy.must_move` is true, `hold` is forbidden: choose the safe option with the highest positive `progress`.",
        "If `strategy.must_move` is false, `hold` is allowed only when no safe direction makes progress or the plan is to use the geometry ahead.",
        "An entry in `projectiles_inbound` with `impact` true means dodge: move in its `dodge` direction when that direction is safe.",
        "Firing is a separate question; keep the player moving while it fights.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which movement executes the plan now?",
}

_MOVEMENT_V3_CRITERIA = {
    "forward": {
        "what": "Step forward along the current facing.",
        "use_when": "`forward.safe` is true and forward has the highest positive `progress`, or the objective is already within its aim tolerance.",
        "not_for": "`forward.safe` is false, or another safe direction has clearly more progress.",
    },
    "back": {
        "what": "Walk backwards.",
        "use_when": "a threat attacks at contact distance, `back.safe` is true and retreating is the plan (low health), or `back` has the highest positive progress toward a goal directly behind.",
        "not_for": "the objective is ahead; backing up then walks away from the mission.",
    },
    "strafe_left": {
        "what": "Side-step left while the aim keeps turning.",
        "use_when": "`strafe_left.safe` is true and it has the highest positive `progress`, or the plan is to dodge a projectile to the left.",
        "not_for": "`strafe_left.safe` is false, or its progress is zero and forward makes progress.",
    },
    "strafe_right": {
        "what": "Side-step right while the aim keeps turning.",
        "use_when": "`strafe_right.safe` is true and it has the highest positive `progress`, or the plan is to dodge a projectile to the right.",
        "not_for": "`strafe_right.safe` is false, or its progress is zero and forward makes progress.",
    },
    "hold": {
        "what": "Stand still for this decision.",
        "use_when": "`strategy.must_move` is false and either no safe direction makes progress or the plan is to use the geometry directly ahead.",
        "not_for": "`strategy.must_move` is true, a safe direction with positive `progress` exists, or an impacting projectile is inbound.",
    },
}

_AIM_V3_INSTRUCTIONS = {
    "role": "You execute the plan's targeting.",
    "task": "Point the weapon at `strategy.focus`; when the focus is the objective, aim the route.",
    "rules": [
        "`strategy.focus` is already the code's chosen target: enemies it ignores are scenery.",
        "If the focus is a threat with `shot_would_hit` true, choose `straight`: the shot already reaches it.",
        "If the focus is a threat without a shot, turn toward the sign of its `bearing_degrees`: positive means `left`, negative means `right`.",
        "If the focus is the objective or a pickup, apply the same sign rule using `objective.aim_tolerance_degrees`.",
        "Threats listed as `relevant` false never justify a turn.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which way should the player turn now?",
}

_AIM_V3_CRITERIA = {
    "left": {
        "what": "Turn left.",
        "use_when": "`strategy.focus` is to the left (`bearing_degrees` positive) and no shot reaches it yet.",
        "not_for": "the focus is already in the firing corridor, or it lies to the right.",
    },
    "straight": {
        "what": "Do not turn.",
        "use_when": "the focus threat has `shot_would_hit` true, or the focus is the objective and its absolute `bearing_degrees` is within `objective.aim_tolerance_degrees`.",
        "not_for": "the focus is off axis and the shot does not reach it yet.",
    },
    "right": {
        "what": "Turn right.",
        "use_when": "`strategy.focus` is to the right (`bearing_degrees` negative) and no shot reaches it yet.",
        "not_for": "the focus is already in the firing corridor, or it lies to the left.",
    },
}

_INTERACTION_V3_INSTRUCTIONS = {
    "role": "You execute the plan's rules of engagement.",
    "task": "Pick exactly one action: fire, use or neither.",
    "rules": [
        "`fire` whenever `player.weapon_ready` is true, `player.ammo` is above zero and some threat has `shot_would_hit` true.",
        "Ammunition is plentiful: do not hold fire to save bullets.",
        "`use` when `usable_geometry` lists an entry whose `locked` is false.",
        "Otherwise choose `neither`; never fire at a threat whose `shot_would_hit` is false.",
        "Firing does not pause movement; both questions answer the same decision.",
        _SEE + " Choose exactly one option; there is no abstention.",
    ],
    "question": "Which action should the player take now?",
}

_INTERACTION_V3_CRITERIA = {
    "fire": {
        "what": "Shoot with the current weapon.",
        "use_when": "the weapon is ready, ammunition is above zero and a threat has `shot_would_hit` true.",
        "not_for": "the weapon is on cooldown, there is no ammunition, or no shot reaches a target.",
    },
    "use": {
        "what": "Open or activate the geometry ahead.",
        "use_when": "`usable_geometry` holds an entry whose `locked` is false.",
        "not_for": "no geometry is listed, or the entry is locked.",
    },
    "neither": {
        "what": "Take no weapon or use action.",
        "use_when": "no shot reaches a target and nothing usable is ahead.",
        "not_for": "a threat is in the firing corridor with a ready, loaded weapon.",
    },
}

V3_QUESTIONS = {
    "movement": {
        "type": "choice",
        "instructions": _MOVEMENT_V3_INSTRUCTIONS,
        "criteria": _MOVEMENT_V3_CRITERIA,
    },
    "aim": {
        "type": "choice",
        "instructions": _AIM_V3_INSTRUCTIONS,
        "criteria": _AIM_V3_CRITERIA,
    },
    "interaction": {
        "type": "choice",
        "instructions": _INTERACTION_V3_INSTRUCTIONS,
        "criteria": _INTERACTION_V3_CRITERIA,
    },
}

_QUESTIONS = {"v1": V1_QUESTIONS, "v2": V2_QUESTIONS, "v3": V3_QUESTIONS}

# ── v3w: the v3 plan plus the schematic world model from `map/` ────────────

_WORLD_MODEL_NOTE = (
    "`state.world_model` is informative, not authoritative: it comes from a "
    "schematic map of the level and may be approximate. The visible state and "
    "the deterministic guard always win."
)

_WORLD_MODEL_RULES = {
    "movement": [
        _WORLD_MODEL_NOTE,
        "If `world_model.hazards.nukage` is true or `world_model.sector_risk.worst_risk` is above 0.5, leave the hazard: pick a safe direction with lower risk.",
        "`world_model.hidden_items.top_aspirations` lists pickups the snapshot cannot see; treat the top entry as a detour candidate when health is low.",
    ],
    "aim": [
        _WORLD_MODEL_NOTE,
        "`world_model.hidden_foes` counts enemies you cannot see; never turn for one that is not in `strategy.focus`.",
    ],
    "interaction": [_WORLD_MODEL_NOTE],
}


def _with_world_model(questions: dict) -> dict:
    expanded = {}
    for name, question in questions.items():
        instructions = dict(question["instructions"])
        instructions["rules"] = list(instructions["rules"]) + _WORLD_MODEL_RULES[name]
        expanded[name] = {**question, "instructions": instructions}
    return expanded


V3W_QUESTIONS = _with_world_model(V3_QUESTIONS)

_QUESTIONS["v3w"] = V3W_QUESTIONS
_EXPECTED_LABELS = {"movement": MOVEMENTS, "aim": AIMS, "interaction": INTERACTIONS}


def build_questions(version: str, *, reverse_order: bool = False) -> dict:
    """Return a fresh questions dict for ``version``.

    ``reverse_order`` flips the order of the ``criteria`` keys without changing
    their content; the offline harness uses it to detect position bias.
    """

    if version not in _QUESTIONS:
        raise ValueError(f"unknown prompt version: {version}")
    questions = {}
    for name, question in _QUESTIONS[version].items():
        criteria = list(question["criteria"].items())
        if reverse_order:
            criteria = list(reversed(criteria))
        questions[name] = {
            **question,
            "criteria": dict(criteria),
        }
    for name, question in questions.items():
        if set(question["criteria"]) != set(_EXPECTED_LABELS[name]):
            raise ValueError(
                f"prompt {version} question {name} has criteria "
                f"{sorted(question['criteria'])} != {sorted(_EXPECTED_LABELS[name])}"
            )
    return questions


def _degrees(radians: float) -> float:
    return round(math.degrees(radians), 1)


def _movement_options(
    snapshot: DuumSnapshot, progress: dict[str, float] | None = None
) -> dict:
    options = {
        option.name: {
            "safe": bool(option.safe),
            "clear_distance_units": round(float(option.clear_distance), 1),
        }
        for option in snapshot.movement_options
    }
    if progress:
        for name, value in options.items():
            value["progress"] = progress.get(name)
    options.setdefault(
        "hold",
        {
            "safe": True,
            "clear_distance_units": 0.0,
            "note": "standing still cannot collide",
            **({"progress": 0.0} if progress else {}),
        },
    )
    return options


def _threats(snapshot: DuumSnapshot, relevant_ids: tuple[int, ...] | None = None) -> list:
    return [
        {
            "id": enemy.id,
            "kind": enemy.category,
            "bearing_degrees": _degrees(enemy.bearing),
            "bearing_word": enemy.bearing_word,
            "distance_units": round(float(enemy.distance), 1),
            "distance_word": enemy.distance_word,
            "attacking": bool(enemy.attacking),
            "active": bool(enemy.active),
            "shot_would_hit": bool(enemy.aligned),
            "melee_reachable": bool(enemy.melee_reachable),
            "motion": enemy.motion,
            **(
                {"relevant": enemy.id in relevant_ids}
                if relevant_ids is not None
                else {}
            ),
        }
        for enemy in snapshot.visible_enemies
    ]


def _projectiles(snapshot: DuumSnapshot) -> list:
    return [
        {
            "bearing_degrees": _degrees(projectile.bearing),
            "distance_units": round(float(projectile.distance), 1),
            "impact": bool(projectile.impact),
            "impact_in_seconds": round(float(projectile.impact_time), 2),
            "dodge": projectile.dodge,
        }
        for projectile in snapshot.incoming_projectiles
    ]


def _pickups(snapshot: DuumSnapshot) -> list:
    return [
        {
            "category": pickup.category,
            "bearing_degrees": _degrees(pickup.bearing),
            "distance_units": round(float(pickup.distance), 1),
            "need": pickup.need,
        }
        for pickup in snapshot.visible_pickups
    ]


def _geometry(snapshot: DuumSnapshot) -> list:
    return [
        {
            "kind": interaction.kind,
            "distance_units": round(float(interaction.distance), 1),
            "locked": bool(interaction.locked),
            "required_key": interaction.required_key,
        }
        for interaction in snapshot.nearby_interactions
    ]


def _objective(snapshot: DuumSnapshot) -> dict | None:
    route = snapshot.navigation
    if route is None:
        return None
    return {
        "kind": route.objective,
        "bearing_degrees": _degrees(route.bearing),
        "bearing_word": route.bearing_word,
        "distance_units": round(float(route.distance), 1),
        "route_length": int(route.route_length),
        "reachable": bool(route.reachable),
        "use_when_near": bool(route.use_when_near),
        "aim_tolerance_degrees": ROUTE_AIM_TOLERANCE_DEGREES,
        "forward_tolerance_degrees": ROUTE_FORWARD_TOLERANCE_DEGREES,
    }


def _structured_state(snapshot: DuumSnapshot, strategy=None) -> dict:
    player = snapshot.player
    episode = snapshot.episode
    if isinstance(strategy, dict):
        # A recorded strategy block can be replayed verbatim.
        block = strategy
        relevant_ids = tuple(strategy.get("relevant_threat_ids") or ())
        progress = strategy.get("progress") or None
    elif strategy is not None:
        block = strategy.to_dict()
        relevant_ids = strategy.relevant_threat_ids
        progress = strategy.progress
    else:
        block = None
        relevant_ids = None
        progress = None
    state = {
        "tick": snapshot.tick,
        "map": snapshot.map_name,
        "conventions": CONVENTIONS,
        "player": {
            "health": int(player.health),
            "armor": int(player.armor),
            "weapon": player.weapon_name,
            "ammo": int(player.ammo),
            "weapon_ready": bool(player.weapon_ready),
            "keys": int(player.keys),
        },
        "objective": _objective(snapshot),
        "threats": _threats(snapshot, relevant_ids),
        "projectiles_inbound": _projectiles(snapshot),
        "pickups": _pickups(snapshot),
        "usable_geometry": _geometry(snapshot),
        "movement_options": _movement_options(snapshot, progress),
        "situation": {
            "stuck": bool(episode.stuck_ticks >= 24),
            "game_time": round(float(episode.game_time), 1),
            "damage_received": int(episode.damage_received),
            "kills": int(episode.kills),
            "items": int(episode.items),
            "unique_sectors": int(episode.unique_sectors),
            "live_enemies": int(episode.live_enemies),
            "omitted_enemies": int(snapshot.omitted_enemies),
            "dead": bool(episode.dead),
            "finished": bool(episode.finished),
        },
    }
    if block is not None:
        state["strategy"] = block
    return state


def _legacy_state(snapshot: DuumSnapshot) -> tuple[dict, dict[str, str]]:
    candidates = build_observations(snapshot)
    observations = {
        name: getattr(candidates, name)[0][1]
        for name in ("movement", "aim", "interaction")
    }
    state = {
        "tick": candidates.tick,
        "map": snapshot.map_name,
        "movement": observations["movement"],
        "aim": observations["aim"],
        "interaction": observations["interaction"],
    }
    return state, observations


def build_state(
    snapshot: DuumSnapshot, version: str, strategy=None, world_model: dict | None = None
) -> tuple[dict, dict[str, str]]:
    """Return ``(state, observations)`` for one snapshot and prompt version.

    ``observations`` stays the short human summary the Tk panel already renders,
    independent of the version.  ``state`` is what actually travels to Jev.
    """

    if version not in PROMPT_VERSIONS:
        raise ValueError(f"unknown prompt version: {version}")
    legacy_state, observations = _legacy_state(snapshot)
    if version == "v1":
        return legacy_state, observations
    if version == "v2":
        return _structured_state(snapshot), observations
    if strategy is None:
        raise ValueError(f"prompt {version} needs a strategy")
    state = _structured_state(snapshot, strategy)
    if version == "v3w":
        # Fail-soft: the adapter may return None and the prompt still works.
        state["world_model"] = world_model
    return state, observations


def snapshot_from_dict(payload: dict) -> DuumSnapshot:
    """Rebuild a snapshot from ``DuumSnapshot.to_dict()`` output.

    The offline prompt harness stores snapshots once and derives the state for
    every prompt version from them, so it needs to reconstruct the dataclasses.
    """

    navigation = payload.get("navigation")
    return DuumSnapshot(
        tick=int(payload["tick"]),
        map_name=str(payload["map_name"]),
        rng=int(payload["rng"]),
        player=PlayerSnapshot(**payload["player"]),
        visible_enemies=tuple(
            EnemySnapshot(**enemy) for enemy in payload["visible_enemies"]
        ),
        incoming_projectiles=tuple(
            ProjectileSnapshot(**projectile)
            for projectile in payload["incoming_projectiles"]
        ),
        visible_pickups=tuple(
            PickupSnapshot(**pickup) for pickup in payload["visible_pickups"]
        ),
        nearby_interactions=tuple(
            InteractionSnapshot(**interaction)
            for interaction in payload["nearby_interactions"]
        ),
        movement_options=tuple(
            MovementOptionSnapshot(**option) for option in payload["movement_options"]
        ),
        navigation=NavigationSnapshot(**navigation) if navigation else None,
        omitted_enemies=int(payload["omitted_enemies"]),
        episode=EpisodeSnapshot(**payload["episode"]),
    )
