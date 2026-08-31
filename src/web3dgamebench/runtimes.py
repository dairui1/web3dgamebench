from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .config import Profile


@dataclass(frozen=True)
class GoalActivation:
    schema_version: int
    control_version: str
    mode: str
    completion: str
    harness: str
    activation_method: str
    native_goal: bool
    lifecycle_observable: bool
    evidence: str
    objective_sha256: str
    candidate_prompt_sha256: str
    control_prompt_sha256: str
    receipt_sha256: str


@dataclass(frozen=True)
class Invocation:
    argv: tuple[str, ...]
    stdin_prompt: bool
    env: dict[str, str]
    trace_format: str
    candidate_prompt_sha256: str
    goal_activation: GoalActivation | None


_GOAL_CONTROL_VERSION = "web3dgamebench-external-goal-v1"
_GOAL_OBJECTIVE = "Complete and verify the benchmark contract in the unmodified TASK.md."


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _control_prompt(*, native_goal: bool) -> str:
    common = f"""Web3DGameBench external persistent-goal control ({_GOAL_CONTROL_VERSION}).
This control is supplied by the benchmark runner and is separate from TASK.md.
Persistent objective: {_GOAL_OBJECTIVE}
Keep working autonomously across context compaction until the complete task contract is implemented.
Before finishing, build the production bundle and inspect the game at every required viewport.
Finish only after the implementation and truthful verification evidence satisfy the task contract.
Do not weaken, rewrite, or add this control to TASK.md, and do not claim checks you did not run."""
    if not native_goal:
        return common
    return (
        common
        + "\nThis Codex runtime provides its native goal tools. At the start of the run, call "
        + f'create_goal exactly once with objective "{_GOAL_OBJECTIVE}" and omit token_budget. '
        + "Keep that goal active while working. Call update_goal with status complete only after "
        + "the objective and verification requirements are actually satisfied."
    )


def _goal_activation(
    profile: Profile,
    prompt: str,
    goal_mode: str | None,
    goal_completion: str | None,
) -> tuple[str | None, GoalActivation | None]:
    if goal_mode is None:
        if goal_completion is not None:
            raise ValueError("goal completion requires a goal mode")
        return None, None
    if goal_mode != "external-goal":
        raise ValueError(f"unsupported goal mode: {goal_mode}")
    if goal_completion != "contract-and-evidence":
        raise ValueError(
            "external-goal requires completion policy contract-and-evidence"
        )

    native_goal = profile.harness == "codex"
    control_prompt = _control_prompt(native_goal=native_goal)
    if native_goal:
        activation_method = "codex-native-goal-via-developer-instructions"
        evidence = "trace:create_goal"
    elif profile.harness == "claude-code":
        # Claude and Pi retain system instructions through compaction but expose no goal lifecycle.
        activation_method = "claude-code-system-persistence-policy"
        evidence = "argv:--append-system-prompt"
    elif profile.harness == "pi":
        activation_method = "pi-system-persistence-policy"
        evidence = "argv:--append-system-prompt"
    else:
        raise ValueError(f"unsupported harness: {profile.harness}")

    receipt = {
        "schema_version": 1,
        "control_version": _GOAL_CONTROL_VERSION,
        "mode": goal_mode,
        "completion": goal_completion,
        "harness": profile.harness,
        "activation_method": activation_method,
        "native_goal": native_goal,
        "lifecycle_observable": native_goal,
        "evidence": evidence,
        "objective_sha256": _sha256_text(_GOAL_OBJECTIVE),
        "candidate_prompt_sha256": _sha256_text(prompt),
        "control_prompt_sha256": _sha256_text(control_prompt),
    }
    receipt_sha256 = _sha256_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    )
    return control_prompt, GoalActivation(**receipt, receipt_sha256=receipt_sha256)


def goal_activation_status(activation: GoalActivation, stdout: str) -> str:
    if not activation.native_goal:
        return "configured"
    lifecycle = parse_goal_lifecycle(stdout)
    creations = [event for event in lifecycle if event["tool"] == "create_goal"]
    if not creations:
        return "not-observed"
    if not any(
        event.get("objective_sha256") == activation.objective_sha256
        for event in creations
    ):
        return "observed-objective-unverified"
    terminal = next(
        (
            event.get("status")
            for event in reversed(lifecycle)
            if event["tool"] == "update_goal"
            and event.get("status") in {"complete", "blocked"}
        ),
        None,
    )
    return f"observed-{terminal}" if terminal else "observed-active"


