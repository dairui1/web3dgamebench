from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import ConfigError, load_task
from .evaluator import render_dist_sha256, render_source_sha256
from .matrix import (
    MatrixError,
    load_matrix_receipt,
    validate_publication_receipt,
)
from .pricing import PricingError, estimate_official_cost, load_pricing
from .trace_replay import TraceReplayError, export_trace_replay


class PublishError(RuntimeError):
    pass


def _copy_source(workspace: Path, destination: Path) -> None:
    shutil.copytree(
        workspace,
        destination,
        ignore=shutil.ignore_patterns(
            "node_modules",
            "dist",
            ".git",
            "TASK.md",
            "AGENTS.md",
            ".web3dgamebench-final.txt",
            ".aetherplay-final.txt",
        ),
    )


def load_publication_matrix(
    root: Path, receipt_path: Path
) -> tuple[dict[str, Any], list[Path]]:
    """Load a closed matrix and return its complete set of trusted run roots."""

    try:
        receipt, _plan = validate_publication_receipt(
            root, load_matrix_receipt(receipt_path.expanduser().resolve())
        )
    except MatrixError as error:
        raise PublishError(str(error)) from error
    runs = [
        Path(cell["run"]).expanduser().resolve()
        for cell in receipt["cells"]
        if cell["trusted"] is True
    ]
    if not runs:
        raise PublishError("closed matrix has no trusted passing runs")
    if len(runs) != len(set(runs)):
        raise PublishError("closed matrix references a run more than once")
    return receipt, runs


def _matrix_cells_by_run(receipt: dict[str, Any]) -> dict[Path, dict[str, Any]]:
    return {
        Path(cell["run"]).expanduser().resolve(): cell
        for cell in receipt["cells"]
        if cell["trusted"] is True
    }


def _task_season(root: Path, task_id: str) -> str | None:
    if not (root / "tasks" / task_id / "task" / "task.toml").is_file():
        return None
    try:
        return load_task(root, task_id).season
    except ConfigError as error:
        raise PublishError(f"invalid task configuration for {task_id}: {error}") from error


def _verify_render_evidence(run_root: Path, evaluation: dict[str, Any]) -> Path:
    render = run_root / "render"
    dist = render / "dist"
    if not dist.is_dir():
        raise PublishError(f"rendered dist is missing: {dist}")
    evidence = evaluation.get("evidence")
    evaluator = evaluation.get("evaluator")
    if not isinstance(evidence, dict) or not isinstance(evaluator, dict):
        raise PublishError(f"run has no immutable render evidence: {run_root}")
    expected = evidence.get("post_build_render_source_sha256")
    if (
        evidence.get("render_source_unchanged") is not True
        or not isinstance(expected, str)
        or evaluator.get("render_source_sha256") != expected
    ):
        raise PublishError(f"run render evidence is inconsistent: {run_root}")
    if render_source_sha256(render) != expected:
        raise PublishError(f"evaluated render source changed after admission: {run_root}")
    expected_dist = evidence.get("render_dist_sha256")
    if not isinstance(expected_dist, str):
        raise PublishError(f"run has no immutable playable-bundle evidence: {run_root}")
    if render_dist_sha256(dist) != expected_dist:
        raise PublishError(f"evaluated playable bundle changed after admission: {run_root}")
    return render


