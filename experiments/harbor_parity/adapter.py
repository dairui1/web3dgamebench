from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path


TASK_ID = "bombsite-retake"
# Peeled commit behind the installed Harbor v0.22.0 tag.
HARBOR_COMMIT = "4407eb5227a2ff4f0d3f16b2eb48849382fdf276"
IMAGE = "web3dgamebench-candidate:0.1.0"
EXPECTED_IMAGE_ID = (
    "sha256:dfc81e81836c55dce69584371b7a9dd6d63246f8611a1c32b99edba9743d3879"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        if any(part in {"node_modules", "dist", ".git"} for part in item.parts):
            continue
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def candidate_prompt(goal: Path) -> str:
    return (
        "Implement the complete benchmark task in TASK.md. Work only inside this workspace. "
        "Do not use the network or external assets. You have the supplied dependency set. "
        "Build and inspect the game at both required viewports before finishing. Preserve any "
        "failures honestly; do not claim checks you did not run.\n\n"
        + goal.read_text(encoding="utf-8")
    )


def docker_image_id() -> str | None:
    result = subprocess.run(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def frozen_invocations(source_root: Path, prompt: str) -> dict[str, dict]:
    sys.path.insert(0, str(source_root / "src"))
    from web3dgamebench.config import load_profiles, load_task
    from web3dgamebench.runtimes import build_invocation

    profiles = load_profiles(source_root)
    task = load_task(source_root, TASK_ID)
    selected = (
        "codex-sol-medium",
        "claude-sonnet-default",
        "pi-deepseek-v4-flash",
    )
    result: dict[str, dict] = {}
    for profile_id in selected:
        invocation = build_invocation(
            profiles[profile_id],
            Path("/workspace"),
            prompt,
            isolation="container",
            goal_mode=task.goal_mode,
            goal_completion=task.goal_completion,
        )
        result[profile_id] = {
            "argv": list(invocation.argv),
            "stdin_prompt": invocation.stdin_prompt,
            "env": invocation.env,
            "trace_format": invocation.trace_format,
            "goal": asdict(invocation.goal_activation) if invocation.goal_activation else None,
        }
    return result


def write_task(source_root: Path, output_root: Path) -> Path:
    source_root = source_root.resolve()
    task_source = source_root / "tasks" / TASK_ID / "task"
    task_root = output_root.resolve() / TASK_ID
    if task_root.exists():
        raise FileExistsError(f"refusing to overwrite {task_root}")

    environment = task_root / "environment"
    tests = task_root / "tests"
    solution = task_root / "solution"
    environment.mkdir(parents=True)
    tests.mkdir()
    solution.mkdir()

    shutil.copytree(task_source / "starter", environment / "starter")
    shutil.copytree(source_root / "vendor" / "npm-cache", environment / "npm-cache")
    shutil.copy2(task_source / "goal.en.md", environment / "TASK.md")
    for relative in (
        "infra/candidate/chromium",
        "infra/candidate/codex_goal_runner.py",
        "infra/candidate/egress_proxy.py",
        "infra/candidate/pi_command_timeout.js",
        "infra/candidate/pi_goal_runner.ts",
    ):
        source = source_root / relative
        if not source.is_file():
            raise FileNotFoundError(f"required frozen runtime asset is missing: {source}")
        shutil.copy2(source, environment / source.name)

    prompt = candidate_prompt(task_source / "goal.en.md")
    (task_root / "instruction.md").write_text(prompt, encoding="utf-8")
    (environment / "AGENTS.md").write_text(
        "# Candidate rules\n\nImplement TASK.md in this directory. Do not access the network, "
        "parent directories, credentials, other submissions, or production services. Build and "
        "test the game.\n",
        encoding="utf-8",
    )
    (environment / "Dockerfile").write_text(
        f"""FROM {IMAGE}

USER root
COPY --chown=candidate:candidate starter/ /workspace/
COPY --chown=candidate:candidate TASK.md AGENTS.md /workspace/
COPY npm-cache/ /vendor/npm-cache/
COPY codex_goal_runner.py /usr/local/bin/web3dgamebench-codex-goal
COPY chromium /usr/local/bin/chromium
COPY pi_command_timeout.js /opt/web3dgamebench/pi_command_timeout.js
COPY pi_goal_runner.ts /opt/web3dgamebench/pi_goal_runner.ts
RUN chmod 0555 /usr/local/bin/web3dgamebench-codex-goal /usr/local/bin/chromium \
    && chown -R candidate:candidate /workspace

USER candidate
WORKDIR /workspace
ENV HOME=/home/candidate \\
    CI=1 \\
    HTTPS_PROXY=http://proxy:8888 \\
    HTTP_PROXY=http://proxy:8888 \\
    NO_PROXY=127.0.0.1,localhost \\
    npm_config_cache=/vendor/npm-cache \\
    npm_config_logs_dir=/tmp/npm-logs \\
    npm_config_offline=true \\
    npm_config_audit=false \\
    npm_config_fund=false \\
    npm_config_update_notifier=false
RUN npm ci --ignore-scripts --no-audit --no-fund
""",
        encoding="utf-8",
    )
    (environment / "docker-compose.yaml").write_text(
        f'''services:
  main:
    build:
      context: .
      dockerfile: Dockerfile
    depends_on:
      - proxy
    networks:
      - internal
    init: true
    pids_limit: 1024
    command: ["sh", "-lc", "sleep infinity"]
  proxy:
    image: {IMAGE}
    networks:
      - internal
      - egress
    volumes:
      - ./egress_proxy.py:/egress_proxy.py:ro
    command:
      - python3
      - /egress_proxy.py
      - --port
      - "8888"
      - --allow
      - chatgpt.com
      - --allow
      - openai.com
      - --allow
      - oaiusercontent.com
      - --allow
      - anthropic.com
      - --allow
      - opencode.ai
networks:
  internal:
    internal: true
  egress: {{}}
''',
        encoding="utf-8",
    )

    goal_sha = sha256_file(task_source / "goal.en.md")
    (task_root / "task.toml").write_text(
        f'''schema_version = "1.4"
artifacts = [{{ source = "/workspace", destination = "workspace" }}]

[task]
name = "web3dgamebench/bombsite-retake-parity"
version = "0.0.1"
description = "Non-publishable Harbor parity spike for Bombsite Retake"
keywords = ["browser-game", "three.js", "parity"]

[metadata]
source_task = "{TASK_ID}"
source_goal_sha256 = "{goal_sha}"
harbor_commit = "{HARBOR_COMMIT}"
candidate_image_id = "{EXPECTED_IMAGE_ID}"

[agent]
timeout_sec = 7200.0
user = "candidate"

[verifier]
timeout_sec = 60.0

[environment]
# Harbor's Docker allowlist is unavailable on macOS. The compose topology keeps
# `main` on an internal network and gives only the allowlisting proxy egress.
network_mode = "public"
build_timeout_sec = 600.0
os = "linux"
cpus = 6
memory_mb = 8192
storage_mb = 10240
''',
        encoding="utf-8",
    )
    (tests / "test.sh").write_text(
        f'''#!/bin/sh
set -eu
mkdir -p /logs/verifier
actual="$(sha256sum /workspace/TASK.md | awk '{{print $1}}')"
expected="{goal_sha}"
if [ "$actual" = "$expected" ]; then
  printf '{{"capture":1,"task_brief_preserved":1}}\n' > /logs/verifier/reward.json
else
  printf '{{"capture":0,"task_brief_preserved":0}}\n' > /logs/verifier/reward.json
  exit 1
fi
''',
        encoding="utf-8",
    )
    (tests / "test.sh").chmod(0o755)
    (solution / "solve.sh").write_text(
        "#!/bin/sh\n# No oracle is claimed for this generative browser-game task.\nexit 2\n",
        encoding="utf-8",
    )
    (solution / "solve.sh").chmod(0o755)

    lock = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "static-parity-spike-not-season-evidence",
        "source_root": str(source_root),
        "source_git_head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "source_git_dirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=source_root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        ),
        "harbor_version": subprocess.run(
            ["harbor", "--version"], capture_output=True, text=True, check=True
        ).stdout.strip(),
        "harbor_commit": HARBOR_COMMIT,
        "task_id": TASK_ID,
        "task_digest": tree_digest(task_source),
        "brief_sha256": goal_sha,
        "candidate_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "candidate_image": IMAGE,
        "candidate_image_id_expected": EXPECTED_IMAGE_ID,
        "candidate_image_id_observed": docker_image_id(),
        "profiles": {
            "codex-sol-medium": {"agent": "Web3DCodex", "model": "gpt-5.6-sol", "effort": "medium"},
            "claude-sonnet-default": {"agent": "Web3DClaude", "model": "claude-sonnet-5"},
            "pi-deepseek-v4-flash": {
                "agent": "Web3DPi",
                "provider": "opencode-go",
                "model": "deepseek-v4-flash",
            },
        },
        "original_invocations": frozen_invocations(source_root, prompt),
        "runtime_assets": {
            relative: sha256_file(source_root / relative)
            for relative in (
                "infra/candidate/chromium",
                "infra/candidate/codex_goal_runner.py",
                "infra/candidate/egress_proxy.py",
                "infra/candidate/pi_command_timeout.js",
                "infra/candidate/pi_goal_runner.ts",
                "src/web3dgamebench/runtimes.py",
                "src/web3dgamebench/runner.py",
                "infra/evaluator/evaluate.py",
        "infra/evaluator/contracts/bombsite-retake.json",
            )
        },
    }
    (task_root / "freeze-lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    return task_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--task-ids", nargs="*", default=[TASK_ID])
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.task_ids != [TASK_ID] or args.limit != 1:
        raise SystemExit("this spike intentionally supports only bombsite-retake")
    target = args.output_dir.resolve() / TASK_ID
    if args.overwrite and target.exists():
        shutil.rmtree(target)
    print(write_task(args.source_root, args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
