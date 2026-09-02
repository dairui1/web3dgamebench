from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class TraceReplayError(RuntimeError):
    pass


_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;\"']+"),
    re.compile(
        r"(?i)([\"']?(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)"
        r"[\"']?\s*[:=]\s*[\"']?)"
        r"[^\s,;\"']+"
    ),
)


def _redact(value: str) -> str:
    text = value.replace(str(Path.home()), "~")
    prompt_marker = "Implement the complete benchmark task in TASK.md"
    if prompt_marker in text:
        text = text[: text.index(prompt_marker)] + "[candidate prompt omitted]"
    text = re.sub(
        r"(?i)([\"']data[\"']\s*:\s*[\"'])[A-Za-z0-9+/=]{200,}",
        r"\1[image data omitted]",
        text,
    )
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(r"\1[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


def _clip(value: Any, limit: int = 1600) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = _redact(text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) / 1000 if value > 10_000_000_000 else float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise TraceReplayError(f"invalid JSONL at {path}:{line_number}") from error
            if isinstance(event, dict):
                events.append(event)
    if not events:
        raise TraceReplayError(f"trace has no events: {path}")
    return events


def _event(
    kind: str,
    title: str,
    *,
    detail: Any = "",
    output: Any = "",
    status: str = "ok",
    tool: str | None = None,
    raw_timestamp: float | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": kind,
        "title": _clip(title, 140),
        "detail": _clip(detail),
        "status": status,
        "_timestamp": raw_timestamp,
    }
    clipped_output = _clip(output, 1200)
    if clipped_output:
        item["output"] = clipped_output
    if tool:
        item["tool"] = tool
    return item


def _tool_title(name: str, arguments: Any) -> str:
    lower_name = name.lower()
    data = arguments if isinstance(arguments, dict) else {}
    command = str(data.get("command") or data.get("cmd") or "")
    path = str(data.get("file_path") or data.get("path") or "")
    lower = command.lower()
    if "npm run build" in lower or re.search(r"\b(vite build|npm build)\b", lower):
        return "Run production build"
    if "tsc" in lower or "typecheck" in lower:
        return "Type-check project"
    if re.search(r"\b(pytest|npm test|node --test)\b", lower):
        return "Run tests"
    if any(token in lower for token in ("chromium", "playwright", "puppeteer", "screenshot", "cdp")):
        return "Inspect the game in a browser"
    if lower_name in {"write", "edit", "apply_patch"}:
        return f"{name.title()} {path or 'project files'}"
    if lower_name in {"read", "grep", "glob", "find", "ls"}:
        return f"Inspect {path or 'the workspace'}"
    if command:
        first = command.splitlines()[0].strip()
        return first[:96]
    return name.replace("_", " ").title()


def _candidate_input_read(arguments: Any) -> bool:
    text = json.dumps(arguments, ensure_ascii=False).lower()
    return "task.md" in text or "agents.md" in text


def _codex_events(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if any(event.get("method") for event in raw):
        return _codex_app_server_events(raw)
    output: list[dict[str, Any]] = []
    usage: Counter[str] = Counter()
    for raw_event in raw:
        event_type = raw_event.get("type")
        if event_type == "turn.completed":
            raw_usage = raw_event.get("usage") or {}
            usage.update(
                {
                    "inputTokens": int(raw_usage.get("input_tokens") or 0),
                    "outputTokens": int(raw_usage.get("output_tokens") or 0),
                    "reasoningTokens": int(raw_usage.get("reasoning_output_tokens") or 0),
                    "cachedTokens": int(raw_usage.get("cached_input_tokens") or 0),
                    "cacheWriteTokens": int(raw_usage.get("cache_creation_input_tokens") or 0),
                }
            )
            continue
        if event_type != "item.completed":
            continue
        item = raw_event.get("item") or {}
        item_type = item.get("type")
        if item_type == "agent_message":
            output.append(_event("message", "Agent update", detail=item.get("text")))
        elif item_type == "reasoning":
            output.append(_event("thought", "Reasoning summary", detail=item.get("text")))
        elif item_type == "command_execution":
            command = str(item.get("command") or "")
            failed = item.get("status") == "failed" or item.get("exit_code") not in (None, 0)
            output.append(
                _event(
                    "tool",
                    _tool_title("shell", {"command": command}),
                    detail=command,
                    output="" if _candidate_input_read(command) else item.get("aggregated_output"),
                    status="error" if failed else "ok",
                    tool="shell",
                )
            )
        elif item_type == "file_change":
            changes = item.get("changes") or []
            paths = [str(change.get("path", "")).replace("/workspace/", "") for change in changes]
            output.append(
                _event(
                    "change",
                    f"Changed {', '.join(paths[:3]) or 'project files'}",
                    detail=changes,
                    tool="edit",
                )
            )
        elif item_type == "todo_list":
            output.append(_event("plan", "Updated implementation plan", detail=item))
    return output, dict(usage)


def _codex_app_server_events(
    raw: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Normalize the JSON-RPC stream emitted by newer Codex app-server runs."""

    output: list[dict[str, Any]] = []
    usage: dict[str, int] = {}
    for raw_event in raw:
        method = raw_event.get("method")
        params = raw_event.get("params") or {}
        raw_timestamp = _timestamp(raw_event.get("emittedAtMs"))
        if method == "thread/tokenUsage/updated":
            total = (params.get("tokenUsage") or {}).get("total") or {}
            usage = {
                "inputTokens": int(total.get("inputTokens") or 0),
                "outputTokens": int(total.get("outputTokens") or 0),
                "reasoningTokens": int(total.get("reasoningOutputTokens") or 0),
                "cachedTokens": int(total.get("cachedInputTokens") or 0),
                "cacheWriteTokens": int(total.get("cacheWriteInputTokens") or 0),
            }
            continue
        if method != "item/completed":
            continue
        item = params.get("item") or {}
        item_type = item.get("type")
        if item_type == "agentMessage":
            message = str(item.get("text") or "").strip()
            if message:
                output.append(
                    _event("message", "Agent update", detail=message, raw_timestamp=raw_timestamp)
                )
        elif item_type == "reasoning":
            summary = item.get("summary") or []
            if summary:
                output.append(
                    _event("thought", "Reasoning summary", detail=summary, raw_timestamp=raw_timestamp)
                )
        elif item_type == "commandExecution":
            command = str(item.get("command") or "")
            failed = item.get("status") == "failed" or item.get("exitCode") not in (None, 0)
            output.append(
                _event(
                    "tool",
                    _tool_title("shell", {"command": command}),
                    detail=command,
                    output="" if _candidate_input_read(command) else item.get("aggregatedOutput"),
                    status="error" if failed else "ok",
                    tool="shell",
                    raw_timestamp=raw_timestamp,
                )
            )
        elif item_type == "fileChange":
            changes = item.get("changes") or []
            paths = [str(change.get("path", "")).replace("/workspace/", "") for change in changes]
            output.append(
                _event(
                    "change",
                    f"Changed {', '.join(paths[:3]) or 'project files'}",
                    detail=changes,
                    tool="edit",
                    raw_timestamp=raw_timestamp,
                )
            )
    return output, usage


def _claude_events(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    output: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    usage: Counter[str] = Counter()
    last_text = ""
    for raw_event in raw:
        event_type = raw_event.get("type")
        raw_timestamp = _timestamp(raw_event.get("timestamp"))
        if event_type == "assistant":
            message = raw_event.get("message") or {}
            for block in message.get("content") or []:
                block_type = block.get("type")
                if block_type == "thinking" and str(block.get("thinking") or "").strip():
                    output.append(
                        _event(
                            "thought",
                            "Reasoning checkpoint",
                            detail=block.get("thinking"),
                            raw_timestamp=raw_timestamp,
                        )
                    )
                elif block_type == "text" and str(block.get("text") or "").strip():
                    last_text = str(block.get("text"))
                    output.append(
                        _event(
                            "message",
                            "Agent update",
                            detail=last_text,
                            raw_timestamp=raw_timestamp,
                        )
                    )
                elif block_type == "tool_use":
                    name = str(block.get("name") or "tool")
                    arguments = block.get("input") or {}
                    item = _event(
                        "tool",
                        _tool_title(name, arguments),
                        detail=arguments,
                        tool=name,
                        raw_timestamp=raw_timestamp,
                    )
                    output.append(item)
                    item["_hideOutput"] = _candidate_input_read(arguments)
                    if block.get("id"):
                        tools[str(block["id"])] = item
        elif event_type == "user":
            message = raw_event.get("message") or {}
            for block in message.get("content") or []:
                if block.get("type") != "tool_result":
                    continue
                item = tools.get(str(block.get("tool_use_id") or ""))
                if item is None:
                    continue
                if not item.get("_hideOutput"):
                    item["output"] = _clip(block.get("content"), 1200)
                if block.get("is_error"):
                    item["status"] = "error"
        elif event_type == "result":
            raw_usage = raw_event.get("usage") or {}
            usage.update(
                {
                    "inputTokens": int(raw_usage.get("input_tokens") or 0),
                    "outputTokens": int(raw_usage.get("output_tokens") or 0),
                    "reasoningTokens": int(
                        (raw_usage.get("output_tokens_details") or {}).get("thinking_tokens") or 0
                    ),
                    "cachedTokens": int(raw_usage.get("cache_read_input_tokens") or 0),
                    "cacheWriteTokens": int(raw_usage.get("cache_creation_input_tokens") or 0),
                }
            )
            result_text = str(raw_event.get("result") or "").strip()
            if result_text and result_text != last_text:
                output.append(
                    _event(
                        "message",
                        "Final response",
                        detail=result_text,
                        status="error" if raw_event.get("is_error") else "ok",
                        raw_timestamp=raw_timestamp,
                    )
                )
    return output, dict(usage)


def _pi_events(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    output: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    usage: Counter[str] = Counter()
    for raw_event in raw:
        event_type = raw_event.get("type")
        raw_timestamp = _timestamp(raw_event.get("timestamp"))
        if event_type == "message_end":
            message = raw_event.get("message") or {}
            if message.get("role") != "assistant":
                continue
            raw_timestamp = _timestamp(message.get("timestamp")) or raw_timestamp
            raw_usage = message.get("usage") or {}
            usage.update(
                {
                    "inputTokens": int(raw_usage.get("input") or 0),
                    "outputTokens": int(raw_usage.get("output") or 0),
                    "reasoningTokens": int(raw_usage.get("reasoning") or 0),
                    "cachedTokens": int(raw_usage.get("cacheRead") or 0),
                    "cacheWriteTokens": int(raw_usage.get("cacheWrite") or 0),
                }
            )
            for block in message.get("content") or []:
                block_type = block.get("type")
                if block_type == "thinking" and str(block.get("thinking") or "").strip():
                    output.append(
                        _event(
                            "thought",
                            "Reasoning checkpoint",
                            detail=block.get("thinking"),
                            raw_timestamp=raw_timestamp,
                        )
                    )
                elif block_type == "text" and str(block.get("text") or "").strip():
                    output.append(
                        _event(
                            "message",
                            "Agent update",
                            detail=block.get("text"),
                            raw_timestamp=raw_timestamp,
                        )
                    )
                elif block_type == "toolCall":
                    name = str(block.get("name") or "tool")
                    arguments = block.get("arguments") or {}
                    item = _event(
                        "tool",
                        _tool_title(name, arguments),
                        detail=arguments,
                        tool=name,
                        raw_timestamp=raw_timestamp,
                    )
                    output.append(item)
                    item["_hideOutput"] = _candidate_input_read(arguments)
                    if block.get("id"):
                        tools[str(block["id"])] = item
        elif event_type == "tool_execution_start":
            call_id = str(raw_event.get("toolCallId") or "")
            if call_id and call_id not in tools:
                name = str(raw_event.get("toolName") or "tool")
                arguments = raw_event.get("args") or {}
                item = _event(
                    "tool",
                    _tool_title(name, arguments),
                    detail=arguments,
                    tool=name,
                    raw_timestamp=raw_timestamp,
                )
                output.append(item)
                item["_hideOutput"] = _candidate_input_read(arguments)
                tools[call_id] = item
        elif event_type == "tool_execution_end":
            item = tools.get(str(raw_event.get("toolCallId") or ""))
            if item is None:
                continue
            result = raw_event.get("result") or {}
            if not item.get("_hideOutput"):
                item["output"] = _clip(result.get("content") or result, 1200)
            if raw_event.get("isError") or result.get("isError"):
                item["status"] = "error"
        elif event_type in {"auto_retry_start", "agent_start"} and raw_event.get("error"):
            output.append(
                _event(
                    "error",
                    "Runtime retry",
                    detail=raw_event.get("error"),
                    status="error",
                    raw_timestamp=raw_timestamp,
                )
            )
    return output, dict(usage)


def _assign_times(events: list[dict[str, Any]], duration: float) -> None:
    if not events:
        return
    duration = max(duration, 1.0)
    known = [
        (index, float(event["_timestamp"]))
        for index, event in enumerate(events)
        if event.get("_timestamp") is not None
    ]
    if len(known) >= 2 and known[-1][1] > known[0][1]:
        start = known[0][1]
        span = known[-1][1] - start
        anchors = [(index, max(0.0, min(duration, (stamp - start) / span * duration))) for index, stamp in known]
        for index, event in enumerate(events):
            if event.get("_timestamp") is not None:
                event["atSeconds"] = next(value for anchor, value in anchors if anchor == index)
                continue
            previous = max((anchor for anchor in anchors if anchor[0] < index), default=(0, 0.0))
            following = min(
                (anchor for anchor in anchors if anchor[0] > index),
                default=(len(events) - 1, duration),
            )
            ratio = (index - previous[0]) / max(1, following[0] - previous[0])
            event["atSeconds"] = previous[1] + (following[1] - previous[1]) * ratio
    else:
        denominator = max(1, len(events) - 1)
        for index, event in enumerate(events):
            event["atSeconds"] = index / denominator * duration
    previous_time = 0.0
    for index, event in enumerate(events):
        at = max(previous_time, min(duration, float(event.get("atSeconds") or 0.0)))
        event["atSeconds"] = round(at, 3)
        event["id"] = f"e{index + 1}"
        event.pop("_timestamp", None)
        event.pop("_hideOutput", None)
        previous_time = at


def _phase_for(event: dict[str, Any], current: str) -> str:
    haystack = " ".join(
        str(event.get(key) or "") for key in ("title", "detail", "tool")
    ).lower()
    if event.get("status") == "error":
        return "debug"
    verification = any(
        token in haystack
        for token in ("browser", "screenshot", "npm run build", "production build", "type-check", "run tests")
    )
    if verification and current == "orient" and not any(
        token in haystack for token in ("screenshot", "npm run build", "production build", "type-check", "run tests")
    ):
        return current
    if verification:
        return "verify"
    if event.get("kind") == "change" or str(event.get("tool") or "").lower() in {
        "write",
        "edit",
        "apply_patch",
    }:
        return "build" if current in {"orient", "build"} else "refine"
    return current


def _chapters(events: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    if not events:
        return []
    phases: list[str] = []
    current = "orient"
    for index, event in enumerate(events):
        current = _phase_for(event, current)
        if index >= len(events) - 2 and event.get("kind") == "message":
            current = "finish"
        event["chapter"] = current
        phases.append(current)
    chapters: list[dict[str, Any]] = []
    start = 0
    for index in range(1, len(events) + 1):
        if index < len(events) and phases[index] == phases[start]:
            continue
        chapter_start = events[start]["atSeconds"]
        chapter_end = events[index]["atSeconds"] if index < len(events) else duration
        chapters.append(
            {
                "id": f"c{len(chapters) + 1}",
                "label": phases[start],
                "startSeconds": chapter_start,
                "endSeconds": max(chapter_start, round(chapter_end, 3)),
                "startEvent": start,
                "endEvent": index - 1,
            }
        )
        start = index
    return chapters


def build_trace_replay(run_root: Path) -> dict[str, Any]:
    manifest_path = run_root / "manifest.json"
    trace_path = run_root / "events.jsonl"
    if not manifest_path.is_file():
        raise TraceReplayError(f"run manifest not found: {manifest_path}")
    if not trace_path.is_file():
        raise TraceReplayError(f"runtime trace not found: {trace_path}")
    manifest = json.loads(manifest_path.read_text())
    raw = _read_events(trace_path)
    trace_format = str(manifest.get("trace_format") or "")
    if trace_format == "codex-jsonl-v1":
        events, usage = _codex_events(raw)
    elif trace_format == "claude-code-jsonl-v1":
        events, usage = _claude_events(raw)
    elif trace_format == "pi-jsonl-v1":
        events, usage = _pi_events(raw)
    else:
        raise TraceReplayError(f"unsupported trace format: {trace_format or 'missing'}")
    repair = manifest.get("repair")
    if isinstance(repair, dict) and repair.get("assisted") is True:
        events.append(
            _event(
                "change",
                "Assisted repair applied",
                detail={
                    "attempt": repair.get("attempt"),
                    "penaltyPoints": repair.get("penalty_points"),
                    "changes": repair.get("changes") or [],
                },
                tool="repair",
            )
        )
    if not events:
        raise TraceReplayError(f"trace produced no replay events: {trace_path}")

    duration = float(manifest.get("duration_seconds") or len(events))
    _assign_times(events, duration)
    chapters = _chapters(events, duration)
    profile = manifest.get("profile") or {}
    evaluation_path = run_root / "evaluation/report.json"
    evaluation: dict[str, Any] = {}
    if evaluation_path.is_file():
        raw_evaluation = json.loads(evaluation_path.read_text())
        evaluation = {
            "trusted": bool(raw_evaluation.get("trusted")),
            "passed": bool(raw_evaluation.get("passed")),
            "checks": [
                {"name": check.get("name"), "passed": bool(check.get("passed"))}
                for check in raw_evaluation.get("checks") or []
                if check.get("name")
            ],
        }
    kind_counts = Counter(str(event["kind"]) for event in events)
    tool_counts = Counter(str(event["tool"]) for event in events if event.get("tool"))
    errors = sum(1 for event in events if event.get("status") == "error")
    run_id = str(manifest.get("run_id") or run_root.name)
    digest = hashlib.sha256(trace_path.read_bytes()).hexdigest()
    return {
        "schemaVersion": 1,
        "id": run_id,
        "runId": run_id,
        "sourceDigest": digest,
        "generatedAt": datetime.now(UTC).isoformat(),
        "task": manifest.get("task") or {},
        "profile": {
            "id": profile.get("id"),
            "harness": profile.get("harness"),
            "model": manifest.get("model_resolved") or profile.get("model"),
            "effort": profile.get("effort"),
        },
        "status": manifest.get("status"),
        "createdAt": manifest.get("created_at"),
        "durationSeconds": round(duration, 3),
        "traceFormat": trace_format,
        "summary": {
            "eventCount": len(events),
            "toolCalls": sum(tool_counts.values()),
            "errors": errors,
            "kinds": dict(sorted(kind_counts.items())),
            "tools": [
                {"name": name, "count": count} for name, count in tool_counts.most_common(8)
            ],
            "usage": usage,
        },
        "evaluation": evaluation,
        "chapters": chapters,
        "events": events,
    }


def export_trace_replay(run_root: Path, destination: Path) -> dict[str, Any]:
    replay = build_trace_replay(run_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(replay, ensure_ascii=False, separators=(",", ":")) + "\n")
    return replay
