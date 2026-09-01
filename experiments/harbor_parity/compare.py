from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def find_one(root: Path, names: tuple[str, ...]) -> Path:
    matches = sorted(
        path
        for name in names
        for path in root.rglob(name)
        if path.is_file()
    )
    if len(matches) != 1:
        raise ValueError(f"expected one of {names!r} below {root}, found {matches!r}")
    return matches[0]


def find_workspace(trial: Path) -> Path:
    candidates = [
        trial / "artifacts" / "workspace",
        trial / "artifacts" / "logs" / "artifacts" / "workspace",
    ]
    candidates.extend(path for path in trial.rglob("workspace") if path.is_dir())
    valid = [path for path in candidates if (path / "package.json").is_file()]
    unique = list(dict.fromkeys(path.resolve() for path in valid))
    if len(unique) != 1:
        raise ValueError(f"expected one collected Harbor workspace below {trial}, found {unique!r}")
    return unique[0]


def goal_summary(manifest: dict | None, events_path: Path | None, source_root: Path) -> dict:
    if manifest is not None:
        goal = manifest.get("goal") or {}
        return {
            "activation_status": goal.get("activation_status"),
            "lifecycle": goal.get("lifecycle", []),
        }
    if events_path is None:
        return {"activation_status": "missing", "lifecycle": []}
    from web3dgamebench.runtimes import parse_goal_lifecycle

    lifecycle = parse_goal_lifecycle(events_path.read_text(encoding="utf-8"))
    terminal = next(
        (
            item.get("status")
            for item in reversed(lifecycle)
            if item.get("tool") == "update_goal"
        ),
        None,
    )
    created = any(item.get("tool") == "create_goal" for item in lifecycle)
    status = f"observed-{terminal}" if terminal else ("observed-active" if created else "not-observed")
    return {"activation_status": status, "lifecycle": lifecycle}


def evaluator_vector(report: dict) -> dict:
    return {
        "trusted": report.get("trusted"),
        "passed": report.get("passed"),
        "build": (report.get("build") or {}).get("passed"),
        "checks": {
            item.get("name"): item.get("passed")
            for item in report.get("checks", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        },
        "infrastructure_errors": report.get("infrastructure_errors", []),
    }


def evaluate_harbor_workspace(source_root: Path, workspace: Path) -> dict:
    from web3dgamebench.artifacts import candidate_workspace_sha256, file_tree_sha256
    from web3dgamebench.evaluator import evaluate_run

    task = source_root / "tasks" / "bombsite-retake" / "task"
    with tempfile.TemporaryDirectory(prefix="web3d-harbor-eval-") as temporary:
        run_root = Path(temporary)
        copied = run_root / "workspace"
        shutil.copytree(workspace, copied)
        manifest = {
            "schema_version": 1,
            "run_id": "harbor-parity-materialized",
            "task": {
                "id": "bombsite-retake",
                "digest": file_tree_sha256(task, excluded=frozenset({"node_modules", "dist"})),
                "brief_sha256": __import__("hashlib").sha256((task / "goal.en.md").read_bytes()).hexdigest(),
            },
            "workspace": str(copied),
            "workspace_digest": candidate_workspace_sha256(copied),
            "status": "candidate-complete",
        }
        (run_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return read_json(evaluate_run(source_root, run_root))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--original-run", type=Path, required=True)
    parser.add_argument("--harbor-trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    sys.path.insert(0, str(source_root / "src"))
    original_manifest = read_json(args.original_run / "manifest.json")
    original_report_path = args.original_run / "evaluation" / "report.json"
    if not original_report_path.is_file():
        from web3dgamebench.evaluator import evaluate_run

        original_report_path = evaluate_run(source_root, args.original_run.resolve())
    original_report = read_json(original_report_path)

    harbor_workspace = find_workspace(args.harbor_trial.resolve())
    harbor_events = find_one(args.harbor_trial.resolve(), ("events.jsonl",))
    harbor_report = evaluate_harbor_workspace(source_root, harbor_workspace)
    original_goal = goal_summary(original_manifest, None, source_root)
    harbor_goal = goal_summary(None, harbor_events, source_root)
    original_vector = evaluator_vector(original_report)
    harbor_vector = evaluator_vector(harbor_report)
    comparison = {
        "schema_version": 1,
        "task": "bombsite-retake",
        "profile": original_manifest.get("profile", {}).get("id"),
        "input_contract": {
            "task_brief_preserved_original": original_manifest.get("prompt", {}).get("task_brief_preserved"),
            "task_brief_preserved_harbor": __import__("hashlib").sha256(
                (harbor_workspace / "TASK.md").read_bytes()
            ).hexdigest()
            == __import__("hashlib").sha256(
                (source_root / "tasks/bombsite-retake/task/goal.en.md").read_bytes()
            ).hexdigest(),
        },
        "goal": {"original": original_goal, "harbor": harbor_goal},
        "exit_classification": {
            "original": original_manifest.get("status"),
            "harbor": "candidate-complete" if harbor_goal["activation_status"] == "observed-complete" else "needs-review",
        },
        "evaluator": {
            "original": original_vector,
            "harbor": harbor_vector,
            "same_check_names": sorted(original_vector["checks"]) == sorted(harbor_vector["checks"]),
            "same_outcomes": original_vector == harbor_vector,
        },
        "interpretation": (
            "One paired run is a contract-parity spike, not statistical score parity. "
            "A behavioral difference can be model sampling; an input, Goal, exit, or evaluator identity "
            "difference is adapter failure."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(comparison, indent=2) + "\n")
    print(args.output)
    hard_fail = not all(comparison["input_contract"].values()) or any(
        side["activation_status"] != "observed-complete"
        for side in comparison["goal"].values()
    )
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
