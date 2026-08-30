from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import Profile


@dataclass(frozen=True)
class Invocation:
    argv: tuple[str, ...]
    stdin_prompt: bool
    env: dict[str, str]
    trace_format: str


def build_invocation(
    profile: Profile, workspace: Path, prompt: str, *, isolation: str = "runtime"
) -> Invocation:
    final_path = workspace / ".aetherplay-final.txt"
    if profile.harness == "codex":
        if not profile.effort:
            raise ValueError("Codex profiles require an explicit effort")
        external = isolation == "container"
        return Invocation(
            argv=(
                "codex", "exec", "-C", str(workspace), "--model", profile.model,
                "-c", f'model_reasoning_effort="{profile.effort}"',
                "-c", 'approval_policy="never"',
                "-c", f'sandbox_workspace_write.network_access={str(external).lower()}',
                "-c", 'web_search="disabled"',
                "--disable", "multi_agent", "--sandbox", "danger-full-access" if external else "workspace-write",
                "--json", "--ephemeral", "--ignore-user-config", "--strict-config",
                "--skip-git-repo-check", "--color", "never",
                "--output-last-message", str(final_path), "-",
            ),
            stdin_prompt=True,
            env={},
            trace_format="codex-jsonl-v1",
        )
    if profile.harness == "claude-code":
        argv = [
            "claude", "-p", "--model", profile.model,
            "--setting-sources", "project", "--no-session-persistence", "--no-chrome",
            "--strict-mcp-config", "--tools", "Bash,Read,Edit,Write,Glob,Grep",
            "--permission-mode", "acceptEdits", "--allowedTools",
            "Bash,Read,Edit,Write,Glob,Grep", "--output-format", "stream-json", "--verbose",
        ]
        # The pilot intentionally omits --effort so Claude Code uses the official default.
        argv.append(prompt)
        return Invocation(
            argv=tuple(argv),
            stdin_prompt=False,
            env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "DISABLE_AUTOUPDATER": "1"},
            trace_format="claude-code-jsonl-v1",
        )
    if profile.harness == "pi":
        if not profile.provider:
            raise ValueError("pi profiles require provider")
        return Invocation(
            argv=(
                "pi", "--provider", profile.provider, "--model", profile.model,
                "--mode", "json", "--print", "--no-session", "--no-context-files",
                "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes",
                "--tools", "read,bash,edit,write,grep,find,ls", "--no-approve", prompt,
            ),
            stdin_prompt=False,
            env={},
            trace_format="pi-jsonl-v1",
        )
    raise ValueError(f"unsupported harness: {profile.harness}")


def parse_resolved_model(trace_format: str, stdout: str) -> str | None:
    resolved: str | None = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if trace_format == "claude-code-jsonl-v1":
            if event.get("type") == "system" and event.get("subtype") == "init":
                resolved = event.get("model") or resolved
        elif trace_format == "codex-jsonl-v1":
            if isinstance(event.get("model"), str):
                resolved = event["model"]
        elif trace_format == "pi-jsonl-v1":
            model = event.get("model")
            if isinstance(model, str):
                resolved = model
            message = event.get("message")
            if isinstance(message, dict) and isinstance(message.get("model"), str):
                resolved = message["model"]
    return resolved
