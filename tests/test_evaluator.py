from __future__ import annotations

import copy
import functools
import http.server
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from web3dgamebench import evaluator as host_evaluator
from web3dgamebench.config import load_task
from web3dgamebench.runtime_contracts import RuntimeContractError, load_runtime_contract

ROOT = Path(__file__).resolve().parents[1]
TASK_IDS = (
    "signal-drift",
    "canyon-strike",
    "bombsite-retake",
    "first-night",
    "village-quest",
    "ashen-duel",
    "linked-chamber",
    "star-course",
    "turbo-circuit",
    "frontier-command",
    "dinner-rush",
)

SPEC = importlib.util.spec_from_file_location(
    "web3dgamebench_container_evaluator", ROOT / "infra/evaluator/evaluate.py"
)
assert SPEC and SPEC.loader
container_evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(container_evaluator)


def _contract(task_id: str) -> dict:
    task = load_task(ROOT, task_id)
    viewports = {
        label: {"width": viewport.width, "height": viewport.height}
        for label, viewport in task.viewports.items()
    }
    return load_runtime_contract(
        ROOT, task_id=task.id, seed=task.seed, viewports=viewports
    ).data


VALID_STATES = {
    "signal-drift": {
        "phase": "ready",
        "score": 0,
        "player": {"x": 0, "y": 1, "z": 0},
        "relaysRestored": 0,
        "charge": 100,
        "seed": 94721,
        "restartCount": 0,
    },
    "canyon-strike": {
        "phase": "ready",
        "score": 0,
        "player": {"x": 0, "y": 10, "z": 0},
        "health": 100,
        "missiles": 4,
        "targetsDestroyed": 0,
        "targetsTotal": 5,
        "extracted": False,
        "missionSecondsRemaining": 300,
        "seed": 19031,
        "restartCount": 0,
    },
    "bombsite-retake": {
        "phase": "ready",
        "score": 0,
        "player": {"x": 0, "y": 1, "z": 0},
        "health": 100,
        "ammo": 30,
        "reserveAmmo": 90,
        "enemiesAlive": 2,
        "bombSecondsRemaining": 45,
        "defuseProgress": 0,
        "defuseStartedAfterClear": False,
        "seed": 28417,
        "restartCount": 0,
    },
    "first-night": {
        "phase": "ready",
        "score": 0,
        "player": {"x": 0, "y": 2, "z": 0},
        "health": 100,
        "timeOfDay": 0,
        "inventory": {"wood": 0, "stone": 0, "crystal": 0},
        "selectedSlot": 0,
        "blocksBroken": 0,
        "blocksPlaced": 0,
        "beaconCrafted": False,
        "beaconPlaced": False,
        "shelterValid": False,
        "shelterCellCount": 0,
        "dawnReached": False,
        "hostilesAlive": 2,
        "seed": 37199,
        "restartCount": 0,
    },
    "village-quest": {
        "phase": "ready",
        "score": 0,
        "player": {"x": 0, "y": 1, "z": 0},
        "health": 100,
        "resource": 100,
        "questStage": "available",
        "enemiesDefeated": 0,
        "enemyRolesDefeated": 0,
        "defensiveAbilityUses": 0,
        "relicCollected": False,
        "targetId": None,
        "seed": 46349,
        "restartCount": 0,
    },
    "ashen-duel": {
        "phase": "ready",
        "score": 0,
        "player": {"x": 0, "y": 1, "z": 0},
        "health": 100,
        "stamina": 100,
        "healsRemaining": 3,
        "bossHealth": 100,
        "bossPhase": 1,
        "bossPhaseReached": 1,
        "lockedOn": False,
        "seed": 55213,
        "restartCount": 0,
    },
    "linked-chamber": {
        "phase": "ready",
        "score": 0,
        "player": {"x": 0, "y": 1, "z": 0},
        "bluePortalPlaced": False,
        "amberPortalPlaced": False,
        "portalTraversals": 0,
        "cubePortalTraversals": 0,
        "cubeHeld": False,
        "cubeOnSwitch": False,
        "doorOpen": False,
        "seed": 64891,
        "restartCount": 0,
    },
    "star-course": {
        "phase": "ready",
        "score": 0,
        "player": {"x": 0, "y": 1, "z": 0},
        "coinsCollected": 0,
        "coinsTotal": 12,
        "lives": 3,
        "checkpoint": 0,
        "enemiesDefeated": 0,
        "movingPlatformTransfers": 0,
        "starUnlocked": False,
        "seed": 73693,
        "restartCount": 0,
    },
    "turbo-circuit": {
        "phase": "countdown",
        "score": 0,
        "player": {"x": 0, "y": 1, "z": 0},
        "lap": 1,
        "checkpoint": 0,
        "rank": 4,
        "speed": 0,
        "driftCharge": 0,
        "driftBoostsEarned": 0,
        "heldItem": None,
        "boostItemsUsed": 0,
        "slowFieldsUsed": 0,
        "finishCrossed": False,
        "raceSeconds": 0,
        "seed": 82939,
        "restartCount": 0,
    },
    "frontier-command": {
        "phase": "ready",
        "score": 0,
        "camera": {"x": 0, "y": 20, "z": 0},
        "wood": 100,
        "ore": 0,
        "selectedUnits": 0,
        "workersAlive": 3,
        "soldiersAlive": 0,
        "soldiersTrained": 0,
        "barracksBuilt": False,
        "raidResolved": False,
        "playerKeepHealth": 100,
        "enemyKeepHealth": 100,
        "seed": 91373,
        "restartCount": 0,
    },
    "dinner-rush": {
        "phase": "ready",
        "score": 0,
        "activeChef": 0,
        "chefs": [
            {"x": 0, "y": 1, "z": 0, "carrying": None},
            {"x": 2, "y": 1, "z": 0, "carrying": "plate"},
        ],
        "serviceSecondsRemaining": 240,
        "ordersDelivered": 0,
        "chef0AcceptedContributions": 0,
        "chef1AcceptedContributions": 0,
        "activeOrders": 1,
        "dirtyPlates": 0,
        "burnedItems": 0,
        "combo": 0,
        "seed": 104729,
        "restartCount": 0,
    },
}


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_each_runtime_contract_accepts_valid_and_rejects_invalid_state(task_id: str) -> None:
    contract = _contract(task_id)
    valid = copy.deepcopy(VALID_STATES[task_id])
    assert container_evaluator.valid_state(valid, contract)

    invalid = copy.deepcopy(valid)
    invalid["seed"] += 1
    assert not container_evaluator.valid_state(invalid, contract)


