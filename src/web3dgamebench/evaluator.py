from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from .artifacts import (
    candidate_workspace_sha256,
    file_tree_sha256,
    normalize_playable_bundle,
)
from .config import Task, load_task
from .container import docker, load_container_config
from .runtime_contracts import file_sha256, load_runtime_contract


def _file_digest(path: Path) -> str:
    return file_sha256(path)


def render_source_sha256(root: Path) -> str:
    """Return the stable digest used to freeze a candidate render source tree."""
    return file_tree_sha256(root, excluded=frozenset({"node_modules", "dist"}))


def render_dist_sha256(dist: Path) -> str:
    """Return a stable digest for the exact playable bundle admitted by the evaluator."""

    if not dist.is_dir():
        raise ValueError(f"rendered dist is missing: {dist}")
    return file_tree_sha256(dist)


def _task_digest(root: Path) -> str:
    return render_source_sha256(root)


def _copy_submission(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            "node_modules",
            "dist",
            ".git",
            ".web3dgamebench-final.txt",
            ".aetherplay-final.txt",
        ),
    )


def _task_viewports(task: Task) -> dict[str, dict[str, int]]:
    return {
        label: {"width": viewport.width, "height": viewport.height}
        for label, viewport in task.viewports.items()
    }


def _evaluator_config(
    root: Path,
    task: Task,
    script: Path,
    runtime_schema: Path,
    *,
    render_digest: str,
    post_build_render_digest: str,
    dist_digest: str | None,
) -> dict:
    runtime_contract = load_runtime_contract(
        root,
        task_id=task.id,
        seed=task.seed,
        viewports=_task_viewports(task),
    )
    return {
        "schema_version": 1,
        "task_id": task.id,
        "checks": task.checks.as_dict(),
        "runtime_contract": runtime_contract.data,
        "runtime_contract_sha256": runtime_contract.sha256,
        "evaluator_sha256": file_sha256(script),
        "runtime_schema_sha256": file_sha256(runtime_schema),
        "render_source_sha256": render_digest,
        "post_build_render_source_sha256": post_build_render_digest,
        "render_source_unchanged": render_digest == post_build_render_digest,
        "render_dist_sha256": dist_digest,
    }


def _evaluation_identity(evaluator_config: dict) -> dict[str, str]:
    return {
        "runtime_contract_sha256": evaluator_config["runtime_contract_sha256"],
        "script_sha256": evaluator_config["evaluator_sha256"],
        "runtime_schema_sha256": evaluator_config["runtime_schema_sha256"],
        "render_source_sha256": evaluator_config["render_source_sha256"],
    }


def _render_evidence(evaluator_config: dict) -> dict[str, object]:
    return {
        "render_source_sha256": evaluator_config["render_source_sha256"],
        "post_build_render_source_sha256": evaluator_config[
            "post_build_render_source_sha256"
        ],
        "render_source_unchanged": evaluator_config["render_source_unchanged"],
        "render_dist_sha256": evaluator_config["render_dist_sha256"],
    }


def _render_integrity_check(evaluator_config: dict) -> dict[str, object]:
    return {
        "name": "render-source-unchanged",
        "passed": evaluator_config["render_source_unchanged"],
        "detail": _render_evidence(evaluator_config),
    }


def _report_identity_errors(report: object, evaluator_config: dict, task_id: str) -> list[str]:
    if not isinstance(report, dict):
        return ["evaluation report is not an object"]
    errors: list[str] = []
    if report.get("task_id") != task_id:
        errors.append(
            f"task_id expected {task_id!r}, got {report.get('task_id')!r}"
        )
    evaluator = report.get("evaluator")
    expected_evaluator = _evaluation_identity(evaluator_config)
    if not isinstance(evaluator, dict):
        errors.append("evaluator identity is missing")
    else:
        for name, expected in expected_evaluator.items():
            if evaluator.get(name) != expected:
                errors.append(f"evaluator.{name} does not match the frozen evaluator")
    evidence = report.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("render evidence is missing")
    else:
        for name, expected in _render_evidence(evaluator_config).items():
            if evidence.get(name) != expected:
                errors.append(f"evidence.{name} does not match the frozen render")
    integrity_checks = [
        item
        for item in report.get("checks", [])
        if isinstance(item, dict) and item.get("name") == "render-source-unchanged"
    ]
    if len(integrity_checks) != 1:
        errors.append("render-source-unchanged gate is missing or duplicated")
    elif integrity_checks[0].get("passed") is not evaluator_config[
        "render_source_unchanged"
    ]:
        errors.append("render-source-unchanged gate does not match the build evidence")
    return errors


