from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .evaluator import evaluate_run
from .runner import run_once, runs_dir


class CalibrationError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_config(root: Path) -> dict[str, Any]:
    path = root / "configs/calibration.toml"
    value = tomllib.loads(path.read_text(encoding="utf-8")).get("calibration")
    if not isinstance(value, dict):
        raise CalibrationError(f"invalid calibration config: {path}")
    tasks = value.get("tasks")
    baselines = value.get("baselines")
    if not isinstance(tasks, list) or not tasks or not isinstance(baselines, dict):
        raise CalibrationError(f"invalid calibration tasks or baselines: {path}")
    return value


def calibration_pointer(directory: Path | None = None) -> Path:
    return (directory or runs_dir()) / "calibration" / "latest.json"


def _write_pointer(receipt_path: Path, receipt: dict[str, Any], state: Path) -> None:
    _atomic_json(
        calibration_pointer(state),
        {
            "schema_version": 1,
            "calibration_id": receipt["calibration_id"],
            "status": receipt["status"],
            "receipt": str(receipt_path.resolve()),
            "receipt_sha256": _sha256(receipt_path),
        },
    )


def load_calibration_gate(directory: Path | None = None) -> dict[str, Any] | None:
    pointer = calibration_pointer(directory)
    try:
        reference = json.loads(pointer.read_text(encoding="utf-8"))
        receipt_path = Path(reference["receipt"]).expanduser().resolve()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (KeyError, OSError, ValueError, json.JSONDecodeError, TypeError):
        return None
    if not receipt_path.is_relative_to(pointer.parent.resolve()):
        return None
    if reference.get("receipt_sha256") != _sha256(receipt_path):
        return None
    return {**receipt, "path": str(receipt_path)}


def require_calibration_gate(
    plan: Path, *, directory: Path | None = None
) -> dict[str, Any]:
    gate = load_calibration_gate(directory)
    if gate is None or gate.get("status") != "passed":
        raise CalibrationError("the three-task calibration gate has not passed")
    plan_value = json.loads(plan.read_text(encoding="utf-8"))
    if gate.get("plan_digest_sha256") != plan_value.get("plan_digest_sha256"):
        raise CalibrationError("calibration gate belongs to a different frozen plan")
    return gate


def _passed_checks(report: dict[str, Any]) -> tuple[int, int]:
    checks = [item for item in report.get("checks", []) if isinstance(item, dict)]
    return sum(item.get("passed") is True for item in checks), len(checks)


def _completion_evidence(manifest: dict[str, Any]) -> dict[str, Any] | None:
    lifecycle = (manifest.get("goal") or {}).get("lifecycle") or []
    if not any(
        item.get("tool") == "update_goal" and item.get("status") == "complete"
        for item in lifecycle
        if isinstance(item, dict)
    ):
        return None
    events_path = Path(manifest["workspace"]).parent / "events.jsonl"
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        entry = event.get("entry") if isinstance(event, dict) else None
        data = entry.get("data") if isinstance(entry, dict) else None
        if (
            isinstance(entry, dict)
            and entry.get("customType") == "web3dgamebench-lifecycle"
            and isinstance(data, dict)
            and data.get("status") == "complete"
            and isinstance(data.get("evidence"), dict)
        ):
            return data["evidence"]
    return None


def _watchdog_probe() -> dict[str, Any]:
    process = subprocess.Popen(
        ["sh", "-c", "trap 'exit 0' INT TERM; while :; do sleep 1; done"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        process.wait(timeout=0.2)
        return {"passed": False, "reason": "infinite probe exited before preemption"}
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(process.pid), 15)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(process.pid), 9)
            process.wait(timeout=3)
            return {"passed": False, "reason": "SIGTERM did not preempt process group"}
    return {"passed": True, "exit_code": process.returncode}


