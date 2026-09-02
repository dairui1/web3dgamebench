import json
from pathlib import Path

import pytest

from web3dgamebench.config import load_profiles
from web3dgamebench.fable_backfill import (
    _begin_attempt,
    _load_receipt,
    _new_receipt,
    _write_receipt,
    quota_deferred,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def season_plan() -> dict:
    return {
        "plan_digest_sha256": "a" * 64,
        "season": {
            "id": "season-1",
            "tasks": [f"task-{index}" for index in range(10)],
        },
    }


def test_fable_profile_is_optional_claude_lane(season_plan: dict) -> None:
    profile = load_profiles(ROOT)["claude-fable-default"]
    receipt = _new_receipt(Path("/tmp/core-plan.json"), season_plan, profile)

    assert profile.model == "claude-fable-5-1"
    assert receipt["policy"] == {
        "blocks_core_matrix": False,
        "quota_failure": "defer",
        "later_backfill": True,
        "task_order": "serial",
    }
    assert len(receipt["cells"]) == 10
    assert all(cell["status"] == "pending" for cell in receipt["cells"])


def test_fable_receipt_round_trip(tmp_path: Path, season_plan: dict) -> None:
    path = tmp_path / "fable.json"
    profile = load_profiles(ROOT)["claude-fable-default"]
    receipt = _new_receipt(Path("/tmp/core-plan.json"), season_plan, profile)
    _write_receipt(path, receipt)

    assert _load_receipt(path) == receipt


def test_quota_failure_is_deferred(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "events.jsonl").write_text(
        json.dumps(
            {
                "type": "result",
                "is_error": True,
                "result": "You've hit your session limit",
            }
        )
        + "\n"
    )

    assert quota_deferred(run_root) is True


def test_harbor_stderr_quota_failure_is_deferred(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "events.jsonl").write_text("", encoding="utf-8")
    (run_root / "stderr.log").write_text(
        "Claude Code session limit reached\n", encoding="utf-8"
    )

    assert quota_deferred(run_root) is True


def test_deferred_cell_starts_a_new_auditable_attempt() -> None:
    cell = {
        "attempt": 1,
        "run": "/private/runs/first",
        "status": "quota-deferred",
        "passed": False,
        "trusted": False,
    }

    _begin_attempt(cell)

    assert cell["attempt"] == 2
    assert cell["previous_runs"] == ["/private/runs/first"]
    assert cell["status"] == "running"
