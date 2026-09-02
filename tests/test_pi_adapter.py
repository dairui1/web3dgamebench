from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pi_goal_bridge_is_thin_and_uses_upstream_managed_run() -> None:
    source = (ROOT / "infra/candidate/pi_goal_runner.ts").read_text(encoding="utf-8")
    identity = json.loads(
        (ROOT / "infra/candidate/pi_goal_bridge.json").read_text(encoding="utf-8")
    )

    assert identity == {
        "adapter_version": "web3dgamebench-pi-goal-bridge-v1",
        "entrypoint": "pi_goal_runner.ts",
        "runtime_evidence_schema_version": 4,
        "upstream_package": "@narumitw/pi-goal",
        "upstream_version": "0.54.4",
    }
    assert 'pi.events.emit("pi-goal:start", { runId, objective })' in source
    assert "pi-goal:event:" in source
    assert 'pi.registerCommand("benchmark-goal"' in source
    assert "benchmark_complete" not in source
    assert "class GoalRuntime" not in source
    assert len(source.splitlines()) < 60
