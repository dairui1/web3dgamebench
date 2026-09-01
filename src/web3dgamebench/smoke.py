from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import load_profiles
from .container import ensure_plane, load_container_config, wrap_command
from .matrix import MatrixError, load_preflight_plan
from .process import run_captured
from .runner import runs_dir
from .runtimes import (
    build_invocation,
    goal_activation_status,
    parse_goal_lifecycle,
    parse_resolved_model,
)

_PROFILES = (
    "codex-sol-medium",
    "claude-sonnet-default",
    "pi-deepseek-v4-flash",
)
_MAX_AGE = timedelta(hours=6)
_TASK = """# Harness smoke contract

Run `npm --version` and `chromium --version`. Then create `smoke.txt` containing
exactly `SMOKE_OK` followed by one newline. Read it back, and complete the active
goal only after all three checks succeed. Do not create any other project files.
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _value_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt.pop("receipt_digest_sha256", None)
    receipt["receipt_digest_sha256"] = _value_sha256(receipt)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")


def _probe(
    root: Path,
    probe_root: Path,
    profile_id: str,
    cancel_event: threading.Event,
    backend: str,
) -> dict[str, Any]:
    profile = load_profiles(root)[profile_id]
    workspace = probe_root / profile.harness / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "TASK.md").write_text(_TASK, encoding="utf-8")
    (workspace / "package.json").write_text(
        '{"name":"web3dgamebench-smoke","private":true}\n', encoding="utf-8"
    )
    invocation = build_invocation(
        profile,
        Path("/workspace"),
        _TASK,
        isolation="container",
        goal_mode="external-goal",
        goal_completion="contract-and-evidence",
    )
    config = load_container_config(root)
    credential_dir = probe_root / profile.harness / "runtime-home"
    container_name = f"web3dgamebench-smoke-{profile.harness}-{uuid.uuid4().hex[:8]}"
    environment = os.environ.copy()
    environment.update(invocation.env)

    def cleanup() -> None:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    started_at = _now()
    output_dir = probe_root / profile.harness
    events_path = output_dir / "events.jsonl"
    stderr_path = output_dir / "stderr.log"
    try:
        if backend == "harbor":
            from .harbor_backend import execute_harbor

            result = execute_harbor(
                root,
                output_dir,
                workspace,
                task_id="harness-smoke",
                profile=profile,
                instruction=_TASK,
                invocation=invocation,
                cancel_event=cancel_event,
            )
            environment_names = result.environment_names
        else:
            argv, environment_names = wrap_command(
                invocation.argv,
                root=root,
                config=config,
                workspace=workspace,
                profile=profile,
                credential_dir=credential_dir,
                container_name=container_name,
            )
            result = run_captured(
                argv,
                cwd=workspace,
                env=environment,
                input_text=_TASK if invocation.stdin_prompt else None,
                cancel_event=cancel_event,
                cleanup=cleanup,
                timeout_seconds=config.command_timeout_seconds,
                stdout_path=events_path,
                stderr_path=stderr_path,
            )
    finally:
        shutil.rmtree(credential_dir, ignore_errors=True)
    events_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    lifecycle = parse_goal_lifecycle(result.stdout)
    smoke_file = workspace / "smoke.txt"
    resolved_model = parse_resolved_model(invocation.trace_format, result.stdout)
    activation_status = goal_activation_status(invocation.goal_activation, result.stdout)
    checks = {
        "exit_zero": result.returncode == 0,
        "workspace_write": smoke_file.is_file()
        and smoke_file.read_text(encoding="utf-8") == "SMOKE_OK\n",
        "resolved_model_observed": bool(resolved_model),
        "goal_completed": activation_status == "observed-complete",
        "stdin_owned_by_runner": invocation.stdin_prompt or result.returncode != 130,
    }
    return {
        "profile": profile_id,
        "harness": profile.harness,
        "model_requested": profile.model,
        "model_resolved": resolved_model,
        "started_at": started_at,
        "completed_at": _now(),
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "goal_activation_status": activation_status,
        "goal_lifecycle": lifecycle,
        "events_sha256": _sha256(output_dir / "events.jsonl"),
        "stderr_sha256": _sha256(output_dir / "stderr.log"),
        "environment_names": sorted(environment_names),
    }


def run_smoke(root: Path, plan_path: Path, *, backend: str = "container") -> Path:
    if backend not in {"container", "harbor"}:
        raise MatrixError(f"unsupported smoke backend: {backend}")
    plan_path = plan_path.expanduser().resolve()
    plan = load_preflight_plan(plan_path)
    config = load_container_config(root)
    plane = ensure_plane(root, config) if backend == "container" else {
        "image_digest": plan["runtime_environment"]["container_images"]["candidate"]["id"]
    }
    smoke_id = f"{plan['plan_id']}-{uuid.uuid4().hex[:8]}"
    probe_root = runs_dir() / "smoke" / smoke_id
    probe_root.mkdir(parents=True)
    cancel_event = threading.Event()
    probes: list[dict[str, Any]] = []
    try:
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="harness-smoke") as executor:
            futures = [
                executor.submit(_probe, root, probe_root, profile_id, cancel_event, backend)
                for profile_id in _PROFILES
            ]
            for future in futures:
                probes.append(future.result())
    except BaseException:
        cancel_event.set()
        raise
    receipt = {
        "schema_version": 1,
        "smoke_id": smoke_id,
        "status": "passed" if all(item["status"] == "passed" for item in probes) else "failed",
        "backend": backend,
        "created_at": _now(),
        "plan": {
            "path": str(plan_path),
            "digest_sha256": plan["plan_digest_sha256"],
            "file_sha256": _sha256(plan_path),
        },
        "candidate_image": {
            "name": config.image,
            "id": plane["image_digest"],
        },
        "probes": sorted(probes, key=lambda item: _PROFILES.index(item["profile"])),
    }
    receipt_path = probe_root / "receipt.json"
    _write_receipt(receipt_path, receipt)
    return receipt_path


def verify_smoke_receipt(
    plan_path: Path,
    plan: dict[str, Any],
    receipt_path: Path,
    *,
    backend: str = "container",
) -> dict[str, Any]:
    receipt_path = receipt_path.expanduser().resolve()
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MatrixError(f"invalid harness smoke receipt: {receipt_path}") from error
    expected_digest = receipt.pop("receipt_digest_sha256", None)
    if expected_digest != _value_sha256(receipt):
        raise MatrixError(f"harness smoke receipt digest mismatch: {receipt_path}")
    receipt["receipt_digest_sha256"] = expected_digest
    if receipt.get("status") != "passed":
        raise MatrixError("harness smoke did not pass")
    if receipt.get("backend", "container") != backend:
        raise MatrixError("harness smoke backend does not match the matrix backend")
    reference = receipt.get("plan")
    if not isinstance(reference, dict) or (
        reference.get("digest_sha256") != plan.get("plan_digest_sha256")
        or reference.get("file_sha256") != _sha256(plan_path)
    ):
        raise MatrixError("harness smoke receipt does not match the frozen plan")
    try:
        created_at = datetime.fromisoformat(str(receipt["created_at"]))
    except (KeyError, ValueError) as error:
        raise MatrixError("harness smoke receipt has no valid timestamp") from error
    if datetime.now(UTC) - created_at > _MAX_AGE:
        raise MatrixError("harness smoke receipt is older than 6 hours")
    planned_image = (
        plan.get("runtime_environment", {})
        .get("container_images", {})
        .get("candidate", {})
        .get("id")
    )
    image = receipt.get("candidate_image")
    if not isinstance(image, dict) or image.get("id") != planned_image:
        raise MatrixError("harness smoke candidate image does not match the frozen plan")
    expected = {"codex", "claude-code", "pi"}
    passed = {
        item.get("harness")
        for item in receipt.get("probes", [])
        if isinstance(item, dict) and item.get("status") == "passed"
    }
    if passed != expected:
        raise MatrixError("harness smoke receipt does not cover all core harnesses")
    return receipt
