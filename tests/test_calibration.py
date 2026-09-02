import hashlib
import json
from pathlib import Path

import pytest

from web3dgamebench.calibration import (
    CalibrationError,
    load_calibration_gate,
    require_calibration_gate,
    run_calibration,
)


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return path


def test_gate_is_digest_bound_to_the_selected_plan(tmp_path: Path) -> None:
    plan = _write_json(tmp_path / "plans/plan.json", {"plan_digest_sha256": "a" * 64})
    receipt = _write_json(
        tmp_path / "calibration/gate/receipt.json",
        {"status": "passed", "plan_digest_sha256": "a" * 64},
    )
    _write_json(
        tmp_path / "calibration/latest.json",
        {
            "receipt": str(receipt),
            "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        },
    )

    assert require_calibration_gate(plan, directory=tmp_path)["status"] == "passed"

    plan.write_text(json.dumps({"plan_digest_sha256": "b" * 64}), encoding="utf-8")
    with pytest.raises(CalibrationError, match="different frozen plan"):
        require_calibration_gate(plan, directory=tmp_path)


def test_gate_rejects_mutated_receipt(tmp_path: Path) -> None:
    receipt = _write_json(tmp_path / "calibration/gate/receipt.json", {"status": "passed"})
    _write_json(
        tmp_path / "calibration/latest.json",
        {"receipt": str(receipt), "receipt_sha256": "0" * 64},
    )

    assert load_calibration_gate(tmp_path) is None


def test_calibration_stops_after_first_failed_task(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "configs").mkdir(parents=True)
    (root / "configs/calibration.toml").write_text(
        """[calibration]
season = "season-1"
profile = "pi-deepseek-v4-flash"
backend = "harbor"
tasks = ["first", "second", "third"]

[calibration.baselines.first]
passed_checks = 1
[calibration.baselines.second]
passed_checks = 1
[calibration.baselines.third]
passed_checks = 1
""",
        encoding="utf-8",
    )
    plan = _write_json(
        tmp_path / "plan.json",
        {"season": {"id": "season-1"}, "plan_digest_sha256": "a" * 64},
    )
    calls: list[str] = []

    def fake_run_once(_root, task, _profile, **_kwargs):
        calls.append(task)
        run = tmp_path / "runs" / task
        run.mkdir(parents=True)
        return run

    monkeypatch.setattr("web3dgamebench.calibration.runs_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(
        "web3dgamebench.calibration._watchdog_probe", lambda: {"passed": True}
    )
    monkeypatch.setattr("web3dgamebench.calibration.run_once", fake_run_once)
    monkeypatch.setattr(
        "web3dgamebench.calibration._task_result",
        lambda task, _run, _baseline: {"task": task, "status": "failed"},
    )

    receipt_path = run_calibration(root, plan)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert calls == ["first"]
    assert receipt["status"] == "failed"
    assert [item["task"] for item in receipt["tasks"]] == ["first"]