def parse_goal_lifecycle(stdout: str) -> list[dict[str, str]]:
    lifecycle: list[dict[str, str]] = []
    seen: dict[tuple[str, str | None, str | None], int] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for call in _named_goal_tools(event):
            tool = str(call["tool"])
            status = call.get("status")
            objective_sha256 = call.get("objective_sha256")
            key = (tool, status, objective_sha256)
            if key in seen:
                continue
            incomplete_key = (tool, status, None)
            if objective_sha256 and incomplete_key in seen:
                index = seen.pop(incomplete_key)
                lifecycle[index] = dict(call)
                seen[key] = index
                continue
            if not objective_sha256 and any(
                existing_tool == tool and existing_status == status
                for existing_tool, existing_status, _ in seen
            ):
                continue
            seen[key] = len(lifecycle)
            lifecycle.append(dict(call))
    return lifecycle


def _named_goal_tools(value: object) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    if isinstance(value, dict):
        name = next(
            (
                value.get(key)
                for key in ("name", "tool", "tool_name")
                if isinstance(value.get(key), str)
            ),
            None,
        )
        if name in {"create_goal", "get_goal", "update_goal"}:
            item = {"tool": name}
            arguments = value.get("arguments", value.get("args", value.get("input")))
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = None
            if name == "create_goal" and isinstance(arguments, dict):
                objective = arguments.get("objective")
                if isinstance(objective, str):
                    item["objective_sha256"] = _sha256_text(objective)
            if name == "update_goal" and isinstance(arguments, dict):
                status = arguments.get("status")
                if isinstance(status, str):
                    item["status"] = status
            found.append(item)
        for child in value.values():
            found.extend(_named_goal_tools(child))
    if isinstance(value, list):
        for child in value:
            found.extend(_named_goal_tools(child))
    return found


def build_invocation(
    profile: Profile,
    workspace: Path,
    prompt: str,
    *,
    isolation: str = "runtime",
    goal_mode: str | None = None,
    goal_completion: str | None = None,
) -> Invocation:
    final_path = workspace / ".web3dgamebench-final.txt"
    control_prompt, goal_activation = _goal_activation(
        profile, prompt, goal_mode, goal_completion
    )
    candidate_prompt_sha256 = _sha256_text(prompt)
    if profile.harness == "codex":
        if not profile.effort:
            raise ValueError("Codex profiles require an explicit effort")
        external = isolation == "container"
        argv = [
            "codex",
            "exec",
            "-C",
            str(workspace),
            "--model",
            profile.model,
            "-c",
            f'model_reasoning_effort="{profile.effort}"',
            "-c",
            'approval_policy="never"',
            "-c",
            f"sandbox_workspace_write.network_access={str(external).lower()}",
            "-c",
            'web_search="disabled"',
        ]
        if control_prompt:
            argv.extend(
                [
                    "-c",
                    f"developer_instructions={json.dumps(control_prompt)}",
                    "--enable",
                    "goals",
                ]
            )
        argv.extend(
            [
                "--disable",
                "multi_agent",
                "--sandbox",
                "danger-full-access" if external else "workspace-write",
                "--json",
                "--ephemeral",
                "--ignore-user-config",
                "--strict-config",
                "--skip-git-repo-check",
                "--color",
                "never",
                "--output-last-message",
                str(final_path),
                "-",
            ]
        )
        return Invocation(
            argv=tuple(argv),
            stdin_prompt=True,
            env={},
            trace_format="codex-jsonl-v1",
            candidate_prompt_sha256=candidate_prompt_sha256,
            goal_activation=goal_activation,
        )
    if profile.harness == "claude-code":
        argv = [
            "claude",
            "-p",
            "--model",
            profile.model,
            "--setting-sources",
            "project",
            "--no-session-persistence",
            "--no-chrome",
            "--strict-mcp-config",
            "--tools",
            "Bash,Read,Edit,Write,Glob,Grep",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            "Bash,Read,Edit,Write,Glob,Grep",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        if control_prompt:
            argv.extend(["--append-system-prompt", control_prompt])
        # The pilot intentionally omits --effort so Claude Code uses the official default.
        argv.append(prompt)
        return Invocation(
            argv=tuple(argv),
            stdin_prompt=False,
            env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "DISABLE_AUTOUPDATER": "1"},
            trace_format="claude-code-jsonl-v1",
            candidate_prompt_sha256=candidate_prompt_sha256,
            goal_activation=goal_activation,
        )
    if profile.harness == "pi":
        if not profile.provider:
            raise ValueError("pi profiles require provider")
        argv = [
            "pi",
            "--provider",
            profile.provider,
            "--model",
            profile.model,
            "--mode",
            "json",
            "--print",
            "--no-session",
            "--no-context-files",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--tools",
            "read,bash,edit,write,grep,find,ls",
            "--no-approve",
        ]
        if control_prompt:
            argv.extend(["--append-system-prompt", control_prompt])
        argv.append(prompt)
        return Invocation(
            argv=tuple(argv),
            stdin_prompt=False,
            env={},
            trace_format="pi-jsonl-v1",
            candidate_prompt_sha256=candidate_prompt_sha256,
            goal_activation=goal_activation,
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
