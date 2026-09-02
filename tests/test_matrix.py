import copy
import hashlib
import json
import shutil
import threading
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

import web3dgamebench.matrix as matrix_module
from web3dgamebench.artifacts import file_tree_sha256
from web3dgamebench.cli import build_parser, command_doctor
from web3dgamebench.config import load_profiles
from web3dgamebench.matrix import (
    MatrixError,
    MatrixInterrupted,
    MatrixLockedError,
    PlanDriftError,
    SeasonLock,
    _barrier_pause_requested,
    _load_vendor_locks,
    _new_receipt,
    _write_receipt,
    close_run_artifacts,
    create_preflight_plan,
    load_matrix_receipt,
    load_preflight_plan,
    matrix_control_path,
    request_matrix_pause,
    resume_matrix,
    start_matrix,
    trusted_cell_gate,
    validate_closed_receipt,
    verify_frozen_inputs,
    verify_plan_digest,
    verify_run_artifacts,
    write_preflight_plan,
)
from web3dgamebench.runtimes import build_invocation

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def season_plan() -> dict:
    return create_preflight_plan(ROOT, "season-1")


@pytest.fixture
def plan_path(tmp_path: Path, season_plan: dict) -> Path:
    return write_preflight_plan(tmp_path / "season-1-plan.json", season_plan)


def test_preflight_plan_freezes_all_eighty_cells_and_runtime_inputs(
    season_plan: dict,
) -> None:
    assert len(season_plan["cells"]) == 80
    assert len({cell["cell_id"] for cell in season_plan["cells"]}) == 80
    assert season_plan["runtime_control"]["candidate_total_timeout_seconds"] == 5400
    assert season_plan["runtime_control"]["candidate_pids_limit"] == 1024
    assert season_plan["runtime_control"]["task_order"] == "serial"
    assert season_plan["runtime_control"]["harness_order"] == "parallel"
    assert season_plan["runtime_control"]["models_within_harness"] == "serial"
    assert season_plan["runtime_control"]["resume_supported"] is True
    assert season_plan["runtime_environment"]["container_images"]["candidate"][
        "id"
    ].startswith("sha256:")
    assert season_plan["runtime_environment"]["container_images"]["evaluator"][
        "id"
    ].startswith("sha256:")
    versions = season_plan["runtime_environment"]["candidate_toolchain"]["versions"]
    assert set(versions) == {
        "codex",
        "claude",
        "pi",
        "pi_goal_upstream",
        "pi_adapter",
        "node",
        "npm",
    }
    assert versions["pi_goal_upstream"] == "0.54.4"
    assert versions["pi_adapter"] == "web3dgamebench-pi-goal-bridge-v1"
    assert season_plan["runtime_control"]["pi_adapter"] == {
        "version": "web3dgamebench-pi-goal-bridge-v1",
        "upstream_pi_goal_version": "0.54.4",
        "runtime_evidence_schema_version": 4,
    }
    assert all(versions.values())
    capabilities = season_plan["runtime_environment"]["candidate_toolchain"]["capabilities"]
    assert capabilities["codex_features"]["goals"] == "goals stable true"
    assert len(capabilities["codex_features"]["output_sha256"]) == 64
    assert len(season_plan["plan_digest_sha256"]) == 64

    frozen = season_plan["frozen_inputs"]["files"]
    assert frozen["uv.lock"]["roles"] == ["host-dependency-lock"]
    assert frozen["src/web3dgamebench/control.py"]["roles"] == ["matrix-operator-runtime"]
    assert frozen["src/web3dgamebench/control_ui/app.js"]["roles"] == ["matrix-operator-ui"]
    assert frozen["src/web3dgamebench/fable_backfill.py"]["roles"] == [
        "optional-backfill-runtime"
    ]
    for task_id, task in season_plan["tasks"].items():
        assert task["brief_path"] in frozen
        assert task["starter_lock_path"] in frozen
        assert task["runtime_contract_path"] in frozen
        assert task["judge_prompt_path"] in frozen
        assert task["judge_rubric_path"] in frozen
        assert task["id"] == task_id


def test_vendor_manifest_covers_each_starter_path_not_only_shared_digest() -> None:
    locks = _load_vendor_locks(ROOT)
    season_starters = {
        f"tasks/{task_id}/task/starter"
        for task_id in (
            "canyon-strike",
            "bombsite-retake",
            "first-night",
            "village-quest",
            "ashen-duel",
            "linked-chamber",
            "star-course",
            "turbo-circuit",
            "frontier-command",
            "dinner-rush",
        )
    }
    assert season_starters.issubset(locks)
    assert len({locks[path] for path in season_starters}) == 1


