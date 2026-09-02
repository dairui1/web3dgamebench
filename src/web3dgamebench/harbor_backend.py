from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from .artifacts import file_tree_sha256
from .config import Profile
from .container import ContainerConfig, container_invocation_argv, load_container_config
from .process import run_captured
from .runtimes import Invocation

HARBOR_VERSION = "0.22.0"
HARBOR_COMMIT = "4407eb5227a2ff4f0d3f16b2eb48849382fdf276"
_AGENTS = {
    "codex": "web3dgamebench.harbor_agents:Web3DCodex",
    "claude-code": "web3dgamebench.harbor_agents:Web3DClaude",
    "pi": "web3dgamebench.harbor_agents:Web3DPi",
}


class HarborBackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class HarborResult:
    returncode: int
    stdout: str
    stderr: str
    plane: dict[str, object]
    environment_names: dict[str, str]
    failure_scope: str | None = None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def harbor_version() -> str:
    executable = shutil.which("harbor")
    if executable is None:
        raise HarborBackendError("Harbor is not installed")
    result = run_captured(
        [executable, "--version"],
        cwd=Path.cwd(),
        env=os.environ.copy(),
        input_text=None,
        timeout_seconds=30,
    )
    version = result.stdout.strip()
    if result.returncode or version != HARBOR_VERSION:
        raise HarborBackendError(
            f"Harbor {HARBOR_VERSION} is required; observed {version or 'unavailable'}"
        )
    return version


def _copy_runtime_assets(root: Path, environment: Path) -> None:
    for relative in (
        "infra/candidate/chromium",
        "infra/candidate/codex_goal_runner.py",
        "infra/candidate/egress_proxy.py",
        "infra/candidate/pi_command_timeout.js",
        "infra/candidate/pi_goal_runner.ts",
        "infra/candidate/pi_goal_bridge.json",
    ):
        source = root / relative
        if not source.is_file():
            raise HarborBackendError(f"required frozen runtime asset is missing: {source}")
        shutil.copy2(source, environment / source.name)


