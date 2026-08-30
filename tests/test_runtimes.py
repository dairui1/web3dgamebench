from pathlib import Path

from aetherplay.config import load_profiles
from aetherplay.runtimes import build_invocation

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
