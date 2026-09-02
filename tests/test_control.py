from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import web3dgamebench.control as control_module
from web3dgamebench.control import MatrixSupervisor, StartRequest, create_control_app

ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _write_passed_gate(state: Path, plan: Path) -> None:
    plan_value = json.loads(plan.read_text(encoding="utf-8"))
    receipt = _write_json(
        state / "calibration/gate/receipt.json",
        {
            "calibration_id": "gate",
            "status": "passed",
            "plan_digest_sha256": plan_value.get("plan_digest_sha256"),
        },
    )
    _write_json(
        state / "calibration/latest.json",
        {
            "receipt": str(receipt),
            "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        },
    )


def test_control_app_is_local_token_guarded_and_lists_frozen_options(
    tmp_path: Path,
) -> None:
    plan = _write_json(
        tmp_path / "plans/plan.json",
        {
            "plan_id": "plan-1",
            "season": {"id": "season-1"},
            "plan_digest_sha256": "a" * 64,
        },
    )
    smoke = _write_json(
        tmp_path / "smoke/smoke-1/receipt.json",
        {
            "smoke_id": "smoke-1",
            "status": "passed",
            "backend": "harbor",
            "plan_digest_sha256": "a" * 64,
        },
    )
    _write_passed_gate(tmp_path, plan)
    app = create_control_app(ROOT, tmp_path)
    supervisor = app.state.supervisor

    index = next(
        route.endpoint for route in app.routes if getattr(route, "path", None) == "/"
    )
    page = index()
    assert "__CONTROL_TOKEN__" not in page.body.decode()
    state = supervisor.snapshot()
    assert state["controls"]["can_start"] is True
    assert state["options"]["plans"][0]["path"] == str(plan.resolve())
    assert state["options"]["smokes"][0]["path"] == str(smoke.resolve())
    assert len(supervisor.token) >= 32
    assert (tmp_path / "control/token").stat().st_mode & 0o077 == 0


def test_start_action_passes_only_managed_harbor_paths(tmp_path: Path) -> None:
    plan = _write_json(
        tmp_path / "plans/plan.json", {"plan_digest_sha256": "a" * 64}
    )
    smoke = _write_json(tmp_path / "smoke/smoke/receipt.json", {})
    _write_passed_gate(tmp_path, plan)
    app = create_control_app(ROOT, tmp_path)
    supervisor = app.state.supervisor
    captured: dict[str, object] = {}

    def capture(operation: str, argv: list[str], receipt: Path | None = None) -> None:
        captured.update(operation=operation, argv=argv, receipt=receipt)

    supervisor._spawn = capture
    supervisor.start(
        StartRequest(plan=str(plan), smoke_receipt=str(smoke), backend="harbor")
    )

    assert captured["operation"] == "matrix-start"
    assert "--backend" in captured["argv"]
    assert "harbor" in captured["argv"]
    with pytest.raises(ValueError, match="only starts trusted Harbor"):
        supervisor.start(
            StartRequest(plan=str(plan), smoke_receipt=str(smoke), backend="container")
        )


def test_pause_is_bound_to_canonical_matrix_and_interrupts_managed_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    supervisor = MatrixSupervisor(ROOT, tmp_path)
    _write_json(
        tmp_path / "matrices/canonical-season-1.json",
        {"matrix_id": "matrix-1", "receipt": str(tmp_path / "matrix.json")},
    )
    _write_json(
        tmp_path / "control/runner.json",
        {"status": "running", "pid": os.getpid(), "pgid": 4242},
    )
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(supervisor, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        control_module.os,
        "killpg",
        lambda pgid, signum: sent.append((pgid, signum)),
    )

    command = supervisor.pause()
    supervisor.interrupt()

    assert json.loads(command.read_text(encoding="utf-8"))["matrix_id"] == "matrix-1"
    assert sent == [(4242, control_module.signal.SIGINT)]


def test_file_endpoint_rejects_paths_outside_run_state(tmp_path: Path) -> None:
    supervisor = MatrixSupervisor(ROOT, tmp_path / "runs")

    with pytest.raises(ValueError, match="outside"):
        supervisor.tail(str(tmp_path / "secret.txt"))
