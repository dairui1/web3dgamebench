from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path


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
            ".aetherplay-final.txt",
        ),
    )


def publish_runs(
    root: Path,
    runs: list[Path],
    games_repo: Path,
    *,
    replace: bool = False,
) -> Path:
    catalog_path = root / "site/public/data/catalog.json"
    catalog = json.loads(catalog_path.read_text())
    tasks = {task["id"]: task for task in catalog["tasks"]}
    seen: set[tuple[str, str]] = set()
    additions: dict[str, list[dict]] = {}

    for run_root in runs:
        manifest = json.loads((run_root / "manifest.json").read_text())
        evaluation = manifest.get("evaluation", {})
        if not evaluation.get("trusted") or not evaluation.get("passed"):
            raise PublishError(f"run is not trusted and passing: {run_root}")
        task_id = manifest["task"]["id"]
        profile = manifest["profile"]
        profile_id = profile["id"]
        key = (task_id, profile_id)
        if key in seen:
            raise PublishError(f"duplicate publication cell: {task_id}/{profile_id}")
        seen.add(key)
        if task_id not in tasks:
            raise PublishError(f"catalog has no task {task_id}")
        workspace = Path(manifest["workspace"])
        dist = run_root / "render/dist"
        if not dist.is_dir():
            raise PublishError(f"rendered dist is missing: {dist}")

        source_target = games_repo / "games" / task_id / profile_id
        play_target = root / "site/public/playground" / task_id / profile_id
        for target in (source_target, play_target):
            if target.exists():
                if not replace:
                    raise PublishError(f"publication target already exists: {target}")
                shutil.rmtree(target)
        source_target.parent.mkdir(parents=True, exist_ok=True)
        play_target.parent.mkdir(parents=True, exist_ok=True)
        _copy_source(workspace, source_target)
        shutil.copytree(dist, play_target)
        additions.setdefault(task_id, []).append(
            {
                "id": f"{task_id}--{profile_id}",
                "taskId": task_id,
                "profileId": profile_id,
                "harness": profile["harness"],
                "model": manifest.get("model_resolved") or profile["model"],
                "playUrl": f"/playground/{task_id}/{profile_id}/",
                "status": "published",
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
    catalog["generatedAt"] = datetime.now(UTC).isoformat()
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")
    return catalog_path
