import json
from pathlib import Path

import pytest

from web3dgamebench.trace_replay import TraceReplayError, build_trace_replay


def write_run(tmp_path: Path, trace_format: str, events: list[dict]) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "trace-123",
                "created_at": "2026-08-31T00:00:00+00:00",
                "status": "candidate-complete",
                "duration_seconds": 120,
                "trace_format": trace_format,
                "task": {"id": "signal-drift"},
                "profile": {"id": "profile", "harness": "test", "model": "model"},
            }
        )
    )
    (run / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    return run


def test_codex_trace_is_normalized_and_redacted(tmp_path: Path) -> None:
    run = write_run(
        tmp_path,
        "codex-jsonl-v1",
        [
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "I will build the game."},
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "API_KEY=supersecret npm run build",
                    "aggregated_output": "done",
                    "exit_code": 0,
                    "status": "completed",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "sed -n '1,200p' TASK.md",
                    "aggregated_output": "sealed candidate prompt",
                    "exit_code": 0,
                    "status": "completed",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "ps aux",
                    "aggregated_output": "claude -p Implement the complete benchmark task in TASK.md secret prompt body",
                    "exit_code": 0,
                    "status": "completed",
                },
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        ],
    )

    replay = build_trace_replay(run)

    assert replay["summary"]["eventCount"] == 4
    assert replay["summary"]["usage"]["inputTokens"] == 100
    assert replay["events"][1]["title"] == "Run production build"
    assert "supersecret" not in json.dumps(replay)
    assert "sealed candidate prompt" not in json.dumps(replay)
    assert "secret prompt body" not in json.dumps(replay)
    assert replay["events"][0]["atSeconds"] == 0
    assert replay["events"][-1]["atSeconds"] == 120


def test_claude_tool_results_are_attached(tmp_path: Path) -> None:
    run = write_run(
        tmp_path,
        "claude-code-jsonl-v1",
        [
            {
                "type": "assistant",
                "timestamp": "2026-08-31T00:00:01Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "Bash",
                            "input": {"command": "npm test"},
                        }
                    ]
                },
            },
            {
                "type": "user",
                "timestamp": "2026-08-31T00:00:02Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-1",
                            "content": "12 passing",
                            "is_error": False,
                        }
                    ]
                },
            },
        ],
    )

    replay = build_trace_replay(run)

    assert replay["events"][0]["title"] == "Run tests"
    assert replay["events"][0]["output"] == "12 passing"


def test_empty_trace_is_rejected(tmp_path: Path) -> None:
    run = write_run(tmp_path, "pi-jsonl-v1", [])
    with pytest.raises(TraceReplayError, match="trace has no events"):
        build_trace_replay(run)


def test_builds_codex_app_server_replay(tmp_path: Path) -> None:
    run = write_run(
        tmp_path,
        "codex-jsonl-v1",
        [
            {
                "method": "item/completed",
                "params": {"item": {"type": "agentMessage", "text": "Starting work"}},
                "emittedAtMs": 1_700_000_000_000,
            },
            {
                "method": "item/completed",
                "params": {
                    "item": {
                        "type": "commandExecution",
                        "command": "/bin/sh -lc 'npm run build'",
                        "status": "completed",
                        "exitCode": 0,
                        "aggregatedOutput": "built",
                    }
                },
                "emittedAtMs": 1_700_000_010_000,
            },
            {
                "method": "thread/tokenUsage/updated",
                "params": {
                    "tokenUsage": {
                        "total": {
                            "inputTokens": 100,
                            "outputTokens": 20,
                            "reasoningOutputTokens": 3,
                            "cachedInputTokens": 40,
                        }
                    }
                },
                "emittedAtMs": 1_700_000_011_000,
            },
        ],
    )

    replay = build_trace_replay(run)

    assert [event["kind"] for event in replay["events"]] == ["message", "tool"]
    assert replay["events"][1]["title"] == "Run production build"
    assert replay["summary"]["usage"] == {
        "inputTokens": 100,
        "outputTokens": 20,
        "reasoningTokens": 3,
        "cachedTokens": 40,
        "cacheWriteTokens": 0,
    }
