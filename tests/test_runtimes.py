from pathlib import Path

from web3dgamebench.config import load_profiles
from web3dgamebench.container import load_container_config, wrap_command
from web3dgamebench.runtimes import build_invocation

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
