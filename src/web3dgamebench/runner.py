from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .artifacts import candidate_workspace_sha256, file_tree_sha256
from .config import Profile, Task, load_profiles, load_task
from .container import (
    ensure_plane,
    load_container_config,
    prepare_dependencies,
    wrap_command,
)
from .process import ProcessTimedOut, run_captured
from .runtimes import (
    build_invocation,
    goal_activation_status,
    parse_goal_lifecycle,
    parse_resolved_model,
)


class RunInterrupted(KeyboardInterrupt):
    def __init__(self, run_root: Path):
        super().__init__(f"candidate run interrupted: {run_root}")
        self.run_root = run_root


def runs_dir() -> Path:
    configured = os.environ.get("WEB3DGAMEBENCH_RUNS_DIR") or os.environ.get(
        "AETHERPLAY_RUNS_DIR"
    )
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local/state/web3dgamebench/runs"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _append_lifecycle_terminal(path: Path, status: str, reason: str) -> str:
    event = {
        "type": "entry_appended",
        "entry": {
            "customType": "web3dgamebench-lifecycle",
            "data": {
                "schema_version": 2,
                "status": status,
                "source": "runner",
                "reason": reason,
            },
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    return path.read_text(encoding="utf-8")


def _terminal_lifecycle_status(stdout: str) -> str | None:
    return next(
        (
            event.get("status")
            for event in reversed(parse_goal_lifecycle(stdout))
            if event.get("tool") == "update_goal"
            and event.get("status")
            in {"complete", "blocked", "interrupted", "timed_out"}
        ),
        None,
    )


def _candidate_prompt(task: Task) -> str:
    return (
        "Implement the benchmark game in TASK.md. Work only inside this workspace. "
        "Do not use the network or external assets. You have the supplied dependency set. "
        "After the final relevant change, run npm run build once and stop when it succeeds. "
        "Do not write or run browser automation, automated runtime checks, autopilots, or full "
        "playthroughs; the post-run evaluator handles runtime verification. Preserve build "
        "failures honestly; do not claim a build you did not run.\n\n"
        + task.brief.read_text(encoding="utf-8")
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
            "digest": file_tree_sha256(
                task.root, excluded=frozenset({"node_modules", "dist"})
            ),
            "brief_sha256": _sha256(task.brief),
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
    root: Path,
    task_id: str,
    profile_id: str,
    attempt: int = 1,
    *,
    backend: str = "container",
    cancel_event: threading.Event | None = None,
    calibration: bool = False,
) -> Path:
    if backend not in {"native", "container", "harbor"}:
        raise ValueError(f"unknown backend: {backend}")
    profiles = load_profiles(root)
    if profile_id not in profiles:
        raise ValueError(f"unknown profile: {profile_id}")
    profile = profiles[profile_id]
    if calibration and profile.harness != "pi":
        raise ValueError("calibration timeout is reserved for Pi adapter diagnostics")
    task = load_task(root, task_id)
    run_root, workspace = prepare(root, task, profile, attempt)
    prompt = _candidate_prompt(task)
    invocation_workspace = (
        Path("/workspace") if backend in {"container", "harbor"} else workspace
    )
    invocation = build_invocation(
        profile,
        invocation_workspace,
        prompt,
        isolation="container" if backend in {"container", "harbor"} else "runtime",
        goal_mode=task.goal_mode,
        goal_completion=task.goal_completion,
        task_sha256=_sha256(task.brief),
    )
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    container_config = load_container_config(root)
    effective_timeout_seconds = (
        container_config.pi_adapter.calibration_total_timeout_seconds
        if calibration
        else container_config.candidate_total_timeout_seconds
    )
    manifest["execution_mode"] = "calibration" if calibration else "benchmark"
    manifest["candidate_timeout_seconds"] = effective_timeout_seconds
    manifest["prompt"] = {
        "candidate_sha256": invocation.candidate_prompt_sha256,
        "task_brief_sha256": _sha256(task.brief),
        "delivery": "stdin" if invocation.stdin_prompt else "argv",
    }
    if invocation.goal_activation:
        goal_receipt = asdict(invocation.goal_activation)
        goal_receipt["activation_status"] = (
            "awaiting-trace" if invocation.goal_activation.native_goal else "configured"
        )
        goal_receipt["lifecycle"] = []
        manifest["goal"] = goal_receipt
    else:
        manifest["goal"] = {
            "mode": "none",
            "activation_method": "none",
            "activation_status": "not-requested",
        }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    environment = os.environ.copy()
    environment.update(invocation.env)
    argv: tuple[str, ...] | list[str] = invocation.argv
    credential_dir = run_root / ".runtime-home"
    plane = None
    container_name = None
    passed_environment: dict[str, str] = {}
    failure_scope = None
    if backend == "container":
        plane = ensure_plane(root, container_config)
        prepare_dependencies(root, container_config, workspace)
        container_name = f"web3dgamebench-run-{run_root.name[-28:]}".lower()
        argv, passed_environment = wrap_command(
            invocation.argv,
            root=root,
            config=container_config,
            workspace=workspace,
            profile=profile,
            credential_dir=credential_dir,
            container_name=container_name,
        )
    elif profile.credential_env and profile.runtime_env:
        value = environment.get(profile.credential_env)
        if not value:
            raise RuntimeError(f"missing required environment variable {profile.credential_env}")
        environment[profile.runtime_env] = value
    started = time.monotonic()
    events_path = run_root / "events.jsonl"
    stderr_path = run_root / "stderr.log"
    try:
        def cleanup_container() -> None:
            if container_name is None:
                return
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

        if backend == "harbor":
            from .harbor_backend import execute_harbor

            result = execute_harbor(
                root,
                run_root,
                workspace,
                task_id=task.id,
                profile=profile,
                instruction=prompt,
                invocation=invocation,
                cancel_event=cancel_event,
                candidate_timeout_seconds=effective_timeout_seconds,
            )
            plane = result.plane
            passed_environment = result.environment_names
            failure_scope = result.failure_scope
        else:
            result = run_captured(
                argv,
                cwd=workspace,
                env=environment,
                input_text=prompt if invocation.stdin_prompt else None,
                cancel_event=cancel_event,
                cleanup=cleanup_container if container_name else None,
                timeout_seconds=effective_timeout_seconds,
                stdout_path=events_path,
                stderr_path=stderr_path,
            )
    except KeyboardInterrupt as error:
        stdout = _append_lifecycle_terminal(
            events_path, "interrupted", "runner received an operator interrupt"
        )
        manifest = json.loads(manifest_path.read_text())
        if invocation.goal_activation:
            manifest["goal"]["activation_status"] = goal_activation_status(
                invocation.goal_activation, stdout
            )
            manifest["goal"]["lifecycle"] = parse_goal_lifecycle(stdout)
        manifest.update(
            {
                "status": "interrupted",
                "duration_seconds": round(time.monotonic() - started, 3),
                "backend": backend,
                "container_plane": plane,
                "environment_names": sorted(passed_environment),
            }
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        shutil.rmtree(credential_dir, ignore_errors=True)
        raise RunInterrupted(run_root) from error
    except ProcessTimedOut as error:
        harbor_watchdog = backend == "harbor"
        if harbor_watchdog:
            events_path.touch(exist_ok=True)
            stdout = events_path.read_text(encoding="utf-8")
        else:
            stdout = _append_lifecycle_terminal(
                events_path,
                "timed_out",
                f"candidate cell exceeded {error.timeout_seconds}s",
            )
        manifest = json.loads(manifest_path.read_text())
        if invocation.goal_activation:
            manifest["goal"]["activation_status"] = goal_activation_status(
                invocation.goal_activation, stdout
            )
            manifest["goal"]["lifecycle"] = parse_goal_lifecycle(stdout)
        manifest.update(
            {
                "status": (
                    "infrastructure-error" if harbor_watchdog else "candidate-failure"
                ),
                "failure_scope": (
                    "harbor-watchdog" if harbor_watchdog else "candidate-non-termination"
                ),
                "exit_code": None,
                "timed_out": True,
                "timeout_seconds": error.timeout_seconds,
                "duration_seconds": round(time.monotonic() - started, 3),
                "trace_format": invocation.trace_format,
                "model_resolved": parse_resolved_model(invocation.trace_format, stdout),
                "workspace_digest": candidate_workspace_sha256(workspace),
                "backend": backend,
                "container_plane": plane,
                "environment_names": sorted(passed_environment),
            }
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        shutil.rmtree(credential_dir, ignore_errors=True)
        return run_root
    except (OSError, RuntimeError, ValueError) as error:
        events_path.touch(exist_ok=True)
        stderr_path.touch(exist_ok=True)
        manifest = json.loads(manifest_path.read_text())
        manifest.update(
            {
                "status": "infrastructure-error",
                "failure_scope": failure_scope or f"{backend}-execution",
                "infrastructure_error": str(error),
                "exit_code": None,
                "duration_seconds": round(time.monotonic() - started, 3),
                "workspace_digest": candidate_workspace_sha256(workspace),
                "backend": backend,
                "container_plane": plane,
                "environment_names": sorted(passed_environment),
            }
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        shutil.rmtree(credential_dir, ignore_errors=True)
        return run_root
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    stderr = result.stderr if isinstance(result.stderr, str) else ""
    events_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    final_path = workspace / ".web3dgamebench-final.txt"
    if final_path.exists():
        shutil.copy2(final_path, run_root / "final.txt")
        final_path.unlink()
    manifest = json.loads(manifest_path.read_text())
    terminal_status = _terminal_lifecycle_status(stdout)
    if invocation.goal_activation:
        manifest["goal"]["activation_status"] = goal_activation_status(
            invocation.goal_activation, stdout
        )
        manifest["goal"]["lifecycle"] = parse_goal_lifecycle(stdout)
    workspace_brief = workspace / "TASK.md"
    workspace_brief_sha256 = _sha256(workspace_brief) if workspace_brief.is_file() else None
    manifest["prompt"].update(
        {
            "workspace_task_brief_sha256_after": workspace_brief_sha256,
            "task_brief_preserved": workspace_brief_sha256 == _sha256(task.brief),
        }
    )
    manifest.update(
        {
            # A non-zero harness exit is not evidence about the submitted game. It may
            # represent authentication, quota, provider, CLI, or container failure and
            # must stop the matrix for operator classification instead of scoring the cell.
            "status": (
                "candidate-failure"
                if terminal_status in {"blocked", "timed_out"}
                or failure_scope == "candidate-non-termination"
                else "candidate-complete"
                if result.returncode == 0
                else "infrastructure-error"
            ),
            "failure_scope": (
                "candidate-verification-overrun"
                if terminal_status == "timed_out"
                else "candidate-blocked"
                if terminal_status == "blocked"
                else "candidate-non-termination"
                if failure_scope == "candidate-non-termination"
                else None
                if result.returncode == 0
                else failure_scope or "candidate-runtime"
            ),
            "exit_code": result.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "trace_format": invocation.trace_format,
            "model_resolved": parse_resolved_model(invocation.trace_format, stdout),
            "workspace_digest": candidate_workspace_sha256(workspace),
            "backend": backend,
            "container_plane": plane,
            "environment_names": sorted(passed_environment),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.rmtree(credential_dir, ignore_errors=True)
    return run_root