def test_plan_write_is_immutable_and_digest_checked(
    tmp_path: Path, season_plan: dict
) -> None:
    path = write_preflight_plan(tmp_path / "plan.json", season_plan)
    assert load_preflight_plan(path) == season_plan
    assert path.stat().st_mode & 0o222 == 0
    with pytest.raises(MatrixError, match="already exists"):
        write_preflight_plan(path, season_plan)

    mutated = copy.deepcopy(season_plan)
    mutated["cells"][0]["attempt"] = 99
    with pytest.raises(PlanDriftError, match="digest mismatch"):
        verify_plan_digest(mutated)


def test_frozen_input_drift_stops_execution(
    monkeypatch: pytest.MonkeyPatch, season_plan: dict
) -> None:
    monkeypatch.setattr(
        matrix_module,
        "_runtime_environment",
        lambda _root: season_plan["runtime_environment"],
    )
    original = matrix_module._file_sha256

    def drifted(path: Path) -> str:
        if path == ROOT / "configs/seasons.toml":
            return "0" * 64
        return original(path)

    monkeypatch.setattr(matrix_module, "_file_sha256", drifted)
    with pytest.raises(PlanDriftError, match="frozen input changed"):
        verify_frozen_inputs(ROOT, season_plan)


def test_runtime_fingerprint_drift_stops_execution(
    monkeypatch: pytest.MonkeyPatch, season_plan: dict
) -> None:
    drifted = copy.deepcopy(season_plan["runtime_environment"])
    drifted["container_images"]["candidate"]["id"] = "sha256:" + "0" * 64
    monkeypatch.setattr(matrix_module, "_runtime_environment", lambda _root: drifted)
    with pytest.raises(PlanDriftError, match="toolchain changed"):
        verify_frozen_inputs(ROOT, season_plan)


def test_season_lock_rejects_concurrent_matrix(tmp_path: Path) -> None:
    with (
        SeasonLock("season-1", tmp_path),
        pytest.raises(MatrixLockedError, match="already running"),
        SeasonLock("season-1", tmp_path),
    ):
        pass
    with SeasonLock("season-1", tmp_path):
        pass


def test_dynamic_pause_is_acknowledged_once_at_task_barrier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path))
    receipt = {"matrix_id": "season-1-test", "execution_window": {}}

    command = request_matrix_pause("season-1-test", requested_by="test")

    assert command == matrix_control_path("season-1-test")
    assert _barrier_pause_requested(receipt, "canyon-strike") is True
    assert _barrier_pause_requested(receipt, "bombsite-retake") is False
    acknowledged = json.loads(command.read_text(encoding="utf-8"))
    assert acknowledged["stopped_at_task_barrier"] == "canyon-strike"
    assert acknowledged["acknowledged_at"]
    assert receipt["execution_window"]["stopped_at_task_barrier"] == "canyon-strike"


def test_season_one_canonical_matrix_cannot_be_replaced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan_path: Path,
    season_plan: dict,
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    first = _new_receipt(plan_path, season_plan, "container")
    second = _new_receipt(plan_path, season_plan, "container")
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first["receipt_path"] = str(first_path.resolve())
    second["receipt_path"] = str(second_path.resolve())
    _terminalize(first)
    first.update(status="complete", completed_at="2026-08-31T00:00:00+00:00")
    _write_receipt(first_path, first)
    _write_receipt(second_path, second)
    monkeypatch.setattr(matrix_module, "verify_run_artifacts", lambda *_args: None)

    matrix_module._claim_canonical_matrix("season-1", first_path, first)
    with pytest.raises(MatrixError, match="already has a canonical matrix"):
        matrix_module._claim_canonical_matrix("season-1", second_path, second)
    matrix_module._assert_canonical_matrix("season-1", first_path, first)
    matrix_module._seal_canonical_matrix("season-1", first_path, first)
    matrix_module._verify_canonical_publication_receipt(first)
    with pytest.raises(MatrixError, match="not the canonical"):
        matrix_module._assert_canonical_matrix("season-1", second_path, second)
    with pytest.raises(MatrixError, match="not the canonical"):
        matrix_module._verify_canonical_publication_receipt(second)

    first["completed_at"] = "2026-08-31T00:00:01+00:00"
    _write_receipt(first_path, first)
    with pytest.raises(MatrixError, match="closure does not match"):
        matrix_module._verify_canonical_publication_receipt(first)