def test_turbo_countdown_and_non_player_task_shapes_are_valid() -> None:
    assert container_evaluator.valid_state(
        VALID_STATES["turbo-circuit"], _contract("turbo-circuit")
    )
    assert "player" not in VALID_STATES["frontier-command"]
    assert container_evaluator.valid_state(
        VALID_STATES["frontier-command"], _contract("frontier-command")
    )
    assert "player" not in VALID_STATES["dinner-rush"]
    assert container_evaluator.valid_state(
        VALID_STATES["dinner-rush"], _contract("dinner-rush")
    )


def test_runtime_contract_rejects_bool_nan_nested_and_invariant_violations() -> None:
    frontier = copy.deepcopy(VALID_STATES["frontier-command"])
    frontier["wood"] = True
    assert not container_evaluator.valid_state(frontier, _contract("frontier-command"))

    dinner = copy.deepcopy(VALID_STATES["dinner-rush"])
    dinner["chefs"][1]["x"] = float("nan")
    assert not container_evaluator.valid_state(dinner, _contract("dinner-rush"))

    first_night = copy.deepcopy(VALID_STATES["first-night"])
    first_night.update(
        phase="won",
        beaconCrafted=True,
        beaconPlaced=True,
        shelterValid=True,
        shelterCellCount=1,
        dawnReached=True,
    )
    assert not container_evaluator.valid_state(first_night, _contract("first-night"))

    linked = copy.deepcopy(VALID_STATES["linked-chamber"])
    linked.update(phase="won", doorOpen=True, portalTraversals=1, cubeOnSwitch=True)
    assert not container_evaluator.valid_state(linked, _contract("linked-chamber"))

    bombsite = copy.deepcopy(VALID_STATES["bombsite-retake"])
    bombsite.update(enemiesAlive=1, defuseProgress=0.1)
    assert not container_evaluator.valid_state(
        bombsite, _contract("bombsite-retake")
    )