def _write_task(
    root: Path,
    task_root: Path,
    workspace: Path,
    task_id: str,
    profile: Profile,
    instruction: str,
    config: ContainerConfig,
    candidate_timeout_seconds: int,
) -> Path:
    environment = task_root / "environment"
    tests = task_root / "tests"
    solution = task_root / "solution"
    environment.mkdir(parents=True)
    tests.mkdir()
    solution.mkdir()
    shutil.copytree(workspace, environment / "starter", dirs_exist_ok=True)
    shutil.copytree(root / "vendor/npm-cache", environment / "npm-cache")
    _copy_runtime_assets(root, environment)
    (task_root / "instruction.md").write_text(instruction, encoding="utf-8")

    (environment / "Dockerfile").write_text(
        f"""FROM {config.image}

USER root
COPY npm-cache/ /vendor/npm-cache/
COPY codex_goal_runner.py /usr/local/bin/web3dgamebench-codex-goal
COPY chromium /usr/local/bin/chromium
COPY pi_command_timeout.js /usr/lib/node_modules/@earendil-works/pi-coding-agent/web3dgamebench-command-timeout.js
COPY pi_goal_runner.ts /usr/lib/node_modules/@earendil-works/pi-coding-agent/web3dgamebench-goal-runner.ts
COPY pi_goal_bridge.json /usr/lib/node_modules/@earendil-works/pi-coding-agent/web3dgamebench-goal-bridge.json
RUN chmod 0555 /usr/local/bin/web3dgamebench-codex-goal /usr/local/bin/chromium \\
    && mkdir -p /workspace \\
    && chown candidate:candidate /workspace

USER candidate
WORKDIR /workspace
ENV HOME=/home/candidate \\
    CI=1 \\
    HTTPS_PROXY=http://proxy:{config.proxy_port} \\
    HTTP_PROXY=http://proxy:{config.proxy_port} \\
    NO_PROXY=127.0.0.1,localhost \\
    npm_config_cache=/vendor/npm-cache \\
    npm_config_logs_dir=/tmp/npm-logs \\
    npm_config_offline=true \\
    npm_config_audit=false \\
    npm_config_fund=false \\
    npm_config_update_notifier=false
COPY --chown=candidate:candidate starter/package*.json /workspace/
RUN if [ -f package-lock.json ]; then npm ci --ignore-scripts --no-audit --no-fund; fi
COPY --chown=candidate:candidate starter/ /workspace/
""",
        encoding="utf-8",
    )
    allow = "\n".join(
        f"      - --allow\n      - {host}" for host in config.egress_allow
    )
    (environment / "docker-compose.yaml").write_text(
        f"""services:
  main:
    build:
      context: .
      dockerfile: Dockerfile
    depends_on:
      - proxy
    networks:
      - internal
    init: true
    pids_limit: {config.pids_limit}
    command: [\"sh\", \"-lc\", \"sleep infinity\"]
  proxy:
    image: {config.image}
    networks:
      - internal
      - egress
    volumes:
      - ./egress_proxy.py:/egress_proxy.py:ro
    command:
      - python3
      - /egress_proxy.py
      - --port
      - \"{config.proxy_port}\"
{allow}
networks:
  internal:
    internal: true
  egress: {{}}
""",
        encoding="utf-8",
    )
    brief_sha = _sha256(workspace / "TASK.md")
    memory_mb = (
        int(config.memory[:-1]) * 1024
        if config.memory and config.memory.endswith("g")
        else 8192
    )
    cpus = int(float(config.cpus)) if config.cpus else 6
    (task_root / "task.toml").write_text(
        f'''schema_version = "1.4"
artifacts = [
  {{ source = "/workspace", destination = "workspace" }},
  {{ source = "/logs/agent/events.jsonl", destination = "events.jsonl" }},
  {{ source = "/logs/agent/stderr.log", destination = "stderr.log" }},
]

[task]
name = "web3dgamebench/{task_id}-{profile.id}"
version = "1.0.0"
description = "Private Web3DGameBench candidate execution"
keywords = ["browser-game", "three.js", "private-eval"]

[metadata]
source_task = "{task_id}"
source_profile = "{profile.id}"
source_goal_sha256 = "{brief_sha}"
harbor_commit = "{HARBOR_COMMIT}"

[agent]
timeout_sec = {float(candidate_timeout_seconds)}
user = "candidate"

[verifier]
timeout_sec = 60.0

[environment]
network_mode = "public"
build_timeout_sec = 600.0
os = "linux"
cpus = {cpus}
memory_mb = {memory_mb}
storage_mb = 10240
''',
        encoding="utf-8",
    )
    (tests / "test.sh").write_text(
        f'''#!/bin/sh
set -eu
mkdir -p /logs/verifier
actual="$(sha256sum /workspace/TASK.md | awk '{{print $1}}')"
if [ "$actual" = "{brief_sha}" ]; then
  printf '{{"capture":1,"task_brief_preserved":1}}\\n' > /logs/verifier/reward.json
else
  printf '{{"capture":0,"task_brief_preserved":0}}\\n' > /logs/verifier/reward.json
  exit 1
fi
''',
        encoding="utf-8",
    )
    (tests / "test.sh").chmod(0o755)
    (solution / "solve.sh").write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    (solution / "solve.sh").chmod(0o755)
    return task_root


def _unique_trial(job_root: Path) -> Path:
    trials = [
        path
        for path in job_root.iterdir()
        if path.is_dir() and (path / "result.json").is_file()
    ]
    if len(trials) != 1:
        raise HarborBackendError(f"expected one Harbor trial below {job_root}, found {trials!r}")
    return trials[0]


