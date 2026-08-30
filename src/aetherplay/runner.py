from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .config import Profile, Task, load_profiles, load_task
from .container import (
    ensure_plane,
    load_container_config,
    prepare_dependencies,
    wrap_command,
)
from .runtimes import build_invocation, parse_resolved_model


def runs_dir() -> Path:
    configured = os.environ.get("AETHERPLAY_RUNS_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".local/state/aetherplay/runs"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path, *, excluded: frozenset[str] = frozenset()) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and not excluded.intersection(item.relative_to(root).parts)
    ):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


def _candidate_prompt(task: Task) -> str:
    return (
        "Implement the complete benchmark task in TASK.md. Work only inside this workspace. "
        "Do not use the network or external assets. You have the supplied dependency set. "
        "Build and inspect the game at both required viewports before finishing. Preserve any "
        "failures honestly; do not claim checks you did not run.\n\n" + task.brief.read_text(encoding="utf-8")
    )


def prepare(root: Path, task: Task, profile: Profile, attempt: int = 1) -> tuple[Path, Path]:
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{task.id}-{profile.id}-a{attempt}-{uuid.uuid4().hex[:8]}"
    run_root = runs_dir() / run_id
    workspace = run_root / "workspace"
    workspace.mkdir(parents=True)
    shutil.copytree(
        task.starter,
        workspace,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("node_modules", "dist"),
    )
    shutil.copy2(task.brief, workspace / "TASK.md")
    (workspace / "AGENTS.md").write_text(
        "# Candidate rules\n\nImplement TASK.md in this directory. Do not access the network, parent "
        "directories, credentials, other submissions, or production services. Build and test the game.\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "task": {
            "id": task.id,
            "digest": _tree_digest(task.root, excluded=frozenset({"node_modules", "dist"})),
        },
        "profile": asdict(profile),
        "attempt": attempt,
        "workspace": str(workspace),
        "status": "prepared",
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return run_root, workspace


def run_native(root: Path, task_id: str, profile_id: str, attempt: int = 1) -> Path:
    return run_once(root, task_id, profile_id, attempt, backend="native")


def run_once(
    root: Path, task_id: str, profile_id: str, attempt: int = 1, *, backend: str = "container"
) -> Path:
    profiles = load_profiles(root)
    if profile_id not in profiles:
        raise ValueError(f"unknown profile: {profile_id}")
    profile = profiles[profile_id]
    task = load_task(root, task_id)
    run_root, workspace = prepare(root, task, profile, attempt)
    prompt = _candidate_prompt(task)
    invocation_workspace = Path("/workspace") if backend == "container" else workspace
    invocation = build_invocation(
        profile, invocation_workspace, prompt, isolation="container" if backend == "container" else "runtime"
    )
    environment = os.environ.copy()
    environment.update(invocation.env)
    argv: tuple[str, ...] | list[str] = invocation.argv
    credential_dir = run_root / ".runtime-home"
    plane = None
    passed_environment: dict[str, str] = {}
    if backend == "container":
        container_config = load_container_config(root)
        plane = ensure_plane(root, container_config)
        prepare_dependencies(root, container_config, workspace)
        argv, passed_environment = wrap_command(
            invocation.argv,
            root=root,
            config=container_config,
            workspace=workspace,
            profile=profile,
            credential_dir=credential_dir,
        )
    elif profile.credential_env and profile.runtime_env:
        value = environment.get(profile.credential_env)
        if not value:
            raise RuntimeError(f"missing required environment variable {profile.credential_env}")
        environment[profile.runtime_env] = value
    started = time.monotonic()
    try:
        result = subprocess.run(
            argv,
            cwd=workspace,
            input=prompt if invocation.stdin_prompt else None,
            text=True,
            capture_output=True,
            timeout=profile.timeout_seconds,
            env=environment,
            check=False,
        )
        timed_out = False
    except subprocess.TimeoutExpired as error:
        result = subprocess.CompletedProcess(invocation.argv, 124, error.stdout or "", error.stderr or "")
        timed_out = True
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    stderr = result.stderr if isinstance(result.stderr, str) else ""
    (run_root / "events.jsonl").write_text(stdout, encoding="utf-8")
    (run_root / "stderr.log").write_text(stderr, encoding="utf-8")
    final_path = workspace / ".aetherplay-final.txt"
    if final_path.exists():
        shutil.copy2(final_path, run_root / "final.txt")
        final_path.unlink()
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(
        {
            "status": "timeout" if timed_out else ("candidate-complete" if result.returncode == 0 else "candidate-failure"),
            "exit_code": result.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "trace_format": invocation.trace_format,
            "model_resolved": parse_resolved_model(invocation.trace_format, stdout),
            "workspace_digest": _tree_digest(
                workspace, excluded=frozenset({"node_modules"})
            ),
            "backend": backend,
            "container_plane": plane,
            "environment_names": sorted(passed_environment),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.rmtree(credential_dir, ignore_errors=True)
    return run_root
