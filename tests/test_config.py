from pathlib import Path

from web3dgamebench.config import load_judges, load_profiles, load_task, validate_matrix
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


def test_candidate_runs_have_no_fixed_time_limit() -> None:
    profiles = load_profiles(ROOT)
    task = load_task(ROOT, "signal-drift")
    assert all(not hasattr(profile, "timeout_seconds") for profile in profiles.values())
    assert not hasattr(task, "time_limit_seconds")


def test_candidate_commands_have_a_bounded_runtime() -> None:
    config = load_container_config(ROOT)
    assert config.command_timeout_seconds == 1200