def test_unclosed_canonical_matrix_can_be_auditably_invalidated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan_path: Path,
    season_plan: dict,
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(runs))
    first = _new_receipt(plan_path, season_plan, "container")
    first_path = runs / "first.json"
    first["receipt_path"] = str(first_path.resolve())
    _write_receipt(first_path, first)
    matrix_module._claim_canonical_matrix("season-1", first_path, first)

    marker_path = matrix_module.invalidate_canonical_matrix(
        "season-1", reason="native goal activation was not wired"
    )

    marker = json.loads(marker_path.read_text())
    invalidated = matrix_module._load_receipt(first_path)
    assert marker["matrix_id"] == first["matrix_id"]
    assert Path(marker["claim"]).is_file()
    assert invalidated["status"] == "invalidated"
    assert invalidated["invalidation"]["marker"] == str(marker_path.resolve())
    assert not matrix_module._canonical_matrix_path("season-1").exists()

    second = _new_receipt(plan_path, season_plan, "container")
    second_path = runs / "second.json"
    second["receipt_path"] = str(second_path.resolve())
    _write_receipt(second_path, second)
    matrix_module._claim_canonical_matrix("season-1", second_path, second)
    matrix_module._assert_canonical_matrix("season-1", second_path, second)


def test_closed_canonical_matrix_cannot_be_invalidated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan_path: Path,
    season_plan: dict,
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(runs))
    receipt = _new_receipt(plan_path, season_plan, "container")
    receipt_path = runs / "receipt.json"
    receipt["receipt_path"] = str(receipt_path.resolve())
    _write_receipt(receipt_path, receipt)
    matrix_module._claim_canonical_matrix("season-1", receipt_path, receipt)
    closure = matrix_module._canonical_closure_path("season-1")
    closure.parent.mkdir(parents=True, exist_ok=True)
    closure.write_text("{}\n")

    with pytest.raises(MatrixError, match="closed canonical"):
        matrix_module.invalidate_canonical_matrix("season-1", reason="not allowed")


def test_run_closure_detects_post_matrix_artifact_changes(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "evaluation").mkdir(parents=True)
    (run / "render/dist").mkdir(parents=True)
    for name, content in (
        ("manifest.json", "{}"),
        ("events.jsonl", "{}\n"),
        ("stderr.log", ""),
        ("evaluation/report.json", "{}"),
        ("render/src.ts", "source"),
        ("render/dist/index.html", "playable"),
    ):
        (run / name).write_text(content, encoding="utf-8")

    closure = close_run_artifacts(run)
    verify_run_artifacts(run, closure)
    (run / "events.jsonl").write_text("changed\n", encoding="utf-8")

    with pytest.raises(MatrixError, match="artifacts changed"):
        verify_run_artifacts(run, closure)


def test_publication_rechecks_failed_cell_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan_path: Path,
    season_plan: dict,
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    receipt_path = tmp_path / "receipt.json"
    receipt = _new_receipt(plan_path, season_plan, "container")
    _terminalize(receipt)
    failed = receipt["cells"][0]
    failed.update(status="candidate-failure", passed=False, trusted=False)
    receipt.update(
        status="complete",
        receipt_path=str(receipt_path.resolve()),
    )
    _write_receipt(receipt_path, receipt)
    matrix_module._claim_canonical_matrix("season-1", receipt_path, receipt)

    checked: list[str] = []
    monkeypatch.setattr(matrix_module, "_verify_plan_file", lambda *_args: season_plan)
    monkeypatch.setattr(matrix_module, "verify_frozen_inputs", lambda *_args: None)
    monkeypatch.setattr(
        matrix_module,
        "verify_run_artifacts",
        lambda run_root, _artifacts: checked.append(run_root.name),
    )
    matrix_module._seal_canonical_matrix("season-1", receipt_path, receipt)
    checked.clear()
    monkeypatch.setattr(matrix_module, "_candidate_manifest", lambda _run: {})
    monkeypatch.setattr(matrix_module, "_evaluation_report", lambda _path: {})
    monkeypatch.setattr(matrix_module, "trusted_cell_gate", lambda *_args: (True, []))

    matrix_module.validate_publication_receipt(ROOT, receipt)

    assert len(checked) == 80
    assert Path(failed["run"]).name in checked


