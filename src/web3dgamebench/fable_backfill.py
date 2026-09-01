from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import runner
from .config import Profile, load_profiles
from .evaluator import evaluate_run
from .matrix import (
    close_run_artifacts,
    load_preflight_plan,
    trusted_cell_gate,
    verify_frozen_inputs,
)

FABLE_PROFILE_ID = "claude-fable-default"

_QUOTA_MARKERS = (
    "rate_limit",
    "rate limit",
    "session limit",
    "usage limit",
    "usage credits",
    "overage",
)


class FableBackfillError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt["updated_at"] = _now()
    receipt.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = _digest(receipt)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(receipt, target, indent=2)
            target.write("\n")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _load_receipt(path: Path) -> dict[str, Any]:
    try:
        receipt = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise FableBackfillError(f"invalid Fable receipt: {path}") from error
    expected = receipt.pop("receipt_sha256", None)
    actual = _digest(receipt)
    receipt["receipt_sha256"] = expected
    if expected != actual:
        raise FableBackfillError(f"Fable receipt digest mismatch: {path}")
    return receipt


def _fable_profile(root: Path) -> Profile:
    profile = load_profiles(root).get(FABLE_PROFILE_ID)
    if profile is None or profile.harness != "claude-code":
        raise FableBackfillError(
            f"{FABLE_PROFILE_ID} must be a configured Claude Code profile"
        )
    return profile


def _new_receipt(
    core_plan_path: Path, core_plan: dict[str, Any], profile: Profile
) -> dict[str, Any]:
    task_order = core_plan["season"]["tasks"]
    return {
        "schema_version": 1,
        "kind": "optional-fable-backfill",
        "season": core_plan["season"]["id"],
        "status": "pending",
        "created_at": _now(),
        "core_plan": {
            "path": str(core_plan_path),
            "digest_sha256": core_plan["plan_digest_sha256"],
        },
        "profile": asdict(profile),
        "policy": {
            "blocks_core_matrix": False,
            "quota_failure": "defer",
            "later_backfill": True,
            "task_order": "serial",
        },
        "cells": [
            {
                "cell_id": f"{task_id}::{profile.id}::a1",
                "task": task_id,
                "profile": profile.id,
                "attempt": 1,
                "status": "pending",
                "run": None,
                "passed": False,
                "trusted": False,
            }
            for task_id in task_order
        ],
    }


def quota_deferred(run_root: Path) -> bool:
    for path in (run_root / "events.jsonl", run_root / "stderr.log"):
        if not path.is_file():
            continue
        for line in path.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                text = line.lower()
            else:
                text = " ".join(
                    str(event.get(key, ""))
                    for key in ("type", "subtype", "error", "result")
                ).lower()
            if any(marker in text for marker in _QUOTA_MARKERS):
                return True
    return False


def _run_fable(
    root: Path, profile: Profile, task_id: str, attempt: int, backend: str
) -> Path:
    return runner.run_once(root, task_id, profile.id, attempt, backend=backend)


def _evaluation_plan(core_plan: dict[str, Any], profile: Profile) -> dict[str, Any]:
    plan = json.loads(json.dumps(core_plan))
    plan["profiles"][profile.id] = asdict(profile)
    return plan


def _begin_attempt(cell: dict[str, Any]) -> None:
    previous = cell.get("run")
    if isinstance(previous, str):
        cell.setdefault("previous_runs", []).append(previous)
        cell["attempt"] += 1
    cell.update(status="running", passed=False, trusted=False, started_at=_now())