@pytest.mark.parametrize(
    ("task_id", "winning_values", "missing_fact", "invalid_value"),
    (
        (
            "first-night",
            {
                "phase": "won",
                "beaconCrafted": True,
                "beaconPlaced": True,
                "shelterValid": True,
                "shelterCellCount": 2,
                "dawnReached": True,
            },
            "dawnReached",
            False,
        ),
        (
            "frontier-command",
            {
                "phase": "won",
                "enemyKeepHealth": 0,
                "soldiersTrained": 3,
                "barracksBuilt": True,
                "raidResolved": True,
            },
            "soldiersTrained",
            2,
        ),
        (
            "ashen-duel",
            {
                "phase": "won",
                "bossHealth": 0,
                "bossPhase": 2,
                "bossPhaseReached": 2,
            },
            "bossPhaseReached",
            1,
        ),
        (
            "turbo-circuit",
            {
                "phase": "won",
                "lap": 3,
                "rank": 1,
                "driftBoostsEarned": 1,
                "boostItemsUsed": 1,
                "slowFieldsUsed": 1,
                "finishCrossed": True,
            },
            "finishCrossed",
            False,
        ),
        (
            "star-course",
            {
                "phase": "won",
                "coinsCollected": 8,
                "starUnlocked": True,
                "enemiesDefeated": 1,
                "movingPlatformTransfers": 1,
            },
            "enemiesDefeated",
            0,
        ),
        (
            "star-course",
            {
                "phase": "won",
                "coinsCollected": 8,
                "starUnlocked": True,
                "enemiesDefeated": 1,
                "movingPlatformTransfers": 1,
            },
            "movingPlatformTransfers",
            0,
        ),
        (
            "village-quest",
            {
                "phase": "won",
                "questStage": "complete",
                "enemiesDefeated": 3,
                "enemyRolesDefeated": 2,
                "defensiveAbilityUses": 1,
                "relicCollected": True,
            },
            "defensiveAbilityUses",
            0,
        ),
        (
            "bombsite-retake",
            {
                "phase": "won",
                "enemiesAlive": 0,
                "defuseProgress": 1,
                "defuseStartedAfterClear": True,
            },
            "defuseStartedAfterClear",
            False,
        ),
        (
            "dinner-rush",
            {
                "phase": "won",
                "ordersDelivered": 5,
                "chef0AcceptedContributions": 1,
                "chef1AcceptedContributions": 1,
            },
            "chef1AcceptedContributions",
            0,
        ),
    ),
)
def test_completion_invariants_require_observable_goal_facts(
    task_id: str,
    winning_values: dict[str, object],
    missing_fact: str,
    invalid_value: object,
) -> None:
    state = copy.deepcopy(VALID_STATES[task_id])
    state.update(winning_values)
    contract = _contract(task_id)
    assert container_evaluator.valid_state(state, contract)

    state[missing_fact] = invalid_value
    assert not container_evaluator.valid_state(state, contract)


def test_input_gate_only_observes_declared_control_paths() -> None:
    before = copy.deepcopy(VALID_STATES["signal-drift"])
    timer_only = copy.deepcopy(before)
    timer_only["score"] = 10
    timer_only["charge"] = 90
    assert not container_evaluator.observation_changed(before, timer_only, ["player"])

    moved = copy.deepcopy(timer_only)
    moved["player"]["x"] = 1
    assert container_evaluator.observation_changed(before, moved, ["player"])


def test_probe_recipes_separate_platform_inputs_and_declare_idle_baselines() -> None:
    for task_id in TASK_IDS:
        contract = _contract(task_id)
        probes = contract["probes"]
        desktop_types = {recipe["input"]["type"] for recipe in probes["desktop"]}
        phone_types = {recipe["input"]["type"] for recipe in probes["phone"]}
        assert "keyboard" in desktop_types
        assert desktop_types <= {"keyboard", "pointer"}
        assert phone_types == {"touch"}
        assert all(
            recipe["baseline_ms"] >= 100
            for recipes in probes.values()
            for recipe in recipes
        )
        if task_id != "signal-drift":
            assert contract["restart"]["desktop_method"] == "keyboard"

    for task_id in ("bombsite-retake", "first-night", "linked-chamber"):
        gestures = {
            recipe["input"].get("gesture")
            for recipe in _contract(task_id)["probes"]["desktop"]
        }
        assert "lock-move" in gestures
    frontier_gestures = {
        recipe["input"].get("gesture")
        for recipe in _contract("frontier-command")["probes"]["desktop"]
    }
    assert "drag" in frontier_gestures

    assert {
        tuple(keys)
        for task_id in TASK_IDS
        for recipe in _contract(task_id)["probes"]["desktop"]
        if recipe["input"]["type"] == "keyboard" and task_id != "signal-drift"
        for keys in recipe["input"]["key_alternatives"]
    } == {("KeyW",), ("ArrowUp",), ("ArrowLeft",), ("KeyA",)}
    assert {
        recipe["input"]["type"]
        for recipe in _contract("canyon-strike")["probes"]["desktop"]
    } == {"keyboard"}


