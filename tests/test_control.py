from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException

import web3dgamebench.control as control_module
from web3dgamebench.control import (
    InvalidateRequest,
    MatrixSupervisor,
    RetryRequest,
    _requeue_matrix_cells,
    StartRequest,
    create_control_app,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


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
    app = create_control_app(ROOT, tmp_path)
    supervisor = app.state.supervisor

    index = next(
        route.endpoint for route in app.routes if getattr(route, "path", None) == "/"
    )
    page = index()
    html = page.body.decode()
    assert "__CONTROL_TOKEN__" not in html
    assert 'id="sel-config"' in html
    assert 'id="sel-plan"' not in html
    assert 'id="sel-smoke"' not in html
    assert "技术详情" in html
    assert 'id="btn-invalidate"' in html
    assert 'id="btn-retry"' in html
    assert 'id="drawer-retry"' in html
    assert 'id="dlg-invalidate-reason"' in html
    state = supervisor.snapshot()
    assert state["controls"]["can_prepare"] is True
    assert state["controls"]["can_start"] is True
    assert state["options"]["plans"][0]["path"] == str(plan.resolve())
    assert state["options"]["smokes"][0]["path"] == str(smoke.resolve())
    assert len(supervisor.token) >= 32
    assert (tmp_path / "control/token").stat().st_mode & 0o077 == 0


def test_start_action_passes_only_managed_harbor_paths(tmp_path: Path) -> None:
    plan = _write_json(tmp_path / "plans/plan.json", {"plan_digest_sha256": "a" * 64})
    smoke = _write_json(tmp_path / "smoke/smoke/receipt.json", {})
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


def test_prepare_action_generates_a_fresh_season_one_plan_and_smoke(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    supervisor = MatrixSupervisor(ROOT, tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(supervisor, "_canonical", lambda: None)

    def capture(operation: str, argv: list[str], receipt: Path | None = None) -> None:
        captured.update(operation=operation, argv=argv, receipt=receipt)

    monkeypatch.setattr(supervisor, "_spawn", capture)
    supervisor.prepare()

    assert captured["operation"] == "matrix-prepare"
    assert captured["argv"][-3:] == ["prepare", "--season", "season-1"]
    assert captured["receipt"] is None

    monkeypatch.setattr(
        supervisor,
        "_canonical",
        lambda: {"season": "season-1", "matrix_id": "matrix-1"},
    )
    with pytest.raises(RuntimeError, match="already exists"):
        supervisor.prepare()


def test_retry_action_requeues_failed_cells_and_resumes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    supervisor = MatrixSupervisor(ROOT, tmp_path)
    receipt = _write_json(tmp_path / "matrix.json", {"status": "incomplete"})
    monkeypatch.setattr(
        supervisor,
        "_canonical",
        lambda: {"season": "season-1", "receipt": str(receipt)},
    )
    monkeypatch.setattr(supervisor, "_refresh_runner", lambda: {"status": "exited"})
    monkeypatch.setattr(
        control_module,
        "_requeue_matrix_cells",
        lambda path, cell_ids, requested_by: ["task::profile::a1"],
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        supervisor,
        "_spawn",
        lambda operation, argv, receipt=None: captured.update(
            operation=operation, argv=argv, receipt=receipt
        ),
    )

    assert supervisor.retry_failed() == ["task::profile::a1"]
    assert captured["operation"] == "matrix-retry"
    assert captured["receipt"] == receipt.resolve()
    assert "web3dgamebench.control_worker" in captured["argv"]
    assert captured["argv"][-2:] == ["--receipt", str(receipt.resolve())]


def test_retry_preserves_failed_attempt_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    receipt = {
        "season": "season-1",
        "status": "incomplete",
        "summary": {"candidate_failures": 1},
        "cells": [
            {
                "cell_id": "task::profile::a1",
                "status": "evidence-failure",
                "run": "/runs/recovery",
                "evaluation": "/runs/recovery/evaluation/report.json",
                "playable": False,
                "passed": False,
                "trusted": True,
                "evidence_failures": ["no canvas"],
                "recovery_attempts": [{"source_run": "/runs/original"}],
                "repair": {"assisted": True, "penalty_points": 100},
            }
        ],
    }
    written: dict[str, object] = {}
    monkeypatch.setattr(control_module, "load_matrix_receipt", lambda _path: receipt)
    monkeypatch.setattr(control_module, "_assert_canonical_matrix", lambda *_args: None)
    monkeypatch.setattr(
        control_module,
        "_write_receipt",
        lambda _path, value: written.update(value=value),
    )

    assert _requeue_matrix_cells(tmp_path / "matrix.json") == ["task::profile::a1"]
    cell = receipt["cells"][0]
    assert cell["status"] == "pending"
    assert cell["playable"] is None
    assert cell["previous_runs"] == ["/runs/original", "/runs/recovery"]
    assert cell["retry_history"][0]["repair"]["penalty_points"] == 100
    assert "run" not in cell
    assert "recovery_attempts" not in cell
    assert written["value"] is receipt


def test_retry_endpoint_is_token_guarded(monkeypatch, tmp_path: Path) -> None:
    app = create_control_app(ROOT, tmp_path)
    supervisor = app.state.supervisor
    monkeypatch.setattr(
        supervisor, "retry_failed", lambda _cell_ids: ["task::profile::a1"]
    )
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/api/actions/retry"
    )

    with pytest.raises(HTTPException, match="403"):
        endpoint(RetryRequest(), None)
    assert endpoint(RetryRequest(), supervisor.token) == {
        "status": "accepted",
        "cell_ids": ["task::profile::a1"],
        "count": 1,
    }


def test_managed_operations_restore_standard_tool_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    supervisor = MatrixSupervisor(ROOT, tmp_path)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    entries = supervisor._child_environment()["PATH"].split(os.pathsep)

    assert str(Path.home() / ".local/bin") in entries
    assert str(Path.home() / ".bun/bin") in entries
    assert "/usr/local/bin" in entries
    assert "/opt/homebrew/bin" in entries


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


def test_invalidate_preserves_audit_path_and_requires_an_idle_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    supervisor = MatrixSupervisor(ROOT, tmp_path)
    canonical = {
        "season": "season-1",
        "matrix_id": "matrix-1",
        "receipt": str(tmp_path / "matrix.json"),
    }
    marker = tmp_path / "matrices/invalidated-season-1-matrix-1.json"
    captured: dict[str, str] = {}
    monkeypatch.setattr(supervisor, "_canonical", lambda: canonical)
    monkeypatch.setattr(supervisor, "_refresh_runner", lambda: {"status": "exited"})

    def invalidate(season: str, *, reason: str) -> Path:
        captured.update(season=season, reason=reason)
        return marker

    monkeypatch.setattr(control_module, "invalidate_canonical_matrix", invalidate)

    assert supervisor.invalidate("  operator requested restart  ") == marker
    assert captured == {
        "season": "season-1",
        "reason": "operator requested restart",
    }
    event = json.loads(supervisor.events_path.read_text(encoding="utf-8"))
    assert event["action"] == "matrix-invalidated"
    assert event["marker"] == str(marker)

    monkeypatch.setattr(
        supervisor,
        "_refresh_runner",
        lambda: {"status": "running", "pid": os.getpid()},
    )
    monkeypatch.setattr(supervisor, "_pid_alive", lambda _pid: True)
    with pytest.raises(RuntimeError, match="must be interrupted"):
        supervisor.invalidate("restart")


def test_snapshot_exposes_invalidate_only_for_stopped_open_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    supervisor = MatrixSupervisor(ROOT, tmp_path)
    canonical = {
        "season": "season-1",
        "matrix_id": "matrix-1",
        "receipt": str(tmp_path / "matrix.json"),
    }
    receipt = {"status": "interrupted", "cells": []}
    monkeypatch.setattr(supervisor, "_canonical", lambda: canonical)
    monkeypatch.setattr(supervisor, "_refresh_runner", lambda: {"status": "exited"})
    monkeypatch.setattr(
        supervisor, "_receipt", lambda _canonical: (tmp_path / "matrix.json", receipt)
    )

    state = supervisor.snapshot()
    assert state["controls"]["can_invalidate"] is True

    receipt["status"] = "complete"
    state = supervisor.snapshot()
    assert state["controls"]["can_invalidate"] is False


def test_invalidate_action_is_token_guarded_and_returns_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = create_control_app(ROOT, tmp_path)
    supervisor = app.state.supervisor
    marker = tmp_path / "matrices/invalidated.json"
    captured: list[str] = []

    def invalidate(reason: str) -> Path:
        captured.append(reason)
        return marker

    monkeypatch.setattr(supervisor, "invalidate", invalidate)
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/api/actions/invalidate"
    )

    with pytest.raises(HTTPException, match="403"):
        endpoint(InvalidateRequest(reason="restart"), None)

    response = endpoint(InvalidateRequest(reason="restart"), supervisor.token)
    assert response == {"status": "invalidated", "marker": str(marker)}
    assert captured == ["restart"]


def test_file_endpoint_rejects_paths_outside_run_state(tmp_path: Path) -> None:
    supervisor = MatrixSupervisor(ROOT, tmp_path / "runs")

    with pytest.raises(ValueError, match="outside"):
        supervisor.tail(str(tmp_path / "secret.txt"))