def evaluate_run(root: Path, run_root: Path) -> Path:
    manifest_path = run_root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"run manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    manifest_task = manifest.get("task")
    if not isinstance(manifest_task, dict) or not isinstance(manifest_task.get("id"), str):
        raise ValueError(f"run manifest has no task id: {manifest_path}")  # noqa: TRY004
    task = load_task(root, manifest_task["id"])
    expected_task_digest = _task_digest(task.root)
    if manifest_task.get("digest") != expected_task_digest:
        raise ValueError(
            f"run task digest no longer matches frozen task {task.id}; rerun the cell"
        )
    expected_brief_digest = _file_digest(task.brief)
    if manifest_task.get("brief_sha256") != expected_brief_digest:
        raise ValueError(
            f"run brief digest no longer matches frozen task {task.id}; rerun the cell"
        )
    workspace = Path(manifest["workspace"])
    if not workspace.is_dir():
        raise ValueError(f"run workspace not found: {workspace}")
    expected_workspace_digest = manifest.get("workspace_digest")
    if not isinstance(expected_workspace_digest, str):
        raise TypeError("run manifest has no terminal workspace digest")
    workspace_digest = candidate_workspace_sha256(workspace)
    if workspace_digest != expected_workspace_digest:
        raise ValueError(
            "candidate workspace changed after candidate exit; rerun the cell"
        )

    render = run_root / "render"
    if render.exists():
        raise ValueError(f"immutable render already exists: {render}")
    _copy_submission(workspace, render)
    if candidate_workspace_sha256(workspace) != expected_workspace_digest:
        raise ValueError(
            "candidate workspace changed while creating the immutable render; rerun the cell"
        )
    render_digest = render_source_sha256(render)
    output = run_root / "evaluation"
    output.mkdir()
    config = load_container_config(root)
    vendor = root / "vendor"
    script = root / "infra/evaluator/evaluate.py"
    runtime_schema = root / "src/web3dgamebench/runtime_schema.py"
    evaluator_config_path = output / "evaluator-contract.json"
    shutil.copy2(
        root / "infra/evaluator/contracts" / f"{task.id}.json",
        output / "runtime-contract.json",
    )
    build = docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "-v",
        f"{render}:/workspace",
        "-v",
        f"{vendor}:/vendor:ro",
        "-w",
        "/workspace",
        "-e",
        "HOME=/tmp",
        "-e",
        "npm_config_cache=/vendor/npm-cache",
        "-e",
        "npm_config_offline=true",
        config.image,
        "sh",
        "-lc",
        "npm ci --ignore-scripts --no-audit --no-fund && npm run build",
        timeout=300,
        check=False,
    )
    (output / "build.stdout.log").write_text(build.stdout)
    (output / "build.stderr.log").write_text(build.stderr)
    if build.returncode == 0 and (render / "dist").is_dir():
        normalize_playable_bundle(render / "dist")
    post_build_render_digest = render_source_sha256(render)
    dist_digest = (
        render_dist_sha256(render / "dist") if (render / "dist").is_dir() else None
    )
    evaluator_config = _evaluator_config(
        root,
        task,
        script,
        runtime_schema,
        render_digest=render_digest,
        post_build_render_digest=post_build_render_digest,
        dist_digest=dist_digest,
    )
    evaluator_config_path.write_text(
        json.dumps(evaluator_config, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    report_path = output / "report.json"
    if build.returncode or dist_digest is None:
        report = {
            "schema_version": 1,
            "task_id": task.id,
            "trusted": True,
            "passed": False,
            "build": {
                "passed": False,
                "exit_code": build.returncode,
                "detail": (
                    "build command did not emit dist/" if dist_digest is None else None
                ),
            },
            "evaluator": _evaluation_identity(evaluator_config),
            "evidence": _render_evidence(evaluator_config),
            "checks": [_render_integrity_check(evaluator_config)],
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n")
    elif not evaluator_config["render_source_unchanged"]:
        report = {
            "schema_version": 1,
            "task_id": task.id,
            "trusted": True,
            "passed": False,
            "build": {"passed": True, "exit_code": 0},
            "evaluator": _evaluation_identity(evaluator_config),
            "evidence": _render_evidence(evaluator_config),
            "checks": [_render_integrity_check(evaluator_config)],
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n")
    else:
        network = f"web3dgamebench-evaluator-{uuid.uuid4().hex[:10]}"
        docker("network", "create", "--internal", network)
        try:
            result = docker(
                "run",
                "--rm",
                "--network",
                network,
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--shm-size",
                "1g",
                "-v",
                f"{render / 'dist'}:/submission:ro",
                "-v",
                f"{output}:/output",
                "-v",
                f"{script}:/evaluate.py:ro",
                "-v",
                f"{runtime_schema}:/runtime_schema.py:ro",
                config.evaluator_image,
                "python3",
                "/evaluate.py",
                "--contract",
                "/output/evaluator-contract.json",
                timeout=180,
                check=False,
            )
            (output / "evaluator.stdout.log").write_text(result.stdout)
            (output / "evaluator.stderr.log").write_text(result.stderr)
            if not report_path.is_file():
                report = {
                    "schema_version": 1,
                    "task_id": task.id,
                    "trusted": False,
                    "passed": False,
                    "build": {"passed": True, "exit_code": 0},
                    "evaluator": _evaluation_identity(evaluator_config),
                    "evidence": _render_evidence(evaluator_config),
                    "checks": [_render_integrity_check(evaluator_config)],
                    "evaluator_exit_code": result.returncode,
                    "infrastructure_errors": [
                        "evaluator exited without writing a report"
                    ],
                }
                report_path.write_text(json.dumps(report, indent=2) + "\n")
        finally:
            docker("network", "rm", network, check=False)

    report = json.loads(report_path.read_text())
    identity_errors = _report_identity_errors(report, evaluator_config, task.id)
    if identity_errors:
        report["trusted"] = False
        report["passed"] = False
        report.setdefault("infrastructure_errors", []).extend(identity_errors)
        report.setdefault("checks", []).append(
            {
                "name": "evaluation-identity",
                "passed": False,
                "detail": identity_errors,
            }
        )
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report_path