def run_backfill(
    root: Path,
    core_plan_path: Path,
    receipt_path: Path,
    selected_tasks: set[str] | None,
    *,
    backend: str = "harbor",
) -> Path:
    if backend not in {"container", "harbor"}:
        raise FableBackfillError(f"unsupported Fable backend: {backend}")
    core_plan_path = core_plan_path.expanduser().resolve()
    core_plan = load_preflight_plan(core_plan_path)
    verify_frozen_inputs(root, core_plan)
    if core_plan["season"]["id"] != "season-1":
        raise FableBackfillError("Fable backfill requires a frozen season-1 plan")
    profile = _fable_profile(root)

    if receipt_path.is_file():
        receipt = _load_receipt(receipt_path)
        if receipt["core_plan"]["digest_sha256"] != core_plan["plan_digest_sha256"]:
            raise FableBackfillError("Fable receipt belongs to another core plan")
        if receipt.get("profile") != asdict(profile):
            raise FableBackfillError("Fable receipt profile differs from the frozen configuration")
        if receipt.get("backend", "container") != backend:
            raise FableBackfillError("Fable receipt backend differs from the requested backend")
    else:
        receipt = _new_receipt(core_plan_path, core_plan, profile)
        receipt["backend"] = backend
        _write_receipt(receipt_path, receipt)

    known_tasks = {cell["task"] for cell in receipt["cells"]}
    if selected_tasks is not None and not selected_tasks <= known_tasks:
        unknown = ", ".join(sorted(selected_tasks - known_tasks))
        raise FableBackfillError(f"unknown Fable backfill tasks: {unknown}")

    receipt["status"] = "running"
    _write_receipt(receipt_path, receipt)
    plan = _evaluation_plan(core_plan, profile)
    for cell in receipt["cells"]:
        if selected_tasks is not None and cell["task"] not in selected_tasks:
            continue
        if cell["status"] not in {"pending", "quota-deferred", "infrastructure-error"}:
            continue
        _begin_attempt(cell)
        _write_receipt(receipt_path, receipt)

        run_root = _run_fable(root, profile, cell["task"], cell["attempt"], backend)
        cell["run"] = str(run_root)
        manifest = json.loads((run_root / "manifest.json").read_text())
        if manifest.get("status") != "candidate-complete":
            if quota_deferred(run_root):
                cell.update(
                    status="quota-deferred",
                    quota_deferred_at=_now(),
                    artifacts=close_run_artifacts(run_root),
                )
                _write_receipt(receipt_path, receipt)
                break
            cell.update(
                status="infrastructure-error",
                infrastructure_error=(
                    f"Fable runtime exited without evidence (exit {manifest.get('exit_code')})"
                ),
                completed_at=_now(),
            )
            _write_receipt(receipt_path, receipt)
            break

        report_path = evaluate_run(root, run_root)
        report = json.loads(report_path.read_text())
        trusted, failures = trusted_cell_gate(plan, cell, manifest, report, run_root)
        cell.update(
            evaluation=str(report_path),
            playable=report.get("passed") is True,
            passed=trusted,
            trusted=trusted,
            status="completed" if trusted else "evidence-failure",
            evidence_failures=failures,
            artifacts=close_run_artifacts(run_root),
            completed_at=_now(),
        )
        _write_receipt(receipt_path, receipt)

    unfinished = any(
        cell["status"] in {"pending", "quota-deferred", "infrastructure-error", "running"}
        for cell in receipt["cells"]
    )
    receipt["status"] = "deferred" if unfinished else "complete"
    receipt["summary"] = {
        "total": len(receipt["cells"]),
        "completed": sum(cell["status"] == "completed" for cell in receipt["cells"]),
        "evidence_failures": sum(
            cell["status"] == "evidence-failure" for cell in receipt["cells"]
        ),
        "quota_deferred": sum(
            cell["status"] == "quota-deferred" for cell in receipt["cells"]
        ),
        "infrastructure_errors": sum(
            cell["status"] == "infrastructure-error" for cell in receipt["cells"]
        ),
        "pending": sum(cell["status"] == "pending" for cell in receipt["cells"]),
    }
    _write_receipt(receipt_path, receipt)
    return receipt_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the optional Claude Fable lane")
    parser.add_argument("--core-plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--task", action="append", default=[])
    args = parser.parse_args(argv)
    receipt = args.receipt or (
        runner.runs_dir() / f"fable-backfill-{args.core_plan.stem}.json"
    )
    result = run_backfill(
        Path(__file__).resolve().parents[2],
        args.core_plan,
        receipt.expanduser().resolve(),
        set(args.task) or None,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