def test_receipt_is_prefilled_with_all_cells_and_separate_judge_state(
    plan_path: Path, season_plan: dict
) -> None:
    receipt = _new_receipt(plan_path, season_plan, "container")
    assert receipt["plan_digest_sha256"] == season_plan["plan_digest_sha256"]
    assert len(receipt["cells"]) == 80
    assert all(cell["status"] == "pending" for cell in receipt["cells"])
    assert all(cell["run"] is None for cell in receipt["cells"])
    assert all(cell["passed"] is False for cell in receipt["cells"])
    assert all(cell["trusted"] is False for cell in receipt["cells"])
    assert all(cell["judge"] == {"status": "not-run"} for cell in receipt["cells"])


def _trusted_evidence(
    season_plan: dict,
    profile_id: str,
    run_root: Path,
) -> tuple[dict, dict, dict]:
    cell = next(
        cell
        for cell in season_plan["cells"]
        if cell["task"] == "canyon-strike" and cell["profile"] == profile_id
    )
    task = season_plan["tasks"][cell["task"]]
    profile = season_plan["profiles"][profile_id]
    workspace = run_root / "workspace"
    workspace.mkdir(parents=True)
    shutil.copy2(ROOT / task["brief_path"], workspace / "TASK.md")

    invocation = build_invocation(
        load_profiles(ROOT)[profile_id],
        Path("/workspace"),
        "candidate prompt",
        isolation="container",
        goal_mode=task["goal_mode"],
        goal_completion=task["goal_completion"],
    )
    assert invocation.goal_activation is not None
    goal = asdict(invocation.goal_activation)
    lifecycle = [
        {
            "tool": "create_goal",
            "objective_sha256": goal["objective_sha256"],
        },
        {"tool": "update_goal", "status": "complete"},
    ]
    goal.update(
        {
            "activation_status": "observed-complete",
            "lifecycle": lifecycle,
        }
    )
    manifest = {
        "status": "candidate-complete",
        "task": {
            "id": cell["task"],
            "digest": task["task_tree_sha256"],
            "brief_sha256": task["brief_sha256"],
        },
        "profile": profile,
        "attempt": cell["attempt"],
        "prompt": {
            "candidate_sha256": invocation.candidate_prompt_sha256,
            "task_brief_preserved": True,
        },
        "goal": goal,
        "model_resolved": profile["model"],
        "backend": "container",
        "container_plane": {
            "image_digest": season_plan["runtime_environment"]["container_images"][
                "candidate"
            ]["id"]
        },
    }
    frozen = season_plan["frozen_inputs"]["files"]
    report = {
        "passed": True,
        "trusted": True,
        "evaluator": {
            "runtime_contract_sha256": task["runtime_contract_sha256"],
            "script_sha256": frozen["infra/evaluator/evaluate.py"]["sha256"],
            "runtime_schema_sha256": frozen["src/web3dgamebench/runtime_schema.py"][
                "sha256"
            ],
        },
    }
    return cell, manifest, report


@pytest.mark.parametrize(
    "profile_id",
    ["codex-sol-medium", "claude-sonnet-default", "pi-deepseek-v4-flash"],
)
def test_trusted_gate_accepts_only_harness_appropriate_goal_evidence(
    tmp_path: Path, season_plan: dict, profile_id: str
) -> None:
    run_root = tmp_path / profile_id
    cell, manifest, report = _trusted_evidence(season_plan, profile_id, run_root)
    assert trusted_cell_gate(season_plan, cell, manifest, report, run_root) == (True, [])


def test_trusted_gate_rejects_missing_task_goal_and_model_evidence(
    tmp_path: Path, season_plan: dict
) -> None:
    run_root = tmp_path / "run"
    cell, manifest, report = _trusted_evidence(season_plan, "codex-sol-medium", run_root)
    manifest["model_resolved"] = "gpt-5.6"
    manifest["prompt"]["task_brief_preserved"] = False
    manifest["goal"]["activation_status"] = "configured"

    trusted, failures = trusted_cell_gate(season_plan, cell, manifest, report, run_root)

    assert trusted is False
    assert "resolved model is incompatible with the profile" in failures
    assert "workspace TASK.md was not preserved" in failures
    assert "codex goal lifecycle did not complete" in failures