def test_probe_delta_must_exceed_idle_motion() -> None:
    observation = {"minimum_delta": 0.1, "baseline_multiplier": 1.5}
    assert not container_evaluator.probe_delta_passes(5.0, 5.0, observation)
    assert not container_evaluator.probe_delta_passes(0.0, 0.09, observation)
    assert container_evaluator.probe_delta_passes(1.0, 1.6, observation)
    assert not container_evaluator.probe_residual_passes(5.0, 0.0, observation)
    assert container_evaluator.probe_residual_passes(1.0, 0.6, observation)


def test_keyboard_probe_tries_published_alternatives_individually(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted: list[list[str]] = []

    def probe_once(_context, _page, _contract, recipe, _viewport):
        keys = recipe["input"]["keys"]
        attempted.append(keys)
        return keys == ["ArrowUp"], {"input": {"keys": keys}}

    monkeypatch.setattr(container_evaluator, "_run_probe_once", probe_once)
    passed, detail = container_evaluator._run_probe(
        None,
        None,
        {},
        {
            "input": {
                "type": "keyboard",
                "key_alternatives": [["KeyW"], ["ArrowUp"]],
                "duration_ms": 600,
            }
        },
        {},
    )

    assert passed is True
    assert attempted == [["KeyW"], ["ArrowUp"]]
    assert detail["matchedKeys"] == ["ArrowUp"]


def test_state_input_residual_removes_constant_automatic_motion() -> None:
    assert container_evaluator._state_input_residual(0.0, 5.0, 10.0) == 0
    assert container_evaluator._state_input_residual(0.0, 5.0, 4.0) == 6


def test_wait_until_playable_uses_declared_probe_phases() -> None:
    class FakePage:
        def __init__(self) -> None:
            self.states = iter(
                ({"phase": "countdown"}, {"phase": "countdown"}, {"phase": "armed"})
            )
            self.current = {"phase": "countdown"}

        def evaluate(self, _expression: str) -> dict[str, str]:
            self.current = next(self.states, self.current)
            return self.current

        def wait_for_timeout(self, _milliseconds: int) -> None:
            return None

    result = container_evaluator._wait_until_playable(
        FakePage(),
        {
            "state_global": "__WEB3DGAMEBENCH__",
            "started_phases": ["playing"],
            "probe_phases": ["armed"],
        },
    )
    assert result == {"phase": "armed"}


def test_restart_checks_declared_core_state_resets() -> None:
    contract = _contract("signal-drift")
    initial = copy.deepcopy(VALID_STATES["signal-drift"])
    restarted = copy.deepcopy(initial)
    restarted.update(phase="playing", restartCount=1, charge=99)
    restarted["player"].update(x=1, z=20)
    assert not container_evaluator._restart_state_errors(initial, restarted, contract)

    restarted["relaysRestored"] = 1
    restarted["player"]["x"] = 10
    errors = container_evaluator._restart_state_errors(initial, restarted, contract)
    assert any("relaysRestored" in error for error in errors)
    assert any("player.x" in error for error in errors)


def test_restart_count_must_increment_exactly_once() -> None:
    assert container_evaluator._restart_count_valid(3, 4, required=True)
    assert not container_evaluator._restart_count_valid(3, 5, required=True)
    assert not container_evaluator._restart_count_valid(3, True, required=True)


def test_phone_restart_requires_a_visible_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Keyboard:
        def __init__(self) -> None:
            self.presses: list[str] = []

        def press(self, key: str) -> None:
            self.presses.append(key)

    page = SimpleNamespace(
        keyboard=Keyboard(),
        restart_count=0,
        wait_for_timeout=lambda _milliseconds: None,
    )
    monkeypatch.setattr(container_evaluator, "_simulate_visibility_pause", lambda _page: None)
    monkeypatch.setattr(
        container_evaluator,
        "_visible_controls",
        lambda _page: [
            {
                "x": 10,
                "y": 20,
                "width": 40,
                "height": 20,
                "accessibleLabel": "Restart",
            }
        ],
    )
    monkeypatch.setattr(
        container_evaluator,
        "_activate_point",
        lambda target, _x, _y, *, mobile: setattr(target, "restart_count", 1),
    )
    monkeypatch.setattr(
        container_evaluator,
        "_state",
        lambda target, _contract: {"restartCount": target.restart_count},
    )

    result = container_evaluator._restart(
        page,
        {"restart": {"fallback": "none"}},
        0,
        mobile=True,
    )

    assert page.keyboard.presses == []
    assert result["method"] == "discovered-control"


def test_phone_restart_does_not_click_an_unlabelled_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = SimpleNamespace(
        keyboard=SimpleNamespace(press=lambda _key: None),
        restart_count=0,
        wait_for_timeout=lambda _milliseconds: None,
    )
    monkeypatch.setattr(container_evaluator, "_simulate_visibility_pause", lambda _page: None)
    monkeypatch.setattr(
        container_evaluator,
        "_visible_controls",
        lambda _page: [
            {
                "x": 10,
                "y": 20,
                "width": 44,
                "height": 44,
                "accessibleLabel": "Attack",
                "label": "restart-action",
            }
        ],
    )
    monkeypatch.setattr(
        container_evaluator,
        "_activate_point",
        lambda *_args, **_kwargs: pytest.fail("unlabelled control must not be clicked"),
    )
    monkeypatch.setattr(
        container_evaluator,
        "_state",
        lambda target, _contract: {"restartCount": target.restart_count},
    )

    result = container_evaluator._restart(
        page,
        {"restart": {"fallback": "none"}},
        0,
        mobile=True,
    )

    assert result == {"sent": False, "method": "none"}


def test_desktop_restart_requires_the_published_r_key_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = SimpleNamespace(
        keyboard=SimpleNamespace(press=lambda _key: None),
        restart_count=0,
        wait_for_timeout=lambda _milliseconds: None,
    )
    monkeypatch.setattr(
        container_evaluator,
        "_visible_controls",
        lambda _page: pytest.fail("desktop controls must not substitute for the R key"),
    )
    monkeypatch.setattr(
        container_evaluator,
        "_state",
        lambda target, _contract: {"restartCount": target.restart_count},
    )

    result = container_evaluator._restart(
        page,
        {"restart": {"desktop_method": "keyboard", "fallback": "none"}},
        0,
        mobile=False,
    )

    assert result == {"sent": False, "method": "keyboard"}


def test_phone_restart_prioritizes_named_control_after_many_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = SimpleNamespace(
        keyboard=SimpleNamespace(press=lambda _key: None),
        restart_count=0,
        wait_for_timeout=lambda _milliseconds: None,
    )
    controls = [
        {"x": index, "y": 10, "width": 44, "height": 44, "label": f"slot {index}"}
        for index in range(12)
    ]
    controls[-1]["label"] = "Restart round"
    monkeypatch.setattr(container_evaluator, "_simulate_visibility_pause", lambda _page: None)
    monkeypatch.setattr(container_evaluator, "_visible_controls", lambda _page: controls)
    monkeypatch.setattr(
        container_evaluator,
        "_activate_point",
        lambda target, x, _y, *, mobile: setattr(
            target, "restart_count", 1 if x == 11 else target.restart_count
        ),
    )
    monkeypatch.setattr(
        container_evaluator,
        "_state",
        lambda target, _contract: {"restartCount": target.restart_count},
    )

    result = container_evaluator._restart(
        page,
        {"restart": {"fallback": "none"}},
        0,
        mobile=True,
    )

    assert result == {"sent": True, "method": "discovered-control", "index": 0}


def test_restart_discovers_controls_after_visibility_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = SimpleNamespace(
        keyboard=SimpleNamespace(press=lambda _key: None),
        restart_count=0,
        visibility_resumed=False,
        wait_for_timeout=lambda _milliseconds: None,
    )

    def resume(target: SimpleNamespace) -> None:
        target.visibility_resumed = True

    def controls(target: SimpleNamespace) -> list[dict[str, object]]:
        if not target.visibility_resumed:
            return [{"x": 1, "y": 1, "width": 44, "height": 44, "label": "old"}]
        return [
            {"x": 50, "y": 50, "width": 44, "height": 44, "label": "Restart"}
        ]

    monkeypatch.setattr(container_evaluator, "_simulate_visibility_pause", resume)
    monkeypatch.setattr(container_evaluator, "_visible_controls", controls)
    monkeypatch.setattr(
        container_evaluator,
        "_activate_point",
        lambda target, x, _y, *, mobile: setattr(
            target, "restart_count", 1 if x == 50 else target.restart_count
        ),
    )
    monkeypatch.setattr(
        container_evaluator,
        "_state",
        lambda target, _contract: {"restartCount": target.restart_count},
    )

    result = container_evaluator._restart(
        page,
        {"restart": {"fallback": "none"}},
        0,
        mobile=True,
    )

    assert result["sent"] is True


def test_restart_rejects_visibility_handlers_that_restart_the_game(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = SimpleNamespace(
        keyboard=SimpleNamespace(press=lambda _key: None),
        restart_count=0,
        wait_for_timeout=lambda _milliseconds: None,
    )
    monkeypatch.setattr(
        container_evaluator,
        "_simulate_visibility_pause",
        lambda target: setattr(target, "restart_count", 1),
    )
    monkeypatch.setattr(
        container_evaluator,
        "_state",
        lambda target, _contract: {"restartCount": target.restart_count},
    )
    monkeypatch.setattr(
        container_evaluator,
        "_visible_controls",
        lambda _page: pytest.fail("controls must not be clicked after visibility restarted"),
    )

    result = container_evaluator._restart(
        page,
        {"restart": {"fallback": "none"}},
        0,
        mobile=True,
    )

    assert result["sent"] is False
    assert result["method"] == "visibility-state-changed"


def test_restart_rediscovers_phone_control_after_resuming_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = SimpleNamespace(
        keyboard=SimpleNamespace(press=lambda _key: None),
        restart_count=0,
        phase="paused",
        wait_for_timeout=lambda _milliseconds: None,
    )
    monkeypatch.setattr(container_evaluator, "_simulate_visibility_pause", lambda _page: None)
    monkeypatch.setattr(
        container_evaluator,
        "_visible_controls",
        lambda target: [
            {
                "x": 10 if target.phase == "paused" else 20,
                "y": 20,
                "width": 80,
                "height": 44,
                "label": "Resume" if target.phase == "paused" else "Restart",
            }
        ],
    )

    def activate(target, x, _y, *, mobile):
        assert mobile is True
        if x == 10:
            target.phase = "playing"
        elif x == 20:
            target.restart_count += 1

    monkeypatch.setattr(container_evaluator, "_activate_point", activate)
    monkeypatch.setattr(
        container_evaluator,
        "_state",
        lambda target, _contract: {
            "phase": target.phase,
            "restartCount": target.restart_count,
        },
    )

    result = container_evaluator._restart(
        page,
        {"restart": {"fallback": "none"}},
        0,
        mobile=True,
    )

    assert result == {"sent": True, "method": "discovered-control", "index": 1}


def test_evaluator_static_server_reproduces_nested_public_route(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("nested game", encoding="utf-8")
    play_path = "/playground/first-night/candidate/"
    handler = functools.partial(
        container_evaluator.ProductionRouteHandler,
        directory=dist,
        mount_path=play_path,
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        assert urllib.request.urlopen(origin + play_path, timeout=2).read() == b"nested game"
        with pytest.raises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(origin + "/index.html", timeout=2)
        assert raised.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_evaluator_runtime_requests_stay_inside_the_nested_route() -> None:
    play_url = "http://127.0.0.1:8123/playground/first-night/candidate/"
    assert container_evaluator._runtime_request_allowed(
        play_url + "assets/game.js", play_url
    )
    assert container_evaluator._runtime_request_allowed("data:image/png;base64,AA==", play_url)
    assert container_evaluator._runtime_request_allowed("blob:http://127.0.0.1:8123/id", play_url)
    assert not container_evaluator._runtime_request_allowed(
        "blob:http://127.0.0.1:8123/id", play_url, is_navigation=True
    )
    assert not container_evaluator._runtime_request_allowed(
        "http://127.0.0.1:8123/sound.ogg", play_url
    )
    assert not container_evaluator._runtime_request_allowed(
        "http://127.0.0.1:9000/playground/first-night/candidate/", play_url
    )


def test_runtime_contract_loader_rejects_malformed_field_schema(tmp_path: Path) -> None:
    contract = copy.deepcopy(_contract("signal-drift"))
    contract["state_schema"]["required"]["charge"] = {"type": "mystery"}
    path = tmp_path / "infra/evaluator/contracts/signal-drift.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(RuntimeContractError, match="unsupported"):
        load_runtime_contract(
            tmp_path,
            task_id="signal-drift",
            seed=94721,
            viewports=contract["viewports"],
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda contract: contract["probes"]["desktop"][0].update(baseline_ms=0),
            "baseline_ms",
        ),
        (
            lambda contract: contract["restart"]["match_initial_paths"][0].update(
                path="notAStateField"
            ),
            "does not name a required field",
        ),
    ),
)
def test_runtime_contract_loader_rejects_malformed_probe_and_restart_recipes(
    tmp_path: Path, mutation: object, message: str
) -> None:
    contract = copy.deepcopy(_contract("signal-drift"))
    mutation(contract)
    path = tmp_path / "infra/evaluator/contracts/signal-drift.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(RuntimeContractError, match=message):
        load_runtime_contract(
            tmp_path,
            task_id="signal-drift",
            seed=94721,
            viewports=contract["viewports"],
        )


def test_render_source_digest_excludes_build_outputs(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/main.ts").write_text("source", encoding="utf-8")
    original = host_evaluator.render_source_sha256(tmp_path)
    for directory in ("dist", "node_modules/package"):
        path = tmp_path / directory
        path.mkdir(parents=True)
        (path / "generated.js").write_text("generated", encoding="utf-8")
    assert host_evaluator.render_source_sha256(tmp_path) == original

    (tmp_path / "src/main.ts").write_text("changed", encoding="utf-8")
    assert host_evaluator.render_source_sha256(tmp_path) != original


def test_render_dist_digest_tracks_the_playable_bundle(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("first", encoding="utf-8")
    original = host_evaluator.render_dist_sha256(dist)
    (dist / "index.html").write_text("second", encoding="utf-8")
    assert host_evaluator.render_dist_sha256(dist) != original


def _run_manifest(run_root: Path, workspace: Path, task_id: str) -> dict:
    task = load_task(ROOT, task_id)
    return {
        "schema_version": 1,
        "run_id": "test-run",
        "task": {
            "id": task_id,
            "digest": host_evaluator._task_digest(task.root),
            "brief_sha256": host_evaluator._file_digest(task.brief),
        },
        "profile": {"id": "test-profile"},
        "workspace": str(workspace),
        "workspace_digest": host_evaluator.candidate_workspace_sha256(workspace),
        "status": "candidate-complete",
    }


def test_evaluate_run_passes_manifest_task_contract_and_records_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "run"
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text("{}", encoding="utf-8")
    run_root.mkdir()
    manifest = _run_manifest(run_root, workspace, "first-night")
    manifest_bytes = json.dumps(manifest).encode()
    (run_root / "manifest.json").write_bytes(manifest_bytes)
    evaluator_calls: list[tuple[object, ...]] = []

    def fake_docker(*args: object, **kwargs: object) -> SimpleNamespace:
        if args and args[0] == "run" and "candidate-image" in args:
            dist = run_root / "render/dist"
            dist.mkdir(parents=True)
            (dist / "index.html").write_text("built", encoding="utf-8")
        if "/evaluate.py" in args:
            evaluator_calls.append(args)
            config = json.loads(
                (run_root / "evaluation/evaluator-contract.json").read_text()
            )
            report = {
                "schema_version": 1,
                "task_id": config["task_id"],
                "trusted": True,
                "passed": True,
                "build": {"passed": True, "exit_code": 0},
                "evaluator": {
                    "runtime_contract_sha256": config["runtime_contract_sha256"],
                    "script_sha256": config["evaluator_sha256"],
                    "runtime_schema_sha256": config["runtime_schema_sha256"],
                    "render_source_sha256": config["render_source_sha256"],
                },
                "evidence": {
                    "render_source_sha256": config["render_source_sha256"],
                    "post_build_render_source_sha256": config[
                        "post_build_render_source_sha256"
                    ],
                    "render_source_unchanged": config["render_source_unchanged"],
                    "render_dist_sha256": config["render_dist_sha256"],
                },
                "checks": [
                    {
                        "name": "render-source-unchanged",
                        "passed": config["render_source_unchanged"],
                    }
                ],
            }
            (run_root / "evaluation/report.json").write_text(json.dumps(report))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(host_evaluator, "docker", fake_docker)
    monkeypatch.setattr(
        host_evaluator,
        "load_container_config",
        lambda root: SimpleNamespace(
            image="candidate-image", evaluator_image="evaluator-image"
        ),
    )

    report_path = host_evaluator.evaluate_run(ROOT, run_root)
    report = json.loads(report_path.read_text())
    assert report["task_id"] == "first-night"
    assert report["passed"]
    assert report["evaluator"]["render_source_sha256"] == report["evidence"][
        "render_source_sha256"
    ]
    assert any(
        item["name"] == "render-source-unchanged" and item["passed"]
        for item in report["checks"]
    )
    assert len(evaluator_calls) == 1
    assert evaluator_calls[0][-3:] == (
        "/evaluate.py",
        "--contract",
        "/output/evaluator-contract.json",
    )
    assert any("runtime_schema.py:/runtime_schema.py:ro" in str(arg) for arg in evaluator_calls[0])
    evaluator_config = json.loads(
        (run_root / "evaluation/evaluator-contract.json").read_text()
    )
    assert evaluator_config["task_id"] == "first-night"
    assert evaluator_config["runtime_contract"]["seed"] == 37199
    assert (run_root / "manifest.json").read_bytes() == manifest_bytes
    assert len(evaluator_config["runtime_contract_sha256"]) == 64
    assert len(evaluator_config["evaluator_sha256"]) == 64
    assert len(evaluator_config["render_source_sha256"]) == 64
    assert len(evaluator_config["render_dist_sha256"]) == 64
    assert evaluator_config["render_source_unchanged"] is True


def test_evaluate_run_rejects_a_drifted_task_before_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "run"
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    run_root.mkdir()
    manifest = _run_manifest(run_root, workspace, "first-night")
    manifest["task"]["digest"] = "0" * 64
    (run_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        host_evaluator,
        "docker",
        lambda *args, **kwargs: pytest.fail("docker must not run after task drift"),
    )

    with pytest.raises(ValueError, match="task digest no longer matches"):
        host_evaluator.evaluate_run(ROOT, run_root)
    assert not (run_root / "render").exists()


def test_evaluate_run_rejects_workspace_changes_after_candidate_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "run"
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text("{}", encoding="utf-8")
    run_root.mkdir()
    manifest = _run_manifest(run_root, workspace, "first-night")
    (run_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (workspace / "package.json").write_text('{"changed": true}', encoding="utf-8")
    monkeypatch.setattr(
        host_evaluator,
        "docker",
        lambda *args, **kwargs: pytest.fail("docker must not run after workspace drift"),
    )

    with pytest.raises(ValueError, match="workspace changed after candidate exit"):
        host_evaluator.evaluate_run(ROOT, run_root)
    assert not (run_root / "render").exists()


def test_evaluate_run_fails_when_build_mutates_render_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "run"
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text("{}", encoding="utf-8")
    run_root.mkdir()
    manifest = _run_manifest(run_root, workspace, "first-night")
    manifest_bytes = json.dumps(manifest).encode()
    (run_root / "manifest.json").write_bytes(manifest_bytes)

    def fake_docker(*args: object, **_kwargs: object) -> SimpleNamespace:
        if args and args[0] == "run" and "candidate-image" in args:
            dist = run_root / "render/dist"
            dist.mkdir()
            (dist / "index.html").write_text("built", encoding="utf-8")
            (run_root / "render/generated-source.js").write_text(
                "mutated during build", encoding="utf-8"
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        pytest.fail(f"evaluator must not run after source mutation: {args!r}")

    monkeypatch.setattr(host_evaluator, "docker", fake_docker)
    monkeypatch.setattr(
        host_evaluator,
        "load_container_config",
        lambda root: SimpleNamespace(
            image="candidate-image", evaluator_image="evaluator-image"
        ),
    )

    report = json.loads(host_evaluator.evaluate_run(ROOT, run_root).read_text())
    assert not report["passed"]
    assert report["build"]["passed"]
    assert report["evidence"]["render_source_unchanged"] is False
    assert report["evidence"]["render_source_sha256"] != report["evidence"][
        "post_build_render_source_sha256"
    ]
    assert (run_root / "manifest.json").read_bytes() == manifest_bytes


def test_missing_evaluator_report_is_untrusted_infrastructure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "run"
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text("{}", encoding="utf-8")
    run_root.mkdir()
    (run_root / "manifest.json").write_text(
        json.dumps(_run_manifest(run_root, workspace, "first-night")),
        encoding="utf-8",
    )

    def fake_docker(*args: object, **_kwargs: object) -> SimpleNamespace:
        if args and args[0] == "run" and "candidate-image" in args:
            dist = run_root / "render/dist"
            dist.mkdir(parents=True)
            (dist / "index.html").write_text("built", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "/evaluate.py" in args:
            return SimpleNamespace(returncode=23, stdout="", stderr="browser crashed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(host_evaluator, "docker", fake_docker)
    monkeypatch.setattr(
        host_evaluator,
        "load_container_config",
        lambda root: SimpleNamespace(
            image="candidate-image", evaluator_image="evaluator-image"
        ),
    )

    report = json.loads(host_evaluator.evaluate_run(ROOT, run_root).read_text())
    assert report["trusted"] is False
    assert report["passed"] is False
    assert "without writing a report" in report["infrastructure_errors"][0]
