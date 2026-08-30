from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from .container import docker, load_container_config


def _copy_submission(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("node_modules", "dist", ".git", ".aetherplay-final.txt"),
    )


def evaluate_run(root: Path, run_root: Path) -> Path:
    manifest_path = run_root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"run manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    workspace = Path(manifest["workspace"])
    if not workspace.is_dir():
        raise ValueError(f"run workspace not found: {workspace}")

    render = run_root / "render"
    if render.exists():
        raise ValueError(f"immutable render already exists: {render}")
    _copy_submission(workspace, render)
    output = run_root / "evaluation"
    output.mkdir()
    config = load_container_config(root)
    vendor = root / "vendor"

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
    report_path = output / "report.json"
    if build.returncode:
        report = {
            "schema_version": 1,
            "trusted": True,
            "passed": False,
            "build": {"passed": False, "exit_code": build.returncode},
            "checks": [],
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n")
    else:
        network = f"aetherplay-evaluator-{uuid.uuid4().hex[:10]}"
        docker("network", "create", "--internal", network)
        try:
            script = root / "infra/evaluator/evaluate.py"
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
                config.evaluator_image,
                "python3",
                "/evaluate.py",
                timeout=180,
                check=False,
            )
            (output / "evaluator.stdout.log").write_text(result.stdout)
            (output / "evaluator.stderr.log").write_text(result.stderr)
            if not report_path.is_file():
                report = {
                    "schema_version": 1,
                    "trusted": True,
                    "passed": False,
                    "build": {"passed": True, "exit_code": 0},
                    "checks": [],
                    "evaluator_exit_code": result.returncode,
                }
                report_path.write_text(json.dumps(report, indent=2) + "\n")
        finally:
            docker("network", "rm", network, check=False)

    report = json.loads(report_path.read_text())
    return report_path
