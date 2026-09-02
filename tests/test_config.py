import json
from pathlib import Path

import pytest

from web3dgamebench.config import (
    ConfigError,
    load_judges,
    load_profiles,
    load_task,
    validate_matrix,
)
from web3dgamebench.container import load_container_config

ROOT = Path(__file__).resolve().parents[1]


def test_pilot_matrix_has_requested_eight_profiles() -> None:
    season, profiles = validate_matrix(ROOT, "pilot-2026-09")
    assert len(season.profiles) == 8
    assert profiles["codex-sol-medium"].effort == "medium"
    assert profiles["codex-terra-high"].effort == "high"
    assert profiles["codex-luna-max"].effort == "max"
    assert profiles["claude-sonnet-default"].effort is None
    assert profiles["claude-opus-default"].effort is None
    assert profiles["pi-deepseek-v4-flash"].provider == "opencode-go"
    assert profiles["pi-qwen3-8-flash"].provider == "opencode-go"
    assert profiles["pi-qwen3-8-flash"].model == "qwen3.8-flash"
    assert profiles["pi-glm-5-3-flash"].provider == "opencode-go"
    assert profiles["pi-glm-5-3-flash"].model == "glm-5.3-flash"


def test_all_profiles_have_unique_ids() -> None:
    profiles = load_profiles(ROOT)
    assert len(profiles) == len(set(profiles))


def test_pilot_judge_uses_one_medium_pi_rollout() -> None:
    judge = load_judges(ROOT)["pi-sol-medium"]
    assert judge.harness == "pi"
    assert judge.provider == "openai-codex"
    assert judge.model == "gpt-5.6-sol"
    assert judge.effort == "medium"
    assert judge.runs == 1


def test_candidate_tasks_and_profiles_do_not_override_runtime_limit() -> None:
    profiles = load_profiles(ROOT)
    task = load_task(ROOT, "signal-drift")
    assert all(not hasattr(profile, "timeout_seconds") for profile in profiles.values())
    assert not hasattr(task, "time_limit_seconds")


def test_candidate_commands_have_a_bounded_runtime() -> None:
    config = load_container_config(ROOT)
    assert config.command_timeout_seconds == 5400
    assert config.candidate_total_timeout_seconds == 5400
    assert config.pi_adapter.runtime_evidence_schema_version == 4
    assert config.pids_limit == 1024


def test_season_one_preflight_has_ten_tasks_and_ninety_cells() -> None:
    season, profiles = validate_matrix(ROOT, "season-1")
    assert season.status == "ready"
    assert season.publish_prompts_after_close is False
    assert len(season.tasks) == 10
    assert len(season.profiles) == 9
    assert "claude-fable-default" in season.profiles
    assert profiles["claude-fable-default"].model == "claude-fable-5-1"
    assert len(season.tasks) * len(season.profiles) * season.attempts == 90
    assert set(season.profiles).issubset(profiles)


def test_task_retains_machine_readable_runtime_metadata() -> None:
    task = load_task(ROOT, "first-night")
    assert task.status == "ready"
    assert task.framework == "three.js"
    assert task.seed == 37199
    assert task.goal_mode == "external-goal"
    assert task.goal_completion == "contract-and-evidence"
    assert task.viewports["desktop"].width == 1440
    assert task.viewports["phone"].height == 844
    assert task.checks.canvas_nonblank
    assert task.checks.resize
    assert not task.checks.runtime_state
    assert not task.checks.restart
    assert not task.checks.pointer_or_touch_input
    assert task.review_brief == task.root / "goal.zh-CN.md"
    assert task.reference_archetype == "Minecraft"


def _write_test_task(tmp_path: Path, *, seed: str = "17", include_restart: bool = True) -> None:
    task_root = tmp_path / "tasks/example/task"
    (task_root / "starter").mkdir(parents=True)
    (task_root / "brief.md").write_text("example", encoding="utf-8")
    restart = "restart = true\n" if include_restart else ""
    (task_root / "task.toml").write_text(
        f'''id = "example"
title = "Example"
season = "season-1"
status = "ready"
framework = "three.js"
brief = "brief.md"
starter = "starter"
seed = {seed}

[goal]
mode = "external-goal"
completion = "contract-and-evidence"

[viewport.desktop]
width = 1440
height = 900

[viewport.phone]
width = 390
height = 844

[checks]
build = true
canvas_nonblank = true
keyboard_input = true
pointer_or_touch_input = true
{restart}resize = true
runtime_state = true
''',
        encoding="utf-8",
    )


def test_task_rejects_boolean_seed_even_though_bool_is_an_int_subclass(tmp_path: Path) -> None:
    _write_test_task(tmp_path, seed="true")
    with pytest.raises(ConfigError, match="seed must be an integer"):
        load_task(tmp_path, "example")


def test_task_rejects_an_unimplemented_check_shape(tmp_path: Path) -> None:
    _write_test_task(tmp_path, include_restart=False)
    with pytest.raises(ConfigError, match="missing restart"):
        load_task(tmp_path, "example")


def test_season_one_preflight_rejects_a_malformed_runtime_contract(tmp_path: Path) -> None:
    _write_test_task(tmp_path)
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "profiles.toml").write_text(
        '[profiles.test]\nharness = "codex"\nmodel = "test"\n', encoding="utf-8"
    )
    (configs / "seasons.toml").write_text(
        '[seasons.season-1]\nstatus = "ready"\ntasks = ["example"]\n'
        'profiles = ["test"]\nattempts = 1\n'
        'publish_prompts_after_close = true\n',
        encoding="utf-8",
    )
    contract = json.loads(
        (ROOT / "infra/evaluator/contracts/signal-drift.json").read_text()
    )
    contract["task_id"] = "example"
    contract["seed"] = 17
    contract["state_schema"]["required"]["seed"]["const"] = 17
    contract["state_schema"]["required"]["charge"] = {"type": "mystery"}
    contract_path = tmp_path / "infra/evaluator/contracts/example.json"
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ConfigError, match="unsupported"):
        validate_matrix(tmp_path, "season-1")
