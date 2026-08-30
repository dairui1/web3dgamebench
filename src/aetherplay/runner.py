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


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
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
    shutil.copytree(task.starter, workspace, dirs_exist_ok=True)
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
        "task": {"id": task.id, "digest": _tree_digest(task.root)},
        "profile": asdict(profile),
        "attempt": attempt,
        "workspace": str(workspace),
        "status": "prepared",
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return run_root, workspace


def run_native(root: Path, task_id: str, profile_id: str, attempt: int = 1) -> Path:
    profiles = load_profiles(root)
    if profile_id not in profiles:
        raise ValueError(f"unknown profile: {profile_id}")
    profile = profiles[profile_id]
    task = load_task(root, task_id)
    run_root, workspace = prepare(root, task, profile, attempt)
    prompt = _candidate_prompt(task)
    invocation = build_invocation(profile, workspace, prompt)
    environment = os.environ.copy()
    environment.update(invocation.env)
    if profile.credential_env and profile.runtime_env:
        value = environment.get(profile.credential_env)
        if not value:
            raise RuntimeError(f"missing required environment variable {profile.credential_env}")
        environment[profile.runtime_env] = value
    started = time.monotonic()
    try:
        result = subprocess.run(
            invocation.argv,
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
            "workspace_digest": _tree_digest(workspace),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return run_root
