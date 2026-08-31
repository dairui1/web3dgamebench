import hashlib
import json
import tomllib
from pathlib import Path

import pytest

from web3dgamebench.config import load_profiles
from web3dgamebench.container import load_container_config, wrap_command
from web3dgamebench.runtimes import (
    build_invocation,
    goal_activation_status,
    parse_goal_lifecycle,
)

ROOT = Path(__file__).resolve().parents[1]


def test_claude_default_omits_effort_flag() -> None:
    profile = load_profiles(ROOT)["claude-sonnet-default"]
    invocation = build_invocation(profile, Path("/tmp/workspace"), "task")
    assert "--effort" not in invocation.argv


def test_pi_uses_opencode_go_without_exposing_key_on_argv() -> None:
    profile = load_profiles(ROOT)["pi-deepseek-v4-flash"]
    invocation = build_invocation(profile, Path("/tmp/workspace"), "task")
    assert invocation.argv[invocation.argv.index("--provider") + 1] == "opencode-go"
    assert "--api-key" not in invocation.argv


def test_pi_container_caps_each_command_without_limiting_the_task(
    monkeypatch, tmp_path: Path
) -> None:
    profile = load_profiles(ROOT)["pi-deepseek-v4-flash"]
    invocation = build_invocation(profile, Path("/workspace"), "task")
    monkeypatch.setenv("OPENCODE_GO_APIKEY", "test-only-token")

    argv, environment = wrap_command(
        invocation.argv,
        root=ROOT,
        config=load_container_config(ROOT),
        workspace=tmp_path / "workspace",
        profile=profile,
        credential_dir=tmp_path / "runtime-home",
    )

    assert "--extension" in argv
    assert "web3dgamebench-command-timeout.js" in argv[argv.index("--extension") + 1]
    assert argv.index("--extension") > argv.index("--no-extensions")
    assert "WEB3DGAMEBENCH_COMMAND_TIMEOUT_SECONDS=<passed>" not in argv
    assert environment["WEB3DGAMEBENCH_COMMAND_TIMEOUT_SECONDS"] == "<passed>"
    assert "-e" in argv
    assert "WEB3DGAMEBENCH_COMMAND_TIMEOUT_SECONDS=1200" in argv


def test_codex_effort_is_explicit() -> None:
    profile = load_profiles(ROOT)["codex-luna-max"]
    invocation = build_invocation(profile, Path("/tmp/workspace"), "task")
    assert 'model_reasoning_effort="max"' in invocation.argv
    assert "--skip-git-repo-check" in invocation.argv


def test_container_codex_uses_external_boundary() -> None:
    profile = load_profiles(ROOT)["codex-sol-medium"]
    invocation = build_invocation(
        profile, Path("/workspace"), "task", isolation="container"
    )
    assert "danger-full-access" in invocation.argv
    assert "sandbox_workspace_write.network_access=true" in invocation.argv


@pytest.mark.parametrize(
    ("profile_id", "native_goal", "method"),
    [
        (
            "codex-sol-medium",
            True,
            "codex-native-goal-via-developer-instructions",
        ),
        (
            "claude-sonnet-default",
            False,
            "claude-code-system-persistence-policy",
        ),
        ("pi-deepseek-v4-flash", False, "pi-system-persistence-policy"),
    ],
)
def test_external_goal_is_separate_system_control_for_every_harness(
    profile_id: str, native_goal: bool, method: str
) -> None:
    profile = load_profiles(ROOT)[profile_id]
    prompt = "TASK-BRIEF-SENTINEL"
    invocation = build_invocation(
        profile,
        Path("/workspace"),
        prompt,
        goal_mode="external-goal",
        goal_completion="contract-and-evidence",
    )

    if profile.harness == "codex":
        configs = [
            invocation.argv[index + 1]
            for index, argument in enumerate(invocation.argv)
            if argument == "-c"
        ]
        developer = next(item for item in configs if item.startswith("developer_instructions="))
        control = tomllib.loads(developer)["developer_instructions"]
        assert invocation.argv[invocation.argv.index("--enable") + 1] == "goals"
        assert prompt not in invocation.argv
    else:
        control = invocation.argv[invocation.argv.index("--append-system-prompt") + 1]
        assert invocation.argv[-1] == prompt

    assert "external persistent-goal control" in control
    assert "unmodified TASK.md" in control
    assert prompt not in control
    assert invocation.goal_activation is not None
    assert invocation.goal_activation.native_goal is native_goal
    assert invocation.goal_activation.lifecycle_observable is native_goal
    assert invocation.goal_activation.activation_method == method
    assert invocation.goal_activation.candidate_prompt_sha256 == invocation.candidate_prompt_sha256
    assert len(invocation.goal_activation.control_prompt_sha256) == 64
    assert len(invocation.goal_activation.receipt_sha256) == 64


def test_external_goal_receipt_is_stable_across_workspaces() -> None:
    profile = load_profiles(ROOT)["codex-sol-medium"]
    first = build_invocation(
        profile,
        Path("/workspace/one"),
        "same prompt",
        goal_mode="external-goal",
        goal_completion="contract-and-evidence",
    )
    second = build_invocation(
        profile,
        Path("/workspace/two"),
        "same prompt",
        goal_mode="external-goal",
        goal_completion="contract-and-evidence",
    )
    assert first.goal_activation is not None
    assert second.goal_activation is not None
    assert first.goal_activation.receipt_sha256 == second.goal_activation.receipt_sha256


def test_goal_lifecycle_only_records_named_goal_tools() -> None:
    objective = "Complete and verify the benchmark contract in the unmodified TASK.md."
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "item.started",
                    "item": {"tool": "create_goal", "arguments": {"objective": objective}},
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"tool": "create_goal", "arguments": {"objective": objective}},
                }
            ),
            json.dumps({"item": {"tool_name": "get_goal", "input": {}}}),
            json.dumps(
                {
                    "item": {
                        "name": "update_goal",
                        "arguments": '{"status":"complete"}',
                    }
                }
            ),
            json.dumps({"item": {"name": "exec_command", "arguments": {}}}),
        ]
    )
    activation = build_invocation(
        load_profiles(ROOT)["codex-sol-medium"],
        Path("/workspace"),
        "task",
        goal_mode="external-goal",
        goal_completion="contract-and-evidence",
    ).goal_activation
    assert activation is not None
    assert parse_goal_lifecycle(stdout) == [
        {
            "tool": "create_goal",
            "objective_sha256": hashlib.sha256(objective.encode()).hexdigest(),
        },
        {"tool": "get_goal"},
        {"tool": "update_goal", "status": "complete"},
    ]
    assert goal_activation_status(activation, stdout) == "observed-complete"


def test_goal_lifecycle_prefers_nested_create_goal_arguments() -> None:
    objective = "Complete and verify the benchmark contract in the unmodified TASK.md."
    stdout = json.dumps(
        {
            "name": "create_goal",
            "item": {
                "name": "create_goal",
                "arguments": {"objective": objective},
            },
        }
    )

    assert parse_goal_lifecycle(stdout) == [
        {
            "tool": "create_goal",
            "objective_sha256": hashlib.sha256(objective.encode()).hexdigest(),
        }
    ]