def _task_result(
    task: str, run_root: Path, baseline: dict[str, Any]
) -> dict[str, Any]:
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report_path: Path | None = None
    report: dict[str, Any] | None = None
    if manifest.get("workspace_digest"):
        try:
            report_path = evaluate_run(Path(__file__).resolve().parents[2], run_root)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            report = {"trusted": False, "passed": False, "infrastructure_errors": [str(error)]}
    passed_checks, total_checks = _passed_checks(report or {})
    required = (
        total_checks
        if baseline.get("kind") == "conservative-full-admission"
        else int(baseline.get("passed_checks", 0))
    )
    evidence = _completion_evidence(manifest)
    checks = {
        "trusted_terminal": manifest.get("status") == "candidate-complete"
        and (manifest.get("goal") or {}).get("activation_status") == "observed-complete",
        "task_brief_preserved": (manifest.get("prompt") or {}).get(
            "task_brief_preserved"
        )
        is True,
        "completion_evidence": bool(
            evidence
            and evidence.get("build")
            and evidence.get("task_sha256")
            and evidence.get("sourceSha256")
            and evidence.get("distSha256")
        ),
        "bounded_verification": manifest.get("failure_scope")
        != "candidate-verification-overrun",
        "evaluator_trusted": bool(report and report.get("trusted") is True),
        "evaluator_not_below_baseline": passed_checks >= required,
    }
    return {
        "task": task,
        "status": "passed" if all(checks.values()) else "failed",
        "run": str(run_root.resolve()),
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": _sha256(manifest_path),
        "trace": str((run_root / "events.jsonl").resolve()),
        "trace_sha256": _sha256(run_root / "events.jsonl")
        if (run_root / "events.jsonl").is_file()
        else None,
        "workspace_digest": manifest.get("workspace_digest"),
        "prompt": manifest.get("prompt"),
        "goal": manifest.get("goal"),
        "image": manifest.get("container_plane"),
        "completion_evidence": evidence,
        "evaluation": str(report_path.resolve()) if report_path else None,
        "evaluation_sha256": _sha256(report_path) if report_path else None,
        "evaluator": {
            "passed_checks": passed_checks,
            "total_checks": total_checks,
            "passed": report.get("passed") if report else False,
            "trusted": report.get("trusted") if report else False,
        },
        "baseline": {**baseline, "required_passed_checks": required},
        "checks": checks,
    }


def run_calibration(root: Path, plan: Path, *, backend: str = "harbor") -> Path:
    root = root.resolve()
    plan = plan.expanduser().resolve()
    config = _load_config(root)
    if backend != config.get("backend") or backend != "harbor":
        raise CalibrationError("calibration is frozen to the Harbor backend")
    state = runs_dir()
    if (state / "matrices" / f"canonical-{config['season']}.json").exists():
        raise CalibrationError("calibration cannot run after a canonical Matrix is claimed")
    plan_value = json.loads(plan.read_text(encoding="utf-8"))
    if (plan_value.get("season") or {}).get("id") != config["season"]:
        raise CalibrationError("calibration plan has the wrong season")
    calibration_id = f"calibration-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    receipt_path = state / "calibration" / calibration_id / "receipt.json"
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "calibration_id": calibration_id,
        "canonical": False,
        "status": "running",
        "season": config["season"],
        "profile": config["profile"],
        "backend": backend,
        "plan": str(plan),
        "plan_digest_sha256": plan_value.get("plan_digest_sha256"),
        "config_sha256": _sha256(root / "configs/calibration.toml"),
        "started_at": _now(),
        "watchdog": _watchdog_probe(),
        "tasks": [],
    }
    _atomic_json(receipt_path, receipt)
    _write_pointer(receipt_path, receipt, state)
    baselines = config["baselines"]
    try:
        for task in config["tasks"]:
            run_root = run_once(
                root,
                task,
                config["profile"],
                backend=backend,
                calibration=True,
            )
            result = _task_result(task, run_root, baselines[task])
            receipt["tasks"].append(result)
            receipt["updated_at"] = _now()
            _atomic_json(receipt_path, receipt)
            _write_pointer(receipt_path, receipt, state)
            if result["status"] != "passed":
                break
    except KeyboardInterrupt:
        receipt["status"] = "interrupted"
        receipt["completed_at"] = _now()
        _atomic_json(receipt_path, receipt)
        _write_pointer(receipt_path, receipt, state)
        raise
    passed = receipt["watchdog"]["passed"] and len(receipt["tasks"]) == len(
        config["tasks"]
    ) and all(item["status"] == "passed" for item in receipt["tasks"])
    receipt["status"] = "passed" if passed else "failed"
    receipt["completed_at"] = _now()
    _atomic_json(receipt_path, receipt)
    _write_pointer(receipt_path, receipt, state)
    return receipt_path