def _publication_catalog(
    root: Path,
    current: dict[str, Any],
    season_id: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    path = root / "configs" / "catalogs" / f"{season_id}.json"
    if path.is_file():
        try:
            catalog = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise PublishError(f"cannot load frozen season catalog: {path}") from error
    elif current.get("season", {}).get("id") == season_id:
        catalog = current
    else:
        raise PublishError(f"frozen season catalog is missing: {path}")
    if catalog.get("schema_version") != 1:
        raise PublishError(f"invalid catalog template for {season_id}")
    if catalog.get("season", {}).get("id") != season_id:
        raise PublishError(f"catalog template does not describe {season_id}")
    catalog_tasks = catalog.get("tasks")
    if not isinstance(catalog_tasks, list):
        raise PublishError(f"catalog template has no tasks for {season_id}")
    task_ids = [task.get("id") for task in catalog_tasks if isinstance(task, dict)]
    expected = plan.get("season", {}).get("tasks")
    if task_ids != expected:
        raise PublishError("catalog task order does not match the frozen matrix plan")
    for task in catalog_tasks:
        if not all(
            isinstance(task.get(field), str) and task[field]
            for field in ("id", "title", "titleZh", "summary", "summaryZh", "genre", "genreZh")
        ):
            raise PublishError(f"catalog task metadata is incomplete: {task.get('id')}")
        evaluation = task.get("evaluation")
        if not isinstance(evaluation, dict) or not isinstance(
            evaluation.get("checklist"), list
        ):
            raise PublishError(f"catalog task evaluation is incomplete: {task['id']}")
        task.setdefault("submissions", [])
    return catalog


def publish_runs(
    root: Path,
    runs: list[Path],
    games_repo: Path,
    *,
    replace: bool = False,
    matrix_receipt: dict[str, Any] | None = None,
) -> Path:
    catalog_path = root / "site/public/data/catalog.json"
    catalog = json.loads(catalog_path.read_text())
    seen: set[tuple[str, str]] = set()
    additions: dict[str, list[dict]] = {}
    pricing = load_pricing(root)
    if catalog.get("season", {}).get("id") == "season-1" and matrix_receipt is None:
        raise PublishError("season-1 publication requires a closed matrix receipt")
    if matrix_receipt is not None:
        try:
            matrix_receipt, plan = validate_publication_receipt(root, matrix_receipt)
        except MatrixError as error:
            raise PublishError(str(error)) from error
    matrix_cells = (
        _matrix_cells_by_run(matrix_receipt) if matrix_receipt is not None else {}
    )
    resolved_runs = [run.expanduser().resolve() for run in runs]
    if matrix_receipt is not None and set(resolved_runs) != set(matrix_cells):
        raise PublishError(
            "publication runs must exactly match all trusted cells in the closed matrix"
        )
    if matrix_receipt is not None:
        catalog = _publication_catalog(root, catalog, matrix_receipt["season"], plan)
    tasks = {task["id"]: task for task in catalog["tasks"]}

    for run_root in resolved_runs:
        manifest = json.loads((run_root / "manifest.json").read_text())
        evaluation_path = run_root / "evaluation/report.json"
        evaluation = (
            json.loads(evaluation_path.read_text()) if evaluation_path.is_file() else {}
        )
        if not evaluation.get("trusted") or not evaluation.get("passed"):
            raise PublishError(f"run is not trusted and passing: {run_root}")
        run_status = str(manifest.get("status", "unknown"))
        if run_status != "candidate-complete":
            raise PublishError(f"run is not publishable: {run_root} ({run_status})")
        task_id = manifest["task"]["id"]
        profile = manifest["profile"]
        profile_id = profile["id"]
        if task_id not in tasks:
            raise PublishError(f"catalog has no task {task_id}")
        task_season = _task_season(root, task_id)
        if task_season == "season-1" and matrix_receipt is None:
            raise PublishError("season-1 publication requires a closed matrix receipt")
        if matrix_receipt is not None:
            if matrix_receipt.get("season") != task_season:
                raise PublishError(
                    f"run task {task_id} does not belong to matrix season "
                    f"{matrix_receipt.get('season')}"
                )
            cell = matrix_cells[run_root]
            if (
                cell.get("task") != task_id
                or cell.get("profile") != profile_id
                or cell.get("attempt") != manifest.get("attempt")
            ):
                raise PublishError(f"run identity does not match matrix cell: {run_root}")
        key = (task_id, profile_id)
        if key in seen:
            raise PublishError(f"duplicate publication cell: {task_id}/{profile_id}")
        seen.add(key)
        render = _verify_render_evidence(run_root, evaluation)
        dist = render / "dist"

        source_target = games_repo / "games" / task_id / profile_id
        play_target = root / "site/public/playground" / task_id / profile_id
        for target in (source_target, play_target):
            if target.exists():
                if not replace:
                    raise PublishError(f"publication target already exists: {target}")
                shutil.rmtree(target)
        source_target.parent.mkdir(parents=True, exist_ok=True)
        play_target.parent.mkdir(parents=True, exist_ok=True)
        _copy_source(render, source_target)
        shutil.copytree(dist, play_target)
        trace_id = str(manifest.get("run_id") or run_root.name)
        trace_target = root / "site/public/data/traces" / f"{trace_id}.json"
        try:
            replay = export_trace_replay(run_root, trace_target)
        except TraceReplayError as error:
            raise PublishError(str(error)) from error
        model = manifest.get("model_resolved") or profile["model"]
        try:
            cost = estimate_official_cost(
                pricing,
                model,
                replay["summary"]["usage"],
                replay["traceFormat"],
                replay.get("createdAt"),
            )
        except PricingError as error:
            raise PublishError(str(error)) from error
        additions.setdefault(task_id, []).append(
            {
                "id": f"{task_id}--{profile_id}",
                "taskId": task_id,
                "profileId": profile_id,
                "harness": profile["harness"],
                "model": model,
                "playUrl": f"/playground/{task_id}/{profile_id}/",
                "traceId": trace_id,
                "replayUrl": f"/replay/{trace_id}",
                "traceSummary": {
                    "durationSeconds": replay["durationSeconds"],
                    "eventCount": replay["summary"]["eventCount"],
                    "toolCalls": replay["summary"]["toolCalls"],
                    "errors": replay["summary"]["errors"],
                },
                "officialApiCost": cost,
                "status": "published",
                "runStatus": run_status,
            }
        )

    for task_id, submissions in additions.items():
        existing = {
            item["profileId"]: item for item in tasks[task_id].get("submissions", [])
        }
        existing.update({item["profileId"]: item for item in submissions})
        tasks[task_id]["submissions"] = sorted(
            existing.values(), key=lambda item: item["profileId"]
        )
    catalog["season"]["status"] = "public-voting"
    catalog["generatedAt"] = datetime.now(UTC).isoformat()
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    return catalog_path
