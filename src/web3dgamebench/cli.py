from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .config import ConfigError, validate_matrix
from .evaluator import evaluate_run
from .judge import run_judge
from .publisher import publish_runs
from .runner import run_once, runs_dir


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def command_plan(args: argparse.Namespace) -> int:
    season, profiles = validate_matrix(project_root(), args.season)
    cells = []
    for task in season.tasks:
        for profile_id in season.profiles:
            for attempt in range(1, season.attempts + 1):
                profile = profiles[profile_id]
                cells.append(
                    {
                        "task": task,
                        "profile": profile_id,
                        "harness": profile.harness,
                        "model": profile.model,
                        "effort": profile.effort or "official-default",
                        "attempt": attempt,
                    }
                )
    print(json.dumps({"season": season.id, "status": season.status, "cells": cells}, indent=2))
    return 0


def command_doctor(_: argparse.Namespace) -> int:
    root = project_root()
    checks = {
        "codex": shutil.which("codex") is not None,
        "claude": shutil.which("claude") is not None,
        "pi": shutil.which("pi") is not None,
        "node": shutil.which("node") is not None,
        "npm": shutil.which("npm") is not None,
        "docker": shutil.which("docker") is not None,
    }
    try:
        validate_matrix(root, "pilot-2026-09")
        checks["pilot_config"] = True
    except (ConfigError, ValueError) as error:
        checks["pilot_config"] = False
        checks["pilot_error"] = str(error)
    if checks["docker"]:
        result = subprocess.run(["docker", "version"], capture_output=True, check=False)
        checks["docker_daemon"] = result.returncode == 0
    print(json.dumps(checks, indent=2))
    return 0 if all(value is True for key, value in checks.items() if not key.endswith("error")) else 1


def command_run(args: argparse.Namespace) -> int:
    run_root = run_once(
        project_root(), args.task, args.profile, args.attempt, backend=args.backend
    )
    print(run_root)
    return 0


