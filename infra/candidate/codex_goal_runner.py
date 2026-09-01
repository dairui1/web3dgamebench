#!/usr/bin/env python3
"""Run one Codex app-server thread with a deterministically activated goal."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def emit(value: dict) -> None:
    print(json.dumps(value, separators=(",", ":")), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--developer-instructions", required=True)
    parser.add_argument("--final", required=True)
    args = parser.parse_args()
    prompt = sys.stdin.read()

    command = [
        "codex",
        "-c",
        'approval_policy="never"',
        "-c",
        'web_search="disabled"',
        "-c",
        "sandbox_workspace_write.network_access=true",
        "app-server",
        "--listen",
        "stdio://",
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    next_id = 1

    def request(method: str, params: dict) -> int:
        nonlocal next_id
        request_id = next_id
        next_id += 1
        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            + "\n"
        )
        process.stdin.flush()
        return request_id

    def wait_response(request_id: int) -> dict:
        for line in process.stdout:
            event = json.loads(line)
            emit(event)
            if event.get("id") == request_id:
                if "error" in event:
                    raise RuntimeError(json.dumps(event["error"], sort_keys=True))
                return event["result"]
        raise RuntimeError("Codex app-server closed before responding")

    initialize_id = request(
        "initialize",
        {
            "clientInfo": {
                "name": "web3dgamebench-goal-runner",
                "version": "1",
            },
            "capabilities": {"experimentalApi": True},
        },
    )
    wait_response(initialize_id)
    process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "initialized"}) + "\n")
    process.stdin.flush()

    thread_result = wait_response(
        request(
            "thread/start",
            {
                "cwd": args.cwd,
                "model": args.model,
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
                "developerInstructions": args.developer_instructions,
                "ephemeral": False,
                "experimentalRawEvents": True,
            },
        )
    )
    thread = thread_result["thread"]
    thread_id = thread["id"]
    emit(
        {
            "type": "web3dgamebench.goal",
            "tool": "create_goal",
            "arguments": {"objective": args.objective},
            "thread_id": thread_id,
            "model": thread.get("model", args.model),
        }
    )
    wait_response(
        request(
            "thread/goal/set",
            {"threadId": thread_id, "objective": args.objective, "status": "active"},
        )
    )
    wait_response(
        request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "model": args.model,
                "effort": args.effort,
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "dangerFullAccess"},
            },
        )
    )

    final_text = ""
    terminal_goal: str | None = None
    for line in process.stdout:
        event = json.loads(line)
        emit(event)
        method = event.get("method")
        params = event.get("params")
        if method == "item/completed" and isinstance(params, dict):
            item = params.get("item")
            if isinstance(item, dict) and item.get("type") == "agentMessage":
                text = item.get("text")
                if isinstance(text, str):
                    final_text = text
        if method == "thread/goal/updated" and isinstance(params, dict):
            goal = params.get("goal")
            if isinstance(goal, dict) and goal.get("status") in {"complete", "blocked"}:
                terminal_goal = goal["status"]
        if method == "turn/completed" and terminal_goal is not None:
            break

    Path(args.final).write_text(final_text, encoding="utf-8")
    process.terminate()
    process.wait(timeout=10)
    if terminal_goal is None:
        emit({"type": "web3dgamebench.goal_error", "error": "goal-not-terminal"})
        return 2
    emit(
        {
            "type": "web3dgamebench.goal",
            "tool": "update_goal",
            "arguments": {"status": terminal_goal},
            "thread_id": thread_id,
        }
    )
    return 0 if terminal_goal == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
