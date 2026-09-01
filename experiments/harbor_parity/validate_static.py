from __future__ import annotations

import argparse
import ast
import json
import subprocess
import tomllib
from pathlib import Path

from .adapter import EXPECTED_IMAGE_ID, HARBOR_COMMIT, TASK_ID, candidate_prompt, tree_digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--generated-task", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    generated = args.generated_task.resolve()
    checks: dict[str, bool] = {}

    season = tomllib.loads((source / "configs/seasons.toml").read_text())
    checks["second_season_task"] = season["seasons"]["season-1"]["tasks"][1] == TASK_ID
    task_config = tomllib.loads((generated / "task.toml").read_text())
    checks["harbor_task_name"] = task_config["task"]["name"] == "web3dgamebench/bombsite-retake-parity"
    checks["two_hour_cell_limit"] = task_config["agent"]["timeout_sec"] == 7200.0
    compose = (generated / "environment/docker-compose.yaml").read_text()
    checks["container_pid_boundary"] = "pids_limit: 1024" in compose and "init: true" in compose
    checks["instruction_exact"] = (generated / "instruction.md").read_text() == candidate_prompt(
        source / "tasks" / TASK_ID / "task" / "goal.en.md"
    )
    lock = json.loads((generated / "freeze-lock.json").read_text())
    checks["task_digest"] = lock["task_digest"] == tree_digest(source / "tasks" / TASK_ID / "task")
    checks["harbor_commit"] = lock["harbor_commit"] == HARBOR_COMMIT
    checks["harbor_version"] = lock["harbor_version"] == "0.22.0"
    checks["image_id"] = lock["candidate_image_id_observed"] == EXPECTED_IMAGE_ID
    checks["goal_assets"] = all(
        name in lock["runtime_assets"]
        for name in (
            "infra/candidate/codex_goal_runner.py",
            "infra/candidate/pi_goal_runner.ts",
            "src/web3dgamebench/runtimes.py",
        )
    )
    invocations = lock["original_invocations"]
    checks["three_invocations"] = set(invocations) == {
        "codex-sol-medium",
        "claude-sonnet-default",
        "pi-deepseek-v4-flash",
    }
    checks["native_goal_v2"] = all(
        item["goal"]["control_version"] == "web3dgamebench-native-goal-v2"
        and item["goal"]["native_goal"] is True
        for item in invocations.values()
    )
    ast.parse((Path(__file__).parent / "agents.py").read_text())
    ast.parse((Path(__file__).parent / "compare.py").read_text())
    checks["python_syntax"] = True
    result = subprocess.run(
        ["harbor", "run", "-p", str(generated), "-a", "nop", "--print-config"],
        capture_output=True,
        text=True,
        check=False,
    )
    checks["harbor_config_loads"] = result.returncode == 0
    output = {"checks": checks, "harbor_stderr": result.stderr.strip()}
    print(json.dumps(output, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