def command_vendor(_: argparse.Namespace) -> int:
    root = project_root()
    cache = root / "vendor/npm-cache"
    cache.mkdir(parents=True, exist_ok=True)
    starters = sorted((root / "tasks").glob("*/task/starter"))
    locks = []
    for starter in starters:
        result = subprocess.run(
            ["npm", "ci", "--ignore-scripts", "--cache", str(cache)],
            cwd=starter,
            check=False,
        )
        if result.returncode:
            return result.returncode
        container_config = root / "configs/container.toml"
        if shutil.which("docker") and container_config.is_file():
            from .container import load_container_config

            image = load_container_config(root).image
            with tempfile.TemporaryDirectory(prefix="web3dgamebench-vendor-") as temporary:
                seed = Path(temporary) / "starter"
                shutil.copytree(starter, seed, ignore=shutil.ignore_patterns("node_modules", "dist"))
                result = subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "-v",
                        f"{seed}:/workspace",
                        "-v",
                        f"{cache}:/cache",
                        "-w",
                        "/workspace",
                        image,
                        "npm",
                        "ci",
                        "--ignore-scripts",
                        "--cache",
                        "/cache",
                    ],
                    check=False,
                )
                if result.returncode:
                    return result.returncode
        import hashlib

        lock = starter / "package-lock.json"
        locks.append(
            {
                "starter": str(starter.relative_to(root)),
                "package_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
            }
        )
    manifest = {"schema_version": 1, "starters": locks}
    (root / "vendor/manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(root / "vendor/manifest.json")
    return 0


def command_evaluate(args: argparse.Namespace) -> int:
    report = evaluate_run(project_root(), Path(args.run).expanduser().resolve())
    print(report)
    return 0 if json.loads(report.read_text()).get("passed") else 1


def command_judge(args: argparse.Namespace) -> int:
    report = run_judge(
        project_root(),
        task_id=args.task,
        submission_id=args.submission,
        judge_id=args.judge,
        timeout_seconds=args.timeout,
    )
    print(report)
    return 0


def command_matrix(args: argparse.Namespace) -> int:
    root = project_root()
    season, _ = validate_matrix(root, args.season)
    matrix_id = f"{season.id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    receipt_path = runs_dir() / f"matrix-{matrix_id}.json"
    receipt = {
        "schema_version": 1,
        "matrix_id": matrix_id,
        "season": season.id,
        "backend": args.backend,
        "status": "running",
        "cells": [],
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    for task in season.tasks:
        for profile in season.profiles:
            for attempt in range(1, season.attempts + 1):
                cell = {"task": task, "profile": profile, "attempt": attempt}
                try:
                    run_root = run_once(
                        root, task, profile, attempt, backend=args.backend
                    )
                    report_path = evaluate_run(root, run_root)
                    report = json.loads(report_path.read_text())
                    manifest = json.loads((run_root / "manifest.json").read_text())
                    cell.update(
                        {
                            "run": str(run_root),
                            "evaluation": str(report_path),
                            "playable": bool(report.get("passed")),
                            "passed": manifest.get("status") == "candidate-complete"
                            and bool(report.get("passed")),
                        }
                    )
                except (OSError, RuntimeError, ValueError) as error:
                    cell.update({"infrastructure_error": str(error), "passed": False})
                receipt["cells"].append(cell)
                receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    receipt["status"] = (
        "complete" if not any("infrastructure_error" in cell for cell in receipt["cells"]) else "incomplete"
    )
    receipt["completed_at"] = datetime.now(UTC).isoformat()
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt_path)
    return 0 if receipt["status"] == "complete" else 1


def command_publish(args: argparse.Namespace) -> int:
    root = project_root()
    games_repo = (
        Path(args.games_repo).expanduser().resolve()
        if args.games_repo
        else root.parent / "web3dgamebench-games"
    )
    catalog = publish_runs(
        root,
        [Path(item).expanduser().resolve() for item in args.run],
        games_repo,
        replace=args.replace,
    )
    print(catalog)
    return 0


def command_invalidate(args: argparse.Namespace) -> int:
    run_root = Path(args.run).expanduser().resolve()
    manifest_path = run_root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"run manifest not found: {manifest_path}")
    sidecar = run_root / "withdrawal.json"
    if sidecar.exists():
        raise ValueError(f"run is already withdrawn: {run_root}")
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "withdrawn_at": datetime.now(UTC).isoformat(),
                "reason": args.reason,
            },
            indent=2,
        )
        + "\n"
    )
    print(sidecar)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="web3dgamebench")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor")
    doctor.set_defaults(func=command_doctor)
    plan = commands.add_parser("plan")
    plan.add_argument("--season", required=True)
    plan.set_defaults(func=command_plan)
    run = commands.add_parser("run")
    run.add_argument("--task", required=True)
    run.add_argument("--profile", required=True)
    run.add_argument("--attempt", type=int, default=1)
    run.add_argument("--backend", choices=("native", "container"), default="container")
    run.set_defaults(func=command_run)
    vendor = commands.add_parser("vendor")
    vendor.set_defaults(func=command_vendor)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--run", required=True)
    evaluate.set_defaults(func=command_evaluate)
    judge = commands.add_parser("judge")
    judge.add_argument("--task", required=True)
    judge.add_argument("--submission", required=True)
    judge.add_argument("--judge", default="pi-sol-medium")
    judge.add_argument("--timeout", type=int, default=900)
    judge.set_defaults(func=command_judge)
    matrix = commands.add_parser("matrix")
    matrix.add_argument("--season", required=True)
    matrix.add_argument("--backend", choices=("native", "container"), default="container")
    matrix.set_defaults(func=command_matrix)
    publish = commands.add_parser("publish")
    publish.add_argument("--run", action="append", required=True)
    publish.add_argument("--games-repo")
    publish.add_argument("--replace", action="store_true")
    publish.set_defaults(func=command_publish)
    invalidate = commands.add_parser("invalidate")
    invalidate.add_argument("--run", required=True)
    invalidate.add_argument("--reason", required=True)
    invalidate.set_defaults(func=command_invalidate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