def test_trusted_gate_accepts_harbor_only_with_bound_adapter_provenance(
    tmp_path: Path, season_plan: dict
) -> None:
    run_root = tmp_path / "harbor-run"
    cell, manifest, report = _trusted_evidence(season_plan, "codex-sol-medium", run_root)
    task = season_plan["tasks"][cell["task"]]
    planned_harbor = season_plan["runtime_environment"]["harbor"]
    generated_task = run_root / "harbor/task" / cell["task"]
    generated_task.mkdir(parents=True)
    (generated_task / "task.toml").write_text("frozen", encoding="utf-8")
    job_root = run_root / "harbor/jobs/job"
    trial_root = job_root / "trial"
    trial_root.mkdir(parents=True)
    (job_root / "result.json").write_text("{}", encoding="utf-8")
    (trial_root / "result.json").write_text("{}", encoding="utf-8")
    adapter_lock = {
        "schema_version": 1,
        "task": cell["task"],
        "profile": cell["profile"],
        "brief_sha256": task["brief_sha256"],
        "harbor_version": planned_harbor["version"],
        "harbor_commit": planned_harbor["commit"],
        "generated_task_sha256": file_tree_sha256(generated_task),
    }
    adapter_path = run_root / "harbor-task-lock.json"
    adapter_path.write_text(json.dumps(adapter_lock), encoding="utf-8")
    (run_root / "harbor.json").write_text(
        json.dumps(
            {
                "version": planned_harbor["version"],
                "commit": planned_harbor["commit"],
                "exception": None,
                "task_checksum": "checksum",
                "job": str(job_root),
                "trial": str(trial_root),
                "trial_result_sha256": hashlib.sha256(
                    (trial_root / "result.json").read_bytes()
                ).hexdigest(),
                "job_result_sha256": hashlib.sha256(
                    (job_root / "result.json").read_bytes()
                ).hexdigest(),
                "adapter_lock_sha256": hashlib.sha256(
                    adapter_path.read_bytes()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    manifest["backend"] = "harbor"
    manifest["container_plane"].update(
        execution_backend="harbor-docker",
        harbor_version=planned_harbor["version"],
        harbor_commit=planned_harbor["commit"],
    )

    assert trusted_cell_gate(season_plan, cell, manifest, report, run_root) == (
        True,
        [],
    )

    harbor = json.loads((run_root / "harbor.json").read_text(encoding="utf-8"))
    harbor["exception"] = {"type": "AgentTimeoutError"}
    (run_root / "harbor.json").write_text(json.dumps(harbor), encoding="utf-8")
    trusted, failures = trusted_cell_gate(season_plan, cell, manifest, report, run_root)
    assert trusted is False
    assert "Harbor execution provenance is missing or inconsistent" in failures


def _terminalize(receipt: dict) -> None:
    artifacts = {
        "schema_version": 1,
        "files": {
            "manifest.json": "0" * 64,
            "events.jsonl": "1" * 64,
            "stderr.log": "2" * 64,
            "evaluation/report.json": "3" * 64,
        },
        "render_source_sha256": "4" * 64,
        "render_dist_sha256": "5" * 64,
    }
    for cell in receipt["cells"]:
        cell.update(
            {
                "status": "completed",
                "run": f"/runs/{cell['cell_id']}",
                "passed": True,
                "trusted": True,
                "artifacts": copy.deepcopy(artifacts),
            }
        )


def test_resume_only_runs_resumable_cells(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan_path: Path,
    season_plan: dict,
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    receipt_path = tmp_path / "receipt.json"
    receipt = _new_receipt(plan_path, season_plan, "container")
    _terminalize(receipt)
    receipt["cells"][1].update(status="candidate-failure", passed=False, trusted=False)
    receipt["cells"][2].update(status="evidence-failure", passed=False, trusted=False)
    for index, status in ((3, "pending"), (4, "infrastructure-error"), (5, "interrupted")):
        receipt["cells"][index].update(status=status, passed=False, trusted=False)
    receipt["status"] = "interrupted"
    _write_receipt(receipt_path, receipt)
    matrix_module._claim_canonical_matrix("season-1", receipt_path, receipt)

    called: list[str] = []

    def execute(_root, _plan, _receipt_path, _receipt, cell, _cancel_event=None):
        called.append(cell["cell_id"])
        cell.update(
            status="completed",
            run=f"/runs/{cell['cell_id']}",
            passed=True,
            trusted=True,
            artifacts=copy.deepcopy(receipt["cells"][0]["artifacts"]),
        )

    monkeypatch.setattr(matrix_module, "_verify_plan_file", lambda *_args: season_plan)
    monkeypatch.setattr(matrix_module, "verify_frozen_inputs", lambda *_args: None)
    monkeypatch.setattr(matrix_module, "verify_run_artifacts", lambda *_args: None)
    monkeypatch.setattr(matrix_module, "_execute_cell", execute)

    assert resume_matrix(ROOT, receipt_path) == receipt_path
    closed = load_matrix_receipt(receipt_path)
    assert set(called) == {receipt["cells"][index]["cell_id"] for index in (3, 4, 5)}
    assert closed["status"] == "complete"
    assert validate_closed_receipt(closed) is closed


def test_matrix_runs_harnesses_in_parallel_models_serially_with_task_barriers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan_path: Path,
    season_plan: dict,
) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt = _new_receipt(plan_path, season_plan, "container")
    _terminalize(receipt)
    first_two_tasks = receipt["cells"][:16]
    for cell in first_two_tasks:
        cell.update(status="pending", run=None, passed=False, trusted=False)

    condition = threading.Condition()
    profiles = load_profiles(ROOT)
    first_started = 0
    first_finished = 0
    second_saw_finished: list[int] = []
    active_by_harness = {"codex": 0, "claude-code": 0, "pi": 0}
    maximum_by_harness = {"codex": 0, "claude-code": 0, "pi": 0}
    start_order = {"codex": [], "claude-code": [], "pi": []}

    def execute(_root, _plan, _receipt_path, _receipt, cell, _cancel_event=None):
        nonlocal first_started, first_finished
        harness = profiles[cell["profile"]].harness
        if cell["task"] == "canyon-strike":
            with condition:
                first_started += 1
                active_by_harness[harness] += 1
                maximum_by_harness[harness] = max(
                    maximum_by_harness[harness], active_by_harness[harness]
                )
                start_order[harness].append(cell["profile"])
                condition.notify_all()
                assert condition.wait_for(lambda: first_started >= 3, timeout=2)
                active_by_harness[harness] -= 1
                first_finished += 1
        else:
            with condition:
                second_saw_finished.append(first_finished)
        cell.update(
            status="completed",
            run=f"/runs/{cell['cell_id']}",
            passed=True,
            trusted=True,
            artifacts=copy.deepcopy(receipt["cells"][16]["artifacts"]),
        )

    monkeypatch.setattr(matrix_module, "_verify_plan_file", lambda *_args: season_plan)
    monkeypatch.setattr(matrix_module, "verify_frozen_inputs", lambda *_args: None)
    monkeypatch.setattr(matrix_module, "_execute_cell", execute)

    matrix_module._drive_matrix(ROOT, plan_path, season_plan, receipt_path, receipt)

    assert first_started == 8
    assert maximum_by_harness == {"codex": 1, "claude-code": 1, "pi": 1}
    assert start_order == {
        "codex": ["codex-sol-medium", "codex-terra-high", "codex-luna-max"],
        "claude-code": ["claude-sonnet-default", "claude-opus-default"],
        "pi": [
            "pi-deepseek-v4-flash",
            "pi-qwen3-8-flash",
            "pi-glm-5-3-flash",
        ],
    }
    assert second_saw_finished == [8] * 8
    assert receipt["status"] == "complete"


def test_matrix_can_stop_at_a_requested_task_barrier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan_path: Path,
    season_plan: dict,
) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt = _new_receipt(plan_path, season_plan, "harbor")
    _terminalize(receipt)
    for cell in receipt["cells"][:16]:
        cell.update(status="pending", run=None, passed=False, trusted=False)
    receipt["execution_window"] = {"stop_after_task": "canyon-strike"}
    called: list[str] = []

    def execute(_root, _plan, _receipt_path, _receipt, cell, _cancel_event=None):
        called.append(cell["cell_id"])
        cell.update(
            status="completed",
            run=f"/runs/{cell['cell_id']}",
            passed=True,
            trusted=True,
            artifacts=copy.deepcopy(receipt["cells"][16]["artifacts"]),
        )

    monkeypatch.setattr(matrix_module, "_verify_plan_file", lambda *_args: season_plan)
    monkeypatch.setattr(matrix_module, "verify_frozen_inputs", lambda *_args: None)
    monkeypatch.setattr(matrix_module, "_execute_cell", execute)

    matrix_module._drive_matrix(
        ROOT,
        plan_path,
        season_plan,
        receipt_path,
        receipt,
        stop_after_task="canyon-strike",
    )

    assert len(called) == 8
    assert all(cell["status"] == "pending" for cell in receipt["cells"][8:16])
    assert receipt["status"] == "incomplete"
    assert receipt["execution_window"]["stopped_at_task_barrier"] == "canyon-strike"


def test_matrix_honors_dynamic_pause_only_after_active_task_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan_path: Path,
    season_plan: dict,
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    receipt_path = tmp_path / "receipt.json"
    receipt = _new_receipt(plan_path, season_plan, "harbor")
    _terminalize(receipt)
    for cell in receipt["cells"][:16]:
        cell.update(status="pending", run=None, passed=False, trusted=False)
    called: list[str] = []

    def execute(_root, _plan, _receipt_path, _receipt, cell, _cancel_event=None):
        called.append(cell["cell_id"])
        if len(called) == 1:
            request_matrix_pause(receipt["matrix_id"], requested_by="test-webui")
        cell.update(
            status="completed",
            run=f"/runs/{cell['cell_id']}",
            passed=True,
            trusted=True,
            artifacts=copy.deepcopy(receipt["cells"][16]["artifacts"]),
        )

    monkeypatch.setattr(matrix_module, "_verify_plan_file", lambda *_args: season_plan)
    monkeypatch.setattr(matrix_module, "verify_frozen_inputs", lambda *_args: None)
    monkeypatch.setattr(matrix_module, "_execute_cell", execute)

    matrix_module._drive_matrix(ROOT, plan_path, season_plan, receipt_path, receipt)

    assert len(called) == 8
    assert all(cell["status"] == "completed" for cell in receipt["cells"][:8])
    assert all(cell["status"] == "pending" for cell in receipt["cells"][8:16])
    assert receipt["status"] == "incomplete"
    assert receipt["execution_window"]["stopped_at_task_barrier"] == "canyon-strike"


def test_resume_recovers_complete_canonical_receipt_missing_closure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan_path: Path,
    season_plan: dict,
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    receipt_path = tmp_path / "receipt.json"
    receipt = _new_receipt(plan_path, season_plan, "container")
    receipt["receipt_path"] = str(receipt_path.resolve())
    _terminalize(receipt)
    receipt.update(status="complete", completed_at="2026-08-31T00:00:00+00:00")
    _write_receipt(receipt_path, receipt)
    matrix_module._claim_canonical_matrix("season-1", receipt_path, receipt)

    monkeypatch.setattr(matrix_module, "_verify_plan_file", lambda *_args: season_plan)
    monkeypatch.setattr(matrix_module, "verify_frozen_inputs", lambda *_args: None)
    monkeypatch.setattr(matrix_module, "verify_run_artifacts", lambda *_args: None)
    monkeypatch.setattr(
        matrix_module,
        "_drive_matrix",
        lambda *_args: pytest.fail("a complete receipt must never rerun candidates"),
    )

    assert resume_matrix(ROOT, receipt_path) == receipt_path
    closure_path = matrix_module._canonical_closure_path("season-1")
    assert closure_path.is_file()
    matrix_module._verify_canonical_publication_receipt(load_matrix_receipt(receipt_path))
    assert resume_matrix(ROOT, receipt_path) == receipt_path


def test_keyboard_interrupt_leaves_resumable_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan_path: Path,
    season_plan: dict,
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    receipt_path = tmp_path / "receipt.json"
    receipt = _new_receipt(plan_path, season_plan, "container")
    _terminalize(receipt)
    receipt["cells"][0].update(status="pending", run=None, passed=False, trusted=False)
    receipt["status"] = "interrupted"
    _write_receipt(receipt_path, receipt)
    matrix_module._claim_canonical_matrix("season-1", receipt_path, receipt)

    monkeypatch.setattr(matrix_module, "_verify_plan_file", lambda *_args: season_plan)
    monkeypatch.setattr(matrix_module, "verify_frozen_inputs", lambda *_args: None)

    def interrupt(*_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(matrix_module, "_execute_cell", interrupt)
    with pytest.raises(MatrixInterrupted) as raised:
        resume_matrix(ROOT, receipt_path)
    assert raised.value.receipt_path == receipt_path
    interrupted = load_matrix_receipt(receipt_path)
    assert interrupted["status"] == "interrupted"
    assert interrupted["cells"][0]["status"] == "interrupted"


def test_evaluator_retry_reuses_completed_candidate_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    season_plan: dict,
) -> None:
    cell = copy.deepcopy(season_plan["cells"][0])
    run_root = tmp_path / "candidate-run"
    (run_root / "evaluation").mkdir(parents=True)
    (run_root / "evaluation/partial.log").write_text("kept", encoding="utf-8")
    (run_root / "render").mkdir()
    (run_root / "manifest.json").write_text(
        json.dumps({"status": "candidate-complete"}), encoding="utf-8"
    )
    (run_root / "events.jsonl").write_text("", encoding="utf-8")
    (run_root / "stderr.log").write_text("", encoding="utf-8")
    cell.update(
        {
            "run": str(run_root),
            "status": "running",
            "passed": False,
            "trusted": False,
            "judge": {"status": "not-run"},
        }
    )
    receipt = {"backend": "container", "cells": [cell]}
    receipt_path = tmp_path / "receipt.json"

    def do_not_rerun(*_args, **_kwargs):
        raise AssertionError("candidate must not be rerun")

    def evaluate(_root: Path, reused: Path) -> Path:
        assert reused == run_root
        assert not (reused / "evaluation").exists()
        assert not (reused / "render").exists()
        output = reused / "evaluation"
        output.mkdir()
        report = output / "report.json"
        report.write_text(json.dumps({"passed": True, "trusted": True}), encoding="utf-8")
        return report

    monkeypatch.setattr(matrix_module, "run_once", do_not_rerun)
    monkeypatch.setattr(matrix_module, "evaluate_run", evaluate)
    monkeypatch.setattr(
        matrix_module,
        "trusted_cell_gate",
        lambda *_args: (True, []),
    )
    monkeypatch.setattr(
        matrix_module,
        "close_run_artifacts",
        lambda *_args: {"schema_version": 1, "files": {}},
    )

    matrix_module._execute_cell(ROOT, season_plan, receipt_path, receipt, cell)

    assert cell["status"] == "completed"
    assert len(cell["infrastructure_attempts"]) == 1
    archived = Path(cell["infrastructure_attempts"][0])
    assert (archived / "evaluation/partial.log").read_text(encoding="utf-8") == "kept"


def test_formal_season_rejects_native_but_accepts_harbor_backend_name(
    tmp_path: Path, plan_path: Path
) -> None:
    with pytest.raises(MatrixError, match="trusted isolated backend"):
        start_matrix(ROOT, plan_path, backend="native")
    with pytest.raises(MatrixError, match="fresh --smoke-receipt"):
        start_matrix(ROOT, plan_path, backend="harbor")


def test_matrix_cli_requires_exactly_one_frozen_source() -> None:
    parser = build_parser()
    assert parser.parse_args(["matrix", "--season", "season-1"]).season == "season-1"
    assert parser.parse_args(["matrix", "--plan", "/tmp/plan.json"]).plan
    assert parser.parse_args(["matrix", "--resume", "/tmp/receipt.json"]).resume
    assert parser.parse_args(["run", "--task", "x", "--profile", "y"]).backend == "harbor"
    assert parser.parse_args(["smoke", "--plan", "/tmp/plan.json"]).backend == "harbor"
    with pytest.raises(SystemExit):
        parser.parse_args(["matrix"])
    with pytest.raises(SystemExit):
        parser.parse_args(["matrix", "--season", "season-1", "--plan", "/tmp/plan.json"])


def test_doctor_probes_flags_without_starting_a_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[list[str]] = []

    def which(name: str) -> str:
        return f"/mock/{name}"

    def run(argv, **_kwargs):
        calls.append(list(argv))
        command = Path(argv[0]).name
        if command == "codex" and argv[1:] == ["features", "list"]:
            output = "goals stable true\n"
        elif command == "codex":
            output = (
                "--config --enable --strict-config --ignore-user-config --ephemeral --json"
            )
        elif command == "claude":
            output = (
                "--append-system-prompt --setting-sources --no-session-persistence "
                "--output-format --strict-mcp-config"
            )
        elif command == "pi":
            output = (
                "--append-system-prompt --no-session --no-context-files --mode --no-approve"
            )
        else:
            output = "ok"
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr("web3dgamebench.cli.shutil.which", which)
    monkeypatch.setattr("web3dgamebench.cli.subprocess.run", run)

    assert command_doctor(SimpleNamespace()) == 0
    checks = json.loads(capsys.readouterr().out)
    assert checks["season_1_config"] is True
    assert checks["codex_runtime_contract"] is True
    assert checks["claude_runtime_contract"] is True
    assert checks["pi_runtime_contract"] is True
    assert all(
        "--help" in call or "features" in call or "version" in call for call in calls
    )
