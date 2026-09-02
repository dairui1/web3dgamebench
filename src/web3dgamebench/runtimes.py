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


_GOAL_CONTROL_VERSION = "web3dgamebench-operational-completion-v5"
_RUNTIME_EVIDENCE_SCHEMA_VERSION = 4
_GOAL_OBJECTIVE = "Implement TASK.md and stop after a successful npm run build."


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _control_prompt() -> str:
    common = f"""Web3DGameBench external persistent-goal control ({_GOAL_CONTROL_VERSION}).
This control is supplied by the benchmark runner and is separate from TASK.md.
Persistent objective: {_GOAL_OBJECTIVE}
Keep working autonomously across context compaction until the game is implemented and npm run build succeeds.
Stop immediately after that successful build. Do not write or run browser automation, automated runtime checks, autopilots, or full playthroughs.
Runtime behavior, responsiveness, feature completeness, balance, polish, and game feel are evaluated after submission.
Keep TASK.md unmodified. Do not add this control to it or claim a build you did not run."""
    return common


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

    native_goal = True
    control_prompt = _control_prompt()
    if profile.harness == "codex":
        activation_method = "codex-app-server-thread-goal-set"
        evidence = "rpc:thread/goal/set"
    elif profile.harness == "claude-code":
        activation_method = "claude-code-native-slash-goal"
        evidence = "trace:goal-status"
    elif profile.harness == "pi":
        activation_method = "upstream-pi-goal-with-noninteractive-bridge"
        evidence = "trace:goal-state+web3dgamebench-lifecycle"
    else:
        raise ValueError(f"unsupported harness: {profile.harness}")

    receipt = {
        "schema_version": _RUNTIME_EVIDENCE_SCHEMA_VERSION,
        "control_version": _GOAL_CONTROL_VERSION,
        "mode": goal_mode,
        "completion": goal_completion,
        "harness": profile.harness,
        "activation_method": activation_method,
        "native_goal": native_goal,
        "lifecycle_observable": True,
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
            and event.get("status")
            in {"complete", "blocked", "interrupted", "timed_out"}
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
        for call in [*_native_goal_events(event), *_named_goal_tools(event)]:
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


def _native_goal_events(event: dict) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    if event.get("type") == "assistant":
        message = event.get("message")
        if isinstance(message, dict) and message.get("model") == "<synthetic>":
            for block in message.get("content", []):
                text = block.get("text") if isinstance(block, dict) else None
                if isinstance(text, str) and text.startswith("Goal set: "):
                    objective = text.removeprefix("Goal set: ")
                    found.append({"tool": "create_goal", "objective_sha256": _sha256_text(objective)})
    if event.get("type") == "result" and event.get("terminal_reason") in {"completed", "blocked"}:
        status = "complete" if event["terminal_reason"] == "completed" else "blocked"
        found.append({"tool": "update_goal", "status": status})
    if event.get("type") == "entry_appended":
        entry = event.get("entry")
        if (
            isinstance(entry, dict)
            and entry.get("customType") == "web3dgamebench-lifecycle"
        ):
            data = entry.get("data")
            status = data.get("status") if isinstance(data, dict) else None
            if status in {"complete", "blocked", "interrupted", "timed_out"}:
                found.append({"tool": "update_goal", "status": status})
        if isinstance(entry, dict) and entry.get("customType") == "goal-state":
            data = entry.get("data")
            goal = data.get("goal") if isinstance(data, dict) else None
            if isinstance(goal, dict):
                status = goal.get("status")
                objective = goal.get("text")
                if status == "active" and isinstance(objective, str):
                    found.append({"tool": "create_goal", "objective_sha256": _sha256_text(objective)})
                elif status in {"complete", "blocked"}:
                    found.append({"tool": "update_goal", "status": status})
    return found


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
        if name in {
            "create_goal",
            "get_goal",
            "update_goal",
            "benchmark_complete",
            "benchmark_blocked",
        }:
            normalized_name = {
                "benchmark_complete": "update_goal",
                "benchmark_blocked": "update_goal",
            }.get(name, name)
            item = {"tool": normalized_name}
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
            if name in {"benchmark_complete", "benchmark_blocked"}:
                item["status"] = (
                    "complete" if name == "benchmark_complete" else "blocked"
                )
            elif name == "update_goal" and isinstance(arguments, dict):
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
    task_sha256: str | None = None,
) -> Invocation:
    final_path = workspace / ".web3dgamebench-final.txt"
    control_prompt, goal_activation = _goal_activation(
        profile, prompt, goal_mode, goal_completion
    )
    candidate_prompt_sha256 = _sha256_text(prompt)
    if profile.harness == "codex":
        if not profile.effort:
            raise ValueError("Codex profiles require an explicit effort")
        argv = [
            "python3",
            "/usr/local/bin/web3dgamebench-codex-goal",
            "--cwd",
            str(workspace),
            "--model",
            profile.model,
            "--effort",
            profile.effort,
            "--objective",
            _GOAL_OBJECTIVE,
            "--developer-instructions",
            control_prompt or "",
            "--final",
            str(final_path),
        ]
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
            "--include-hook-events",
        ]
        if control_prompt:
            argv.extend(["--append-system-prompt", control_prompt])
        # The pilot intentionally omits --effort so Claude Code uses the official default.
        argv.append(f"/goal {_GOAL_OBJECTIVE}")
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
            "--no-context-files",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--tools",
            "read,bash,edit,write,grep,find,ls,goal_complete,goal_blocked,goal_wait",
            "--no-approve",
        ]
        if control_prompt:
            argv.extend(["--append-system-prompt", control_prompt])
        argv.append(f"/benchmark-goal {_GOAL_OBJECTIVE}")
        return Invocation(
            argv=tuple(argv),
            stdin_prompt=False,
            env=(
                {"WEB3DGAMEBENCH_TASK_SHA256": task_sha256}
                if task_sha256 is not None
                else {}
            ),
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
