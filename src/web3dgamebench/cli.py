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
from .matrix import (
    MatrixInterrupted,
    create_plan_for_matrix,
    create_preflight_plan,
    resume_matrix,
    start_matrix,
    write_preflight_plan,
)
from .publisher import load_publication_matrix, publish_runs
from .runner import run_once


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def command_plan(args: argparse.Namespace) -> int:
    root = project_root()
    plan = create_preflight_plan(root, args.season)
    if args.output:
        path = write_preflight_plan(Path(args.output), plan)
        print(path)
    else:
        print(json.dumps(plan, indent=2))
    return 0


def _help_has(executable: str, arguments: tuple[str, ...], flags: set[str]) -> bool:
    path = shutil.which(executable)
    if path is None:
        return False
    try:
        result = subprocess.run(
            [path, *arguments],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    output = f"{result.stdout}\n{result.stderr}"
    return result.returncode == 0 and all(flag in output for flag in flags)


def _codex_goal_capability() -> bool:
    path = shutil.which("codex")
    if path is None:
        return False
    try:
        result = subprocess.run(
            [path, "features", "list"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode:
        return False
    return any(
        fields[:3] == ["goals", "stable", "true"]
        for line in result.stdout.splitlines()
        if len(fields := line.split()) >= 3
    )


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
    checks.update(
        {
            "codex_runtime_contract": _help_has(
                "codex",
                ("exec", "--help"),
                {
                    "--config",
                    "--enable",
                    "--strict-config",
                    "--ignore-user-config",
                    "--ephemeral",
                    "--json",
                },
            )
            and _codex_goal_capability(),
            "claude_runtime_contract": _help_has(
                "claude",
                ("--help",),
                {
                    "--append-system-prompt",
                    "--setting-sources",
                    "--no-session-persistence",
                    "--output-format",
                    "--strict-mcp-config",
                },
            ),
            "pi_runtime_contract": _help_has(
                "pi",
                ("--help",),
                {
                    "--append-system-prompt",
                    "--no-session",
                    "--no-context-files",
                    "--mode",
                    "--no-approve",
                },
            ),
        }
    )
    for season_id, check_name in (
        ("pilot-2026-09", "pilot_config"),
        ("season-1", "season_1_config"),
    ):
        try:
            validate_matrix(root, season_id)
            checks[check_name] = True
        except (ConfigError, ValueError) as error:
            checks[check_name] = False
            checks[f"{check_name}_error"] = str(error)
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
        run_root=(Path(args.run).expanduser().resolve() if args.run else None),
        dist_path=(Path(args.dist).expanduser().resolve() if args.dist else None),
        judge_id=args.judge,
        timeout_seconds=args.timeout,
    )
    print(report)
    return 0 if json.loads(report.read_text()).get("status") == "complete" else 1


def command_matrix(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        if args.resume:
            receipt_path = resume_matrix(
                root,
                Path(args.resume),
                backend=args.backend,
            )
        else:
            plan_path = (
                Path(args.plan).expanduser().resolve()
                if args.plan
                else create_plan_for_matrix(root, args.season)
            )
            receipt_path = start_matrix(
                root,
                plan_path,
                backend=args.backend or "container",
            )
    except MatrixInterrupted as error:
        print(error.receipt_path)
        return 130
    print(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    return 0 if receipt.get("status") == "complete" else 1


def command_publish(args: argparse.Namespace) -> int:
    root = project_root()
    games_repo = (
        Path(args.games_repo).expanduser().resolve()
        if args.games_repo
        else root.parent / "web3dgamebench-games"
    )
    matrix_receipt = None
    if args.matrix:
        matrix_receipt, runs = load_publication_matrix(root, Path(args.matrix))
    else:
        runs = [Path(item).expanduser().resolve() for item in args.run]
    catalog = publish_runs(
        root, runs, games_repo, replace=args.replace, matrix_receipt=matrix_receipt
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
    plan.add_argument("--output")
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
    judge_source = judge.add_mutually_exclusive_group(required=True)
    judge_source.add_argument(
        "--submission",
        help="published submission ID under site/public/playground/<task>/",
    )
    judge_source.add_argument(
        "--run",
        help="private benchmark run root; judges its immutable render/dist build",
    )
    judge_source.add_argument(
        "--dist",
        help="explicit private static dist directory containing index.html",
    )
    judge.add_argument("--judge", default="pi-sol-medium")
    judge.add_argument("--timeout", type=int, default=900)
    judge.set_defaults(func=command_judge)
    matrix = commands.add_parser("matrix")
    matrix_source = matrix.add_mutually_exclusive_group(required=True)
    matrix_source.add_argument("--season")
    matrix_source.add_argument("--plan")
    matrix_source.add_argument("--resume")
    matrix.add_argument("--backend", choices=("native", "container"))
    matrix.set_defaults(func=command_matrix)
    publish = commands.add_parser("publish")
    publish_source = publish.add_mutually_exclusive_group(required=True)
    publish_source.add_argument("--run", action="append")
    publish_source.add_argument(
        "--matrix", help="closed matrix receipt; publishes every trusted cell"
    )
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
