from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from . import __version__
from .config import ConfigError, validate_matrix
from .runner import run_native


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
    if args.backend != "native":
        raise SystemExit("container execution is prepared in infra/candidate but not enabled until its image passes doctor")
    run_root = run_native(project_root(), args.task, args.profile, args.attempt)
    print(run_root)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aetherplay")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