def execute_harbor(
    root: Path,
    run_root: Path,
    workspace: Path,
    *,
    task_id: str,
    profile: Profile,
    instruction: str,
    invocation: Invocation,
    cancel_event: threading.Event | None = None,
    candidate_timeout_seconds: int | None = None,
) -> HarborResult:
    version = harbor_version()
    config = load_container_config(root)
    effective_timeout_seconds = (
        candidate_timeout_seconds
        if candidate_timeout_seconds is not None
        else config.candidate_total_timeout_seconds
    )
    harbor_root = run_root / "harbor"
    task_root = _write_task(
        root,
        harbor_root / "task" / task_id,
        workspace,
        task_id,
        profile,
        instruction,
        config,
        effective_timeout_seconds,
    )
    adapter_lock = {
        "schema_version": 1,
        "task": task_id,
        "profile": profile.id,
        "brief_sha256": _sha256(workspace / "TASK.md"),
        "instruction_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "generated_task_sha256": file_tree_sha256(task_root),
        "harbor_version": version,
        "harbor_commit": HARBOR_COMMIT,
        "pi_adapter": (
            {
                "version": config.pi_adapter.version,
                "upstream_pi_goal_version": config.pi_adapter.upstream_pi_goal_version,
                "runtime_evidence_schema_version": (
                    config.pi_adapter.runtime_evidence_schema_version
                ),
            }
            if profile.harness == "pi"
            else None
        ),
    }
    adapter_lock_path = run_root / "harbor-task-lock.json"
    adapter_lock_path.write_text(json.dumps(adapter_lock, indent=2) + "\n")
    jobs_dir = harbor_root / "jobs"
    job_name = run_root.name
    payload = {
        "schema_version": 1,
        "harness": profile.harness,
        "model": profile.model if profile.harness != "pi" else f"{profile.provider}/{profile.model}",
        "argv": container_invocation_argv(profile, invocation.argv),
        "stdin_prompt": invocation.stdin_prompt,
        "env": invocation.env,
        "instruction": instruction,
    }
    model = payload["model"]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["WEB3DGAMEBENCH_INVOCATION_JSON"] = json.dumps(payload, separators=(",", ":"))
    environment["WEB3DGAMEBENCH_COMMAND_TIMEOUT_SECONDS"] = str(
        config.command_timeout_seconds
    )
    environment["WEB3DGAMEBENCH_PI_ADAPTER_ENV_JSON"] = json.dumps(
        config.pi_adapter.environment(), separators=(",", ":")
    )
    environment.setdefault("CODEX_AUTH_JSON_PATH", str(Path.home() / ".codex/auth.json"))
    argv = [
        "harbor",
        "run",
        "-p",
        str(task_root),
        "-a",
        _AGENTS[profile.harness],
        "-m",
        str(model),
        "--job-name",
        job_name,
        "--jobs-dir",
        str(jobs_dir),
        "--n-concurrent",
        "1",
        "--max-retries",
        "0",
        "--yes",
    ]
    cli_stdout = harbor_root / "harbor.stdout.log"
    cli_stderr = harbor_root / "harbor.stderr.log"
    cli_result = run_captured(
        argv,
        cwd=root,
        env=environment,
        input_text=None,
        cancel_event=cancel_event,
        timeout_seconds=effective_timeout_seconds + 900,
        stdout_path=cli_stdout,
        stderr_path=cli_stderr,
    )
    job_root = jobs_dir / job_name
    if not job_root.is_dir():
        raise HarborBackendError(f"Harbor did not materialize job output: {job_root}")
    trial_root = _unique_trial(job_root)
    trial_result_path = trial_root / "result.json"
    trial_result = json.loads(trial_result_path.read_text(encoding="utf-8"))
    exception = trial_result.get("exception_info")
    exception_summary = None
    if isinstance(exception, dict):
        exception_summary = {
            "type": exception.get("exception_type") or exception.get("type"),
        }
    elif exception is not None:
        exception_summary = {"type": type(exception).__name__}
    rewards = (trial_result.get("verifier_result") or {}).get("rewards") or {}
    successful = (
        cli_result.returncode == 0
        and exception is None
        and rewards.get("capture") == 1
        and rewards.get("task_brief_preserved") == 1
    )
    provenance = {
        "schema_version": 1,
        "version": version,
        "commit": HARBOR_COMMIT,
        "job": str(job_root),
        "trial": str(trial_root),
        "task_checksum": trial_result.get("task_checksum"),
        "trial_result_sha256": _sha256(trial_result_path),
        "job_result_sha256": _sha256(job_root / "result.json"),
        "adapter_lock_sha256": _sha256(adapter_lock_path),
        "exception": exception_summary,
    }
    (run_root / "harbor.json").write_text(json.dumps(provenance, indent=2) + "\n")

    artifact_workspace = trial_root / "artifacts/workspace"
    if not artifact_workspace.is_dir():
        exception_type = (
            exception_summary.get("type") if exception_summary is not None else None
        )
        detail = f" ({exception_type})" if exception_type else ""
        raise HarborBackendError(f"Harbor trial did not preserve /workspace{detail}")
    shutil.rmtree(workspace)
    shutil.copytree(artifact_workspace, workspace)

    event_source = trial_root / "artifacts/events.jsonl"
    stderr_source = trial_root / "artifacts/stderr.log"
    stdout = event_source.read_text(errors="replace") if event_source.is_file() else ""
    stderr = stderr_source.read_text(errors="replace") if stderr_source.is_file() else ""
    plane = {
        "image": config.image,
        "image_digest": subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", config.image],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "execution_backend": "harbor-docker",
        "harbor_version": version,
        "harbor_commit": HARBOR_COMMIT,
    }
    return HarborResult(
        returncode=0 if successful else (cli_result.returncode or 1),
        stdout=stdout,
        stderr=stderr,
        plane=plane,
        environment_names={
            "WEB3DGAMEBENCH_INVOCATION_JSON": "<passed>",
            **({"OPENCODE_GO_APIKEY": "<passed>"} if profile.harness == "pi" else {}),
        },
        failure_scope=(
            None
            if successful
            else "candidate-non-termination"
            if exception_summary
            and "agent" in str(exception_summary.get("type", "")).casefold()
            and "timeout" in str(exception_summary.get("type", "")).casefold()
            else "harbor-trial"
        ),
    )
