from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from .config import Profile, Season, Task, load_task, validate_matrix
from .container import load_container_config
from .evaluator import evaluate_run, render_dist_sha256, render_source_sha256
from .runner import RunInterrupted, run_once, runs_dir


class MatrixError(RuntimeError):
    pass


class PlanDriftError(MatrixError):
    pass


class MatrixLockedError(MatrixError):
    pass


class MatrixInterrupted(KeyboardInterrupt):
    def __init__(self, receipt_path: Path):
        super().__init__(f"matrix interrupted; resume from {receipt_path}")
        self.receipt_path = receipt_path


_TASK_TREE_EXCLUDED = frozenset({"node_modules", "dist"})
_VENDOR_TREE_EXCLUDED = frozenset({"_logs", "_update-notifier-last-checked"})
_RESUMABLE_CELL_STATUSES = {"pending", "infrastructure-error", "interrupted"}
_TERMINAL_CELL_STATUSES = {"completed", "candidate-failure", "evidence-failure"}
_CELL_STATUSES = _RESUMABLE_CELL_STATUSES | _TERMINAL_CELL_STATUSES | {"running"}
_JUDGE_CELL_STATUSES = {
    "not-run",
    "running",
    "complete",
    "insufficient-evidence",
    "infrastructure-error",
}
_GOAL_RUNTIME_FIELDS = {"activation_status", "lifecycle", "receipt_sha256"}
_CLOSURE_REQUIRED_FILES = ("manifest.json", "events.jsonl", "stderr.log")
_TOOLCHAIN_PROBE = r"""
import json
import subprocess

commands = {
    "claude_help": ["claude", "--help"],
    "claude_version": ["claude", "--version"],
    "codex_exec_help": ["codex", "exec", "--help"],
    "codex_features": ["codex", "features", "list"],
    "codex_version": ["codex", "--version"],
    "node_version": ["node", "--version"],
    "npm_version": ["npm", "--version"],
    "pi_help": ["pi", "--help"],
    "pi_version": ["pi", "--version"],
}
outputs = {}
for name, argv in commands.items():
    result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=15)
    outputs[name] = {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
print(json.dumps(outputs, sort_keys=True))
"""
_REQUIRED_CLI_FLAGS = {
    "codex_exec_help": {
        "--config",
        "--enable",
        "--strict-config",
        "--ignore-user-config",
        "--ephemeral",
        "--json",
    },
    "claude_help": {
        "--append-system-prompt",
        "--setting-sources",
        "--no-session-persistence",
        "--output-format",
        "--strict-mcp-config",
    },
    "pi_help": {
        "--append-system-prompt",
        "--no-session",
        "--no-context-files",
        "--mode",
        "--no-approve",
    },
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _value_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run_command(argv: list[str], *, label: str, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MatrixError(f"failed to inspect {label}: {error}") from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise MatrixError(f"failed to inspect {label}: {detail}")
    return result.stdout.strip()


def _image_id(docker: str, reference: str) -> str:
    image_id = _run_command(
        [docker, "image", "inspect", "--format", "{{.Id}}", reference],
        label=f"container image {reference}",
    )
    if not image_id.startswith("sha256:"):
        raise MatrixError(f"container image has no immutable ID: {reference}")
    return image_id


def _runtime_environment(root: Path) -> dict[str, Any]:
    docker = shutil.which("docker")
    if docker is None:
        raise MatrixError("docker is required to freeze a matrix plan")
    config = load_container_config(root)
    candidate_id = _image_id(docker, config.image)
    evaluator_id = _image_id(docker, config.evaluator_image)
    raw_probe = _run_command(
        [
            docker,
            "run",
            "--rm",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            config.image,
            "python3",
            "-c",
            _TOOLCHAIN_PROBE,
        ],
        label=f"toolchain in {config.image}",
    )
    try:
        probe = json.loads(raw_probe)
    except json.JSONDecodeError as error:
        raise MatrixError("candidate image returned an invalid toolchain probe") from error
    if not isinstance(probe, dict):
        raise MatrixError("candidate image returned an invalid toolchain probe")
    for name in (
        "codex_version",
        "claude_version",
        "pi_version",
        "node_version",
        "npm_version",
        *_REQUIRED_CLI_FLAGS,
        "codex_features",
    ):
        result = probe.get(name)
        if (
            not isinstance(result, dict)
            or result.get("returncode") != 0
            or not isinstance(result.get("stdout"), str)
        ):
            raise MatrixError(f"candidate image failed runtime probe: {name}")
    for name, flags in _REQUIRED_CLI_FLAGS.items():
        output = probe[name]["stdout"]
        missing = sorted(flag for flag in flags if flag not in output)
        if missing:
            raise MatrixError(
                f"candidate image {name} lacks required flags: {', '.join(missing)}"
            )
    feature_lines = [
        line.split()
        for line in probe["codex_features"]["stdout"].splitlines()
        if line.split()
    ]
    goal_feature = next((fields for fields in feature_lines if fields[0] == "goals"), None)
    if goal_feature is None or goal_feature[1:3] != ["stable", "true"]:
        raise MatrixError("candidate image does not expose the stable Codex goals feature")

    versions = {
        name.removesuffix("_version"): probe[name]["stdout"]
        for name in (
            "codex_version",
            "claude_version",
            "pi_version",
            "node_version",
            "npm_version",
        )
    }
    capabilities = {
        name: {
            "output_sha256": _text_sha256(probe[name]["stdout"]),
            "required_flags": sorted(flags),
        }
        for name, flags in _REQUIRED_CLI_FLAGS.items()
    }
    capabilities["codex_features"] = {
        "output_sha256": _text_sha256(probe["codex_features"]["stdout"]),
        "goals": " ".join(goal_feature[:3]),
    }
    fingerprint: dict[str, Any] = {
        "container_images": {
            "candidate": {"reference": config.image, "id": candidate_id},
            "evaluator": {"reference": config.evaluator_image, "id": evaluator_id},
        },
        "candidate_toolchain": {
            "versions": versions,
            "capabilities": capabilities,
        },
    }
    fingerprint["fingerprint_sha256"] = _value_sha256(fingerprint)
    return fingerprint


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def close_run_artifacts(run_root: Path) -> dict[str, Any]:
    """Bind every artifact used for trust, replay, source, and playable publication."""

    files: dict[str, str] = {}
    for relative in _CLOSURE_REQUIRED_FILES:
        path = run_root / relative
        if not path.is_file():
            raise MatrixError(f"run closure artifact is missing: {path}")
        files[relative] = _file_sha256(path)
    for relative in ("final.txt", "evaluation/report.json"):
        path = run_root / relative
        if path.is_file():
            files[relative] = _file_sha256(path)

    closure: dict[str, Any] = {"schema_version": 1, "files": files}
    render = run_root / "render"
    if render.is_dir():
        closure["render_source_sha256"] = render_source_sha256(render)
        dist = render / "dist"
        if dist.is_dir():
            closure["render_dist_sha256"] = render_dist_sha256(dist)
    return closure


def verify_run_artifacts(run_root: Path, expected: object) -> None:
    if not isinstance(expected, dict) or expected.get("schema_version") != 1:
        raise MatrixError(f"matrix cell has no valid run closure: {run_root}")
    actual = close_run_artifacts(run_root)
    if actual != expected:
        raise MatrixError(f"closed run artifacts changed: {run_root}")


def _tree_sha256(root: Path, *, excluded: frozenset[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and not excluded.intersection(item.relative_to(root).parts)
    ):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(bytes.fromhex(_file_sha256(path)))
    return digest.hexdigest()


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise MatrixError(f"frozen input is outside the repository: {path}") from error


def _task_snapshot(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "season": task.season,
        "status": task.status,
        "framework": task.framework,
        "seed": task.seed,
        "goal_mode": task.goal_mode,
        "goal_completion": task.goal_completion,
        "viewports": {
            label: {"width": viewport.width, "height": viewport.height}
            for label, viewport in sorted(task.viewports.items())
        },
        "checks": task.checks.as_dict(),
    }


def _season_snapshot(season: Season) -> dict[str, Any]:
    return {
        "id": season.id,
        "status": season.status,
        "tasks": list(season.tasks),
        "profiles": list(season.profiles),
        "attempts": season.attempts,
        "publish_prompts_after_close": season.publish_prompts_after_close,
    }


def _profile_snapshots(
    season: Season, profiles: dict[str, Profile]
) -> dict[str, dict[str, Any]]:
    return {profile_id: asdict(profiles[profile_id]) for profile_id in season.profiles}


def _add_file(
    root: Path,
    files: dict[str, dict[str, Any]],
    path: Path,
    role: str,
) -> str:
    if not path.is_file():
        raise MatrixError(f"required frozen input is missing: {path}")
    relative = _relative(root, path)
    digest = _file_sha256(path)
    existing = files.setdefault(relative, {"sha256": digest, "roles": []})
    if existing["sha256"] != digest:
        raise MatrixError(f"input changed while planning: {relative}")
    if role not in existing["roles"]:
        existing["roles"].append(role)
        existing["roles"].sort()
    return digest


def _global_inputs(root: Path) -> list[tuple[Path, str]]:
    return [
        (root / "pyproject.toml", "package-config"),
        (root / "configs/seasons.toml", "season-config"),
        (root / "configs/profiles.toml", "profile-config"),
        (root / "configs/judges.toml", "judge-config"),
        (root / "configs/container.toml", "container-config"),
        (root / "vendor/manifest.json", "vendor-manifest"),
        (root / "infra/candidate/Dockerfile", "candidate-image"),
        (root / "infra/candidate/egress_proxy.py", "candidate-egress"),
        (root / "infra/candidate/pi_command_timeout.js", "candidate-command-limit"),
        (root / "infra/evaluator/Dockerfile", "evaluator-image"),
        (root / "infra/evaluator/evaluate.py", "evaluator"),
        (root / "infra/judge/pi/playtest-judge.ts", "judge-runtime"),
        (root / "src/web3dgamebench/cli.py", "matrix-runtime"),
        (root / "src/web3dgamebench/artifacts.py", "playable-normalization"),
        (root / "src/web3dgamebench/config.py", "matrix-runtime"),
        (root / "src/web3dgamebench/container.py", "matrix-runtime"),
        (root / "src/web3dgamebench/evaluator.py", "evaluator-host"),
        (root / "src/web3dgamebench/judge.py", "judge-host"),
        (root / "src/web3dgamebench/matrix.py", "matrix-runtime"),
        (root / "src/web3dgamebench/runner.py", "candidate-runtime"),
        (root / "src/web3dgamebench/runtimes.py", "candidate-runtime"),
        (root / "src/web3dgamebench/runtime_contracts.py", "runtime-contract-loader"),
        (root / "src/web3dgamebench/runtime_schema.py", "runtime-schema"),
    ]


def _load_vendor_locks(root: Path) -> dict[str, str]:
    path = root / "vendor/manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise MatrixError(f"invalid vendor manifest: {path}") from error
    starters = manifest.get("starters")
    if manifest.get("schema_version") != 1 or not isinstance(starters, list):
        raise MatrixError(f"invalid vendor manifest shape: {path}")
    locks: dict[str, str] = {}
    for item in starters:
        if not isinstance(item, dict):
            raise MatrixError(f"invalid vendor starter entry: {path}")
        starter = item.get("starter")
        expected_digest = item.get("package_lock_sha256")
        if not isinstance(starter, str) or not isinstance(expected_digest, str):
            raise MatrixError(f"invalid vendor starter entry: {path}")
        relative = Path(starter)
        if relative.is_absolute() or ".." in relative.parts:
            raise MatrixError(f"vendor starter path escapes repository: {starter}")
        starter_path = root / relative
        normalized = _relative(root, starter_path)
        if normalized != starter or starter in locks:
            raise MatrixError(f"duplicate or non-canonical vendor starter: {starter}")
        if not starter_path.is_dir():
            raise MatrixError(f"stale vendor starter entry: {starter}")
        lock_path = starter_path / "package-lock.json"
        if not lock_path.is_file() or _file_sha256(lock_path) != expected_digest:
            raise MatrixError(f"stale vendor lock entry: {starter}")
        locks[starter] = expected_digest
    if not locks:
        raise MatrixError(f"vendor manifest has no package locks: {path}")
    return locks


def create_preflight_plan(root: Path, season_id: str) -> dict[str, Any]:
    season, profiles = validate_matrix(root, season_id)
    runtime_environment = _runtime_environment(root)
    files: dict[str, dict[str, Any]] = {}
    for path, role in _global_inputs(root):
        _add_file(root, files, path, role)
    catalog_template = root / "configs" / "catalogs" / f"{season.id}.json"
    if season.id == "season-1":
        _add_file(root, files, catalog_template, "publication-catalog")

    vendor_locks = _load_vendor_locks(root)
    tasks: dict[str, dict[str, Any]] = {}
    trees: dict[str, dict[str, Any]] = {}
    for task_id in season.tasks:
        task = load_task(root, task_id)
        task_path = _relative(root, task.root)
        starter_path = _relative(root, task.starter)
        task_tree_sha256 = _tree_sha256(task.root, excluded=_TASK_TREE_EXCLUDED)
        starter_tree_sha256 = _tree_sha256(task.starter, excluded=_TASK_TREE_EXCLUDED)
        trees[task_path] = {
            "sha256": task_tree_sha256,
            "excluded_names": sorted(_TASK_TREE_EXCLUDED),
            "role": "candidate-task",
        }
        trees[starter_path] = {
            "sha256": starter_tree_sha256,
            "excluded_names": sorted(_TASK_TREE_EXCLUDED),
            "role": "candidate-starter",
        }

        task_config = task.root / "task.toml"
        lock = task.starter / "package-lock.json"
        runtime_contract = root / "infra/evaluator/contracts" / f"{task.id}.json"
        judge_prompt = root / "infra/judge/prompts" / f"{task.id}.md"
        judge_rubric = root / "infra/judge/rubrics" / f"{task.id}.json"
        task_config_sha256 = _add_file(root, files, task_config, "task-config")
        brief_sha256 = _add_file(root, files, task.brief, "candidate-brief")
        starter_lock_sha256 = _add_file(root, files, lock, "starter-lock")
        runtime_contract_sha256 = _add_file(
            root, files, runtime_contract, "runtime-contract"
        )
        judge_prompt_sha256 = _add_file(root, files, judge_prompt, "judge-prompt")
        judge_rubric_sha256 = _add_file(root, files, judge_rubric, "judge-rubric")
        if vendor_locks.get(starter_path) != starter_lock_sha256:
            raise MatrixError(
                f"vendor manifest does not exactly cover starter for task {task.id}"
            )
        tasks[task.id] = {
            **_task_snapshot(task),
            "task_path": task_path,
            "starter_path": starter_path,
            "task_tree_sha256": task_tree_sha256,
            "starter_tree_sha256": starter_tree_sha256,
            "task_config_sha256": task_config_sha256,
            "brief_path": _relative(root, task.brief),
            "brief_sha256": brief_sha256,
            "starter_lock_path": _relative(root, lock),
            "starter_lock_sha256": starter_lock_sha256,
            "runtime_contract_path": _relative(root, runtime_contract),
            "runtime_contract_sha256": runtime_contract_sha256,
            "judge_prompt_path": _relative(root, judge_prompt),
            "judge_prompt_sha256": judge_prompt_sha256,
            "judge_rubric_path": _relative(root, judge_rubric),
            "judge_rubric_sha256": judge_rubric_sha256,
        }

    vendor_cache = root / "vendor/npm-cache"
    if not vendor_cache.is_dir():
        raise MatrixError(f"vendor cache is missing: {vendor_cache}")
    vendor_path = _relative(root, vendor_cache)
    trees[vendor_path] = {
        "sha256": _tree_sha256(vendor_cache, excluded=_VENDOR_TREE_EXCLUDED),
        "excluded_names": sorted(_VENDOR_TREE_EXCLUDED),
        "role": "offline-vendor-cache",
    }

    cells = []
    for task_id in season.tasks:
        for profile_id in season.profiles:
            profile = profiles[profile_id]
            for attempt in range(1, season.attempts + 1):
                cells.append(
                    {
                        "cell_id": f"{task_id}::{profile_id}::a{attempt}",
                        "task": task_id,
                        "profile": profile_id,
                        "harness": profile.harness,
                        "model": profile.model,
                        "effort": profile.effort or "official-default",
                        "attempt": attempt,
                    }
                )

    plan: dict[str, Any] = {
        "schema_version": 2,
        "plan_id": (
            f"{season.id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
            f"{uuid.uuid4().hex[:8]}"
        ),
        "created_at": _now(),
        "season": _season_snapshot(season),
        "profiles": _profile_snapshots(season, profiles),
        "tasks": tasks,
        "runtime_control": {
            "candidate_total_timeout_seconds": None,
            "interruptible": True,
            "resume_supported": True,
        },
        "runtime_environment": runtime_environment,
        "frozen_inputs": {
            "files": dict(sorted(files.items())),
            "trees": dict(sorted(trees.items())),
        },
        "cells": cells,
    }
    plan["plan_digest_sha256"] = _value_sha256(plan)
    return plan


def _atomic_json_replace(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            json.dump(value, destination, indent=2, ensure_ascii=True, allow_nan=False)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_immutable_json_once(path: Path, value: object, *, label: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            json.dump(value, destination, indent=2, ensure_ascii=True, allow_nan=False)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
        temporary_path.chmod(0o444)
        try:
            os.link(temporary_path, path)
        except FileExistsError as error:
            raise MatrixError(f"{label} already exists: {path}") from error
    finally:
        temporary_path.unlink(missing_ok=True)
    return path


def write_preflight_plan(path: Path, plan: dict[str, Any]) -> Path:
    verify_plan_digest(plan)
    path = path.expanduser().resolve()
    return _write_immutable_json_once(path, plan, label="immutable plan")


def verify_plan_digest(plan: dict[str, Any]) -> None:
    expected = plan.get("plan_digest_sha256")
    if not isinstance(expected, str):
        raise PlanDriftError("plan has no digest")
    unsigned = dict(plan)
    unsigned.pop("plan_digest_sha256", None)
    actual = _value_sha256(unsigned)
    if actual != expected:
        raise PlanDriftError(f"plan digest mismatch: expected {expected}, found {actual}")


def load_preflight_plan(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise MatrixError(f"invalid preflight plan: {path}") from error
    if not isinstance(plan, dict) or plan.get("schema_version") != 2:
        raise MatrixError(f"unsupported preflight plan: {path}")
    verify_plan_digest(plan)
    return plan


def _frozen_path(root: Path, relative: str) -> Path:
    candidate = root / relative
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise PlanDriftError(f"frozen path escapes repository: {relative}") from error
    return candidate


def verify_frozen_inputs(root: Path, plan: dict[str, Any]) -> None:
    verify_plan_digest(plan)
    try:
        runtime_environment = _runtime_environment(root)
    except MatrixError as error:
        raise PlanDriftError(str(error)) from error
    if runtime_environment != plan.get("runtime_environment"):
        raise PlanDriftError("container image or candidate toolchain changed")
    inputs = plan.get("frozen_inputs")
    if not isinstance(inputs, dict):
        raise PlanDriftError("plan has no frozen inputs")
    files = inputs.get("files")
    trees = inputs.get("trees")
    if not isinstance(files, dict) or not isinstance(trees, dict):
        raise PlanDriftError("plan frozen inputs are malformed")

    for relative, entry in files.items():
        if not isinstance(relative, str) or not isinstance(entry, dict):
            raise PlanDriftError("plan frozen file entry is malformed")
        path = _frozen_path(root, relative)
        if not path.is_file():
            raise PlanDriftError(f"frozen input is missing: {relative}")
        actual = _file_sha256(path)
        if actual != entry.get("sha256"):
            raise PlanDriftError(f"frozen input changed: {relative}")
    for relative, entry in trees.items():
        if not isinstance(relative, str) or not isinstance(entry, dict):
            raise PlanDriftError("plan frozen tree entry is malformed")
        path = _frozen_path(root, relative)
        if not path.is_dir():
            raise PlanDriftError(f"frozen tree is missing: {relative}")
        excluded_names = entry.get("excluded_names")
        if not isinstance(excluded_names, list) or any(
            not isinstance(name, str) for name in excluded_names
        ):
            raise PlanDriftError(f"frozen tree exclusions are malformed: {relative}")
        actual = _tree_sha256(path, excluded=frozenset(excluded_names))
        if actual != entry.get("sha256"):
            raise PlanDriftError(f"frozen tree changed: {relative}")

    season_id = plan.get("season", {}).get("id")
    if not isinstance(season_id, str):
        raise PlanDriftError("plan has no season id")
    season, profiles = validate_matrix(root, season_id)
    if _season_snapshot(season) != plan.get("season"):
        raise PlanDriftError("season configuration changed")
    if _profile_snapshots(season, profiles) != plan.get("profiles"):
        raise PlanDriftError("profile configuration changed")
    expected_cells = [
        {
            "cell_id": f"{task_id}::{profile_id}::a{attempt}",
            "task": task_id,
            "profile": profile_id,
            "harness": profiles[profile_id].harness,
            "model": profiles[profile_id].model,
            "effort": profiles[profile_id].effort or "official-default",
            "attempt": attempt,
        }
        for task_id in season.tasks
        for profile_id in season.profiles
        for attempt in range(1, season.attempts + 1)
    ]
    if plan.get("cells") != expected_cells:
        raise PlanDriftError("planned matrix cells do not match the season configuration")
    current_tasks = {
        task_id: _task_snapshot(load_task(root, task_id)) for task_id in season.tasks
    }
    planned_tasks = plan.get("tasks")
    if not isinstance(planned_tasks, dict):
        raise PlanDriftError("plan task snapshots are malformed")
    if set(planned_tasks) != set(current_tasks):
        raise PlanDriftError("planned task set does not match the season configuration")
    for task_id, snapshot in current_tasks.items():
        planned = planned_tasks.get(task_id)
        if not isinstance(planned, dict):
            raise PlanDriftError(f"plan task snapshot is missing: {task_id}")
        if any(planned.get(key) != value for key, value in snapshot.items()):
            raise PlanDriftError(f"task configuration changed: {task_id}")

    required_files = {
        _relative(root, path) for path, _role in _global_inputs(root)
    }
    if season.id == "season-1":
        required_files.add(f"configs/catalogs/{season.id}.json")
    for task_id in season.tasks:
        task = load_task(root, task_id)
        required_files.update(
            {
                _relative(root, task.root / "task.toml"),
                _relative(root, task.brief),
                _relative(root, task.starter / "package-lock.json"),
                f"infra/evaluator/contracts/{task_id}.json",
                f"infra/judge/prompts/{task_id}.md",
                f"infra/judge/rubrics/{task_id}.json",
            }
        )
    if not required_files.issubset(files):
        missing = ", ".join(sorted(required_files - set(files)))
        raise PlanDriftError(f"plan omits required frozen files: {missing}")
    required_trees = {"vendor/npm-cache"}
    required_trees.update(task["task_path"] for task in planned_tasks.values())
    required_trees.update(task["starter_path"] for task in planned_tasks.values())
    if not required_trees.issubset(trees):
        missing = ", ".join(sorted(required_trees - set(trees)))
        raise PlanDriftError(f"plan omits required frozen trees: {missing}")


class SeasonLock:
    def __init__(self, season_id: str, directory: Path | None = None):
        safe = season_id.replace("/", "_").replace(os.sep, "_")
        self.path = (directory or (runs_dir() / ".locks")) / f"{safe}.lock"
        self._descriptor: int | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(descriptor)
            raise MatrixLockedError(
                f"season matrix is already running: {self.path.stem}"
            ) from error
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()} acquired_at={_now()}\n".encode())
        self._descriptor = descriptor
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._descriptor is not None:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            os.close(self._descriptor)
            self._descriptor = None


def _receipt_digest(receipt: dict[str, Any]) -> str:
    unsigned = dict(receipt)
    unsigned.pop("receipt_digest_sha256", None)
    return _value_sha256(unsigned)


def _canonical_matrix_path(season_id: str) -> Path:
    safe = season_id.replace("/", "_").replace(os.sep, "_")
    return runs_dir() / "matrices" / f"canonical-{safe}.json"


def _canonical_closure_path(season_id: str) -> Path:
    safe = season_id.replace("/", "_").replace(os.sep, "_")
    return runs_dir() / "matrices" / f"closed-{safe}.json"


def _claim_canonical_matrix(
    season_id: str, receipt_path: Path, receipt: dict[str, Any]
) -> Path | None:
    if season_id != "season-1":
        return None
    path = _canonical_matrix_path(season_id)
    value = {
        "schema_version": 1,
        "season": season_id,
        "matrix_id": receipt["matrix_id"],
        "receipt": str(receipt_path.resolve()),
        "plan_digest_sha256": receipt["plan_digest_sha256"],
        "claimed_at": _now(),
    }
    try:
        _write_immutable_json_once(path, value, label="canonical season-1 matrix")
    except MatrixError as error:
        raise MatrixError(
            f"season-1 already has a canonical matrix; resume the receipt named in {path}"
        ) from error
    return path


def _assert_canonical_matrix(
    season_id: str, receipt_path: Path, receipt: dict[str, Any]
) -> None:
    if season_id != "season-1":
        return
    path = _canonical_matrix_path(season_id)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise MatrixError(f"season-1 canonical matrix record is missing or invalid: {path}") from error
    expected = {
        "season": season_id,
        "matrix_id": receipt.get("matrix_id"),
        "receipt": str(receipt_path.resolve()),
        "plan_digest_sha256": receipt.get("plan_digest_sha256"),
    }
    if not isinstance(record, dict) or any(
        record.get(key) != value for key, value in expected.items()
    ):
        raise MatrixError(f"receipt is not the canonical season-1 matrix: {receipt_path}")


def _verify_canonical_publication_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("season") != "season-1":
        return
    raw_path = receipt.get("receipt_path")
    if not isinstance(raw_path, str) or not raw_path:
        raise MatrixError("season-1 matrix receipt has no canonical path")
    receipt_path = Path(raw_path).expanduser().resolve()
    if raw_path != str(receipt_path):
        raise MatrixError("season-1 matrix receipt path is not canonical")
    _assert_canonical_matrix("season-1", receipt_path, receipt)
    stored = _load_receipt(receipt_path)
    if stored.get("receipt_digest_sha256") != receipt.get("receipt_digest_sha256"):
        raise MatrixError("publication receipt does not match the canonical season-1 receipt")
    closure_path = _canonical_closure_path("season-1")
    try:
        closure = json.loads(closure_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise MatrixError(
            f"season-1 canonical matrix has no valid closure marker: {closure_path}"
        ) from error
    expected = {
        "schema_version": 1,
        "season": "season-1",
        "matrix_id": receipt.get("matrix_id"),
        "receipt": str(receipt_path),
        "plan_digest_sha256": receipt.get("plan_digest_sha256"),
        "receipt_digest_sha256": receipt.get("receipt_digest_sha256"),
        "receipt_file_sha256": _file_sha256(receipt_path),
    }
    if not isinstance(closure, dict) or any(
        closure.get(key) != value for key, value in expected.items()
    ):
        raise MatrixError("season-1 canonical matrix closure does not match the receipt")


def _seal_canonical_matrix(
    season_id: str, receipt_path: Path, receipt: dict[str, Any]
) -> Path | None:
    if season_id != "season-1":
        return None
    validate_closed_receipt(receipt)
    receipt_path = receipt_path.expanduser().resolve()
    _assert_canonical_matrix(season_id, receipt_path, receipt)
    for cell in receipt["cells"]:
        verify_run_artifacts(
            Path(cell["run"]).expanduser().resolve(), cell.get("artifacts")
        )
    value = {
        "schema_version": 1,
        "season": season_id,
        "matrix_id": receipt["matrix_id"],
        "receipt": str(receipt_path),
        "plan_digest_sha256": receipt["plan_digest_sha256"],
        "receipt_digest_sha256": receipt["receipt_digest_sha256"],
        "receipt_file_sha256": _file_sha256(receipt_path),
        "closed_at": receipt.get("completed_at"),
    }
    path = _canonical_closure_path(season_id)
    return _write_immutable_json_once(path, value, label="season-1 matrix closure")


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    receipt["updated_at"] = _now()
    receipt.pop("receipt_digest_sha256", None)
    receipt["receipt_digest_sha256"] = _receipt_digest(receipt)
    _atomic_json_replace(path, receipt)


def _load_receipt(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise MatrixError(f"invalid matrix receipt: {path}") from error
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 2:
        raise MatrixError(f"unsupported matrix receipt: {path}")
    expected = receipt.get("receipt_digest_sha256")
    if not isinstance(expected, str) or _receipt_digest(receipt) != expected:
        raise MatrixError(f"matrix receipt digest mismatch: {path}")
    cells = receipt.get("cells")
    if not isinstance(cells, list) or not cells:
        raise MatrixError(f"matrix receipt has no cells: {path}")
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("status") not in _CELL_STATUSES:
            raise MatrixError(f"matrix receipt has a malformed cell: {path}")
        if not isinstance(cell.get("passed"), bool) or not isinstance(
            cell.get("trusted"), bool
        ):
            raise MatrixError(f"matrix receipt has incomplete cell evidence: {path}")
    return receipt


def load_matrix_receipt(path: Path) -> dict[str, Any]:
    """Load a matrix receipt and verify its content digest."""

    return _load_receipt(path)


def validate_closed_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Validate the stable publication-facing shape of a closed receipt."""

    if receipt.get("schema_version") != 2:
        raise MatrixError("unsupported matrix receipt")
    expected_digest = receipt.get("receipt_digest_sha256")
    if not isinstance(expected_digest, str) or _receipt_digest(receipt) != expected_digest:
        raise MatrixError("matrix receipt digest mismatch")
    if receipt.get("status") != "complete":
        raise MatrixError("matrix receipt is not closed")
    if not isinstance(receipt.get("season"), str):
        raise MatrixError("matrix receipt has no season")
    plan = receipt.get("plan")
    plan_digest = receipt.get("plan_digest_sha256")
    if (
        not isinstance(plan, dict)
        or not isinstance(plan_digest, str)
        or plan.get("digest_sha256") != plan_digest
    ):
        raise MatrixError("matrix receipt has no stable plan digest")
    cells = receipt.get("cells")
    if not isinstance(cells, list) or not cells:
        raise MatrixError("matrix receipt has no cells")
    if receipt["season"] == "season-1" and len(cells) != 80:
        raise MatrixError("season-1 matrix receipt must contain exactly 80 cells")
    seen: set[str] = set()
    for cell in cells:
        if not isinstance(cell, dict):
            raise MatrixError("matrix receipt cell is malformed")
        cell_id = cell.get("cell_id")
        if not isinstance(cell_id, str) or cell_id in seen:
            raise MatrixError("matrix receipt cell id is missing or duplicated")
        seen.add(cell_id)
        if cell.get("status") not in _TERMINAL_CELL_STATUSES:
            raise MatrixError(f"matrix receipt cell is not terminal: {cell_id}")
        if not isinstance(cell.get("run"), str) or not cell["run"]:
            raise MatrixError(f"matrix receipt cell has no run: {cell_id}")
        if not isinstance(cell.get("passed"), bool):
            raise MatrixError(f"matrix receipt cell has no passed result: {cell_id}")
        if not isinstance(cell.get("trusted"), bool):
            raise MatrixError(f"matrix receipt cell has no trusted result: {cell_id}")
        if cell["passed"] is not cell["trusted"]:
            raise MatrixError(f"matrix receipt cell pass and trust disagree: {cell_id}")
        if (cell["status"] == "completed") is not cell["trusted"]:
            raise MatrixError(f"matrix receipt cell terminal result is inconsistent: {cell_id}")
        judge = cell.get("judge")
        if (
            not isinstance(judge, dict)
            or judge.get("status") not in _JUDGE_CELL_STATUSES
        ):
            raise MatrixError(f"matrix receipt cell has invalid judge state: {cell_id}")
        artifacts = cell.get("artifacts")
        if not isinstance(artifacts, dict) or artifacts.get("schema_version") != 1:
            raise MatrixError(f"matrix receipt cell has no run closure: {cell_id}")
        files = artifacts.get("files")
        if not isinstance(files, dict) or any(
            not isinstance(files.get(name), str) for name in _CLOSURE_REQUIRED_FILES
        ):
            raise MatrixError(f"matrix receipt cell run closure is incomplete: {cell_id}")
        if cell["trusted"] and (
            not isinstance(files.get("evaluation/report.json"), str)
            or not isinstance(artifacts.get("render_source_sha256"), str)
            or not isinstance(artifacts.get("render_dist_sha256"), str)
        ):
            raise MatrixError(f"trusted matrix cell closure is incomplete: {cell_id}")
    return receipt


def validate_publication_receipt(
    root: Path, receipt: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify that a closed receipt still points at its frozen runnable inputs."""

    validated = validate_closed_receipt(receipt)
    if validated["season"] == "season-1" and validated.get("backend") != "container":
        raise MatrixError("season-1 publication requires a container matrix")
    _verify_canonical_publication_receipt(validated)
    plan_reference = validated.get("plan")
    if not isinstance(plan_reference, dict) or not isinstance(
        plan_reference.get("path"), str
    ):
        raise MatrixError("matrix receipt has no plan reference")
    plan_path = Path(plan_reference["path"]).expanduser().resolve()
    plan = _verify_plan_file(plan_path, validated)
    verify_frozen_inputs(root, plan)
    for cell in validated["cells"]:
        run_root = Path(cell["run"]).expanduser().resolve()
        verify_run_artifacts(run_root, cell.get("artifacts"))
        if cell["trusted"] is not True:
            continue
        manifest = _candidate_manifest(run_root)
        report = _evaluation_report(run_root / "evaluation/report.json")
        trusted, failures = trusted_cell_gate(plan, cell, manifest, report, run_root)
        if not trusted:
            raise MatrixError(
                f"closed matrix cell no longer passes its trust gate: "
                f"{cell['cell_id']} ({'; '.join(failures)})"
            )
    return validated, plan


def _new_receipt(plan_path: Path, plan: dict[str, Any], backend: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "matrix_id": f"{plan['plan_id']}-{uuid.uuid4().hex[:8]}",
        "season": plan["season"]["id"],
        "backend": backend,
        "status": "running",
        "created_at": _now(),
        "plan_digest_sha256": plan["plan_digest_sha256"],
        "plan": {
            "path": str(plan_path),
            "digest_sha256": plan["plan_digest_sha256"],
            "file_sha256": _file_sha256(plan_path),
        },
        "cells": [
            {
                "cell_id": cell["cell_id"],
                "task": cell["task"],
                "profile": cell["profile"],
                "attempt": cell["attempt"],
                "status": "pending",
                "run": None,
                "passed": False,
                "trusted": False,
                "judge": {"status": "not-run"},
            }
            for cell in plan["cells"]
        ],
    }


def _verify_plan_file(plan_path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    plan = load_preflight_plan(plan_path)
    reference = receipt.get("plan")
    if not isinstance(reference, dict):
        raise MatrixError("matrix receipt has no plan reference")
    if plan.get("plan_digest_sha256") != reference.get("digest_sha256"):
        raise PlanDriftError("matrix plan semantic digest changed")
    if receipt.get("plan_digest_sha256") != reference.get("digest_sha256"):
        raise PlanDriftError("matrix receipt plan digest is inconsistent")
    if _file_sha256(plan_path) != reference.get("file_sha256"):
        raise PlanDriftError("matrix plan file changed")
    cells = receipt.get("cells")
    expected = [
        (cell["cell_id"], cell["task"], cell["profile"], cell["attempt"])
        for cell in plan["cells"]
    ]
    actual = [
        (cell.get("cell_id"), cell.get("task"), cell.get("profile"), cell.get("attempt"))
        for cell in cells
    ] if isinstance(cells, list) else []
    if actual != expected:
        raise PlanDriftError("matrix receipt cells do not match the frozen plan")
    return plan


def _models_compatible(expected: str, resolved: str) -> bool:
    def normalize(value: str) -> str:
        return value.strip().lower().split("/")[-1].split(":")[0].replace("_", "-")

    wanted = normalize(expected)
    actual = normalize(resolved)
    return wanted == actual or actual.startswith(f"{wanted}-")


def _goal_receipt_valid(goal: dict[str, Any]) -> bool:
    expected = goal.get("receipt_sha256")
    if not isinstance(expected, str):
        return False
    payload = {key: value for key, value in goal.items() if key not in _GOAL_RUNTIME_FIELDS}
    try:
        return _value_sha256(payload) == expected
    except (TypeError, ValueError):
        return False


def trusted_cell_gate(
    plan: dict[str, Any],
    cell: dict[str, Any],
    manifest: dict[str, Any],
    report: dict[str, Any],
    run_root: Path,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    task_id = cell["task"]
    profile_id = cell["profile"]
    task = plan["tasks"][task_id]
    profile = plan["profiles"][profile_id]

    if manifest.get("status") != "candidate-complete":
        failures.append("candidate did not complete")
    if report.get("passed") is not True:
        failures.append("evaluator did not pass")
    if report.get("trusted") is not True:
        failures.append("evaluator report is not trusted")
    manifest_task = manifest.get("task")
    if not isinstance(manifest_task, dict) or manifest_task.get("id") != task_id:
        failures.append("run task identity mismatch")
    else:
        if manifest_task.get("digest") != task["task_tree_sha256"]:
            failures.append("run task tree digest mismatch")
        if manifest_task.get("brief_sha256") != task["brief_sha256"]:
            failures.append("run task brief digest mismatch")
    manifest_profile = manifest.get("profile")
    if not isinstance(manifest_profile, dict) or any(
        manifest_profile.get(key) != value for key, value in profile.items()
    ):
        failures.append("run profile mismatch")
    if manifest.get("attempt") != cell["attempt"]:
        failures.append("run attempt mismatch")
    if plan["season"]["id"] == "season-1":
        if manifest.get("backend") != "container":
            failures.append("season-1 candidate did not run in the container backend")
        plane = manifest.get("container_plane")
        candidate_image_id = plan["runtime_environment"]["container_images"][
            "candidate"
        ]["id"]
        if (
            not isinstance(plane, dict)
            or plane.get("image_digest") != candidate_image_id
        ):
            failures.append("candidate container image digest mismatch")

    prompt = manifest.get("prompt")
    prompt_data = prompt if isinstance(prompt, dict) else {}
    if prompt_data.get("task_brief_preserved") is not True:
        failures.append("workspace TASK.md was not preserved")
    workspace_task = run_root / "workspace/TASK.md"
    if not workspace_task.is_file() or _file_sha256(workspace_task) != task["brief_sha256"]:
        failures.append("workspace TASK.md digest mismatch")

    resolved = manifest.get("model_resolved")
    if not isinstance(resolved, str) or not resolved.strip():
        failures.append("resolved model is missing")
    elif not _models_compatible(profile["model"], resolved):
        failures.append("resolved model is incompatible with the profile")

    if plan["season"]["id"] == "season-1":
        goal = manifest.get("goal")
        if not isinstance(goal, dict) or not _goal_receipt_valid(goal):
            failures.append("goal receipt is missing or invalid")
        else:
            if goal.get("mode") != task["goal_mode"]:
                failures.append("goal mode mismatch")
            if goal.get("completion") != task["goal_completion"]:
                failures.append("goal completion policy mismatch")
            if goal.get("candidate_prompt_sha256") != prompt_data.get(
                "candidate_sha256"
            ):
                failures.append("goal prompt digest mismatch")
            if profile["harness"] == "codex":
                if goal.get("native_goal") is not True:
                    failures.append("Codex native goal was not enabled")
                if goal.get("activation_method") != (
                    "codex-native-goal-via-developer-instructions"
                ):
                    failures.append("Codex goal activation method mismatch")
                if goal.get("activation_status") != "observed-complete":
                    failures.append("Codex goal lifecycle did not complete")
                lifecycle = goal.get("lifecycle")
                if not isinstance(lifecycle, list) or not any(
                    isinstance(event, dict)
                    and event.get("tool") == "create_goal"
                    and event.get("objective_sha256") == goal.get("objective_sha256")
                    for event in lifecycle
                ):
                    failures.append("Codex goal creation evidence is missing")
                if not isinstance(lifecycle, list) or not any(
                    isinstance(event, dict)
                    and event.get("tool") == "update_goal"
                    and event.get("status") == "complete"
                    for event in lifecycle
                ):
                    failures.append("Codex goal completion evidence is missing")
            else:
                expected_method = f"{profile['harness']}-system-persistence-policy"
                if goal.get("native_goal") is not False:
                    failures.append("system persistence policy was mislabeled native")
                if goal.get("lifecycle_observable") is not False:
                    failures.append("system persistence lifecycle was mislabeled observable")
                if goal.get("activation_method") != expected_method:
                    failures.append("system persistence activation method mismatch")
                if goal.get("activation_status") != "configured":
                    failures.append("system persistence policy was not configured")
                if goal.get("lifecycle") != []:
                    failures.append("system persistence policy has false lifecycle evidence")

    evaluator = report.get("evaluator")
    frozen_files = plan["frozen_inputs"]["files"]
    evaluator_script = frozen_files["infra/evaluator/evaluate.py"]["sha256"]
    runtime_schema = frozen_files["src/web3dgamebench/runtime_schema.py"]["sha256"]
    if not isinstance(evaluator, dict):
        failures.append("evaluator digest evidence is missing")
    else:
        if evaluator.get("runtime_contract_sha256") != task["runtime_contract_sha256"]:
            failures.append("runtime contract digest mismatch")
        if evaluator.get("script_sha256") != evaluator_script:
            failures.append("evaluator script digest mismatch")
        if evaluator.get("runtime_schema_sha256") != runtime_schema:
            failures.append("runtime schema digest mismatch")
    return not failures, failures


def _candidate_manifest(run_root: Path) -> dict[str, Any]:
    path = run_root / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise MatrixError(f"invalid candidate manifest: {path}") from error
    if not isinstance(manifest, dict):
        raise MatrixError(f"invalid candidate manifest: {path}")
    return manifest


def _evaluation_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise MatrixError(f"invalid evaluator report: {path}") from error
    if not isinstance(report, dict):
        raise MatrixError(f"invalid evaluator report: {path}")
    return report


def _existing_candidate(cell: dict[str, Any]) -> Path | None:
    run_value = cell.get("run")
    if not isinstance(run_value, str):
        return None
    run_root = Path(run_value)
    manifest_path = run_root / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = _candidate_manifest(run_root)
    if manifest.get("status") != "candidate-complete":
        return None
    return run_root


def _archive_incomplete_evaluation(run_root: Path) -> Path | None:
    partials = [
        path for path in (run_root / "render", run_root / "evaluation") if path.exists()
    ]
    if not partials:
        return None
    destination = (
        run_root
        / "infrastructure-attempts"
        / f"evaluation-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    destination.mkdir(parents=True)
    for path in partials:
        path.rename(destination / path.name)
    return destination


def _execute_cell(
    root: Path,
    plan: dict[str, Any],
    receipt_path: Path,
    receipt: dict[str, Any],
    cell: dict[str, Any],
) -> None:
    run_root = _existing_candidate(cell)
    if run_root is None:
        run_root = run_once(
            root,
            cell["task"],
            cell["profile"],
            cell["attempt"],
            backend=receipt["backend"],
        )
        cell["run"] = str(run_root)
        manifest = _candidate_manifest(run_root)
        if manifest.get("status") == "infrastructure-error":
            raise MatrixError(
                "candidate runtime exited without benchmark evidence: "
                f"{run_root} (exit {manifest.get('exit_code')})"
            )
        if manifest.get("status") == "candidate-failure":
            cell.update(
                {
                    "status": "candidate-failure",
                    "passed": False,
                    "trusted": False,
                    "artifacts": close_run_artifacts(run_root),
                    "evidence_failures": ["candidate did not complete"],
                    "completed_at": _now(),
                }
            )
            return
        if manifest.get("status") != "candidate-complete":
            raise MatrixError(
                f"candidate runtime returned an unknown status for {run_root}: "
                f"{manifest.get('status')}"
            )

    report_path = run_root / "evaluation/report.json"
    if report_path.is_file():
        previous_report = _evaluation_report(report_path)
        if previous_report.get("trusted") is not True:
            archived = _archive_incomplete_evaluation(run_root)
            if archived is not None:
                cell.setdefault("infrastructure_attempts", []).append(str(archived))
    if not report_path.is_file():
        archived = _archive_incomplete_evaluation(run_root)
        if archived is not None:
            cell.setdefault("infrastructure_attempts", []).append(str(archived))
        cell["phase"] = "evaluating"
        _write_receipt(receipt_path, receipt)
        report_path = evaluate_run(root, run_root)

    manifest = _candidate_manifest(run_root)
    report = _evaluation_report(report_path)
    if report.get("trusted") is not True:
        errors = report.get("infrastructure_errors")
        detail = "; ".join(str(item) for item in errors) if isinstance(errors, list) else "untrusted evaluator report"
        raise MatrixError(f"evaluator infrastructure failure for {run_root}: {detail}")
    trusted, failures = trusted_cell_gate(plan, cell, manifest, report, run_root)
    cell.update(
        {
            "evaluation": str(report_path),
            "playable": report.get("passed") is True,
            "passed": trusted,
            "trusted": trusted,
            "status": "completed" if trusted else "evidence-failure",
            "artifacts": close_run_artifacts(run_root),
            "evidence_failures": failures,
            "completed_at": _now(),
        }
    )
    cell.pop("phase", None)


def _drive_matrix(
    root: Path,
    plan_path: Path,
    plan: dict[str, Any],
    receipt_path: Path,
    receipt: dict[str, Any],
) -> None:
    for cell in receipt["cells"]:
        if cell.get("status") not in _RESUMABLE_CELL_STATUSES:
            continue
        try:
            plan = _verify_plan_file(plan_path, receipt)
            verify_frozen_inputs(root, plan)
            cell.update(
                {
                    "status": "running",
                    "started_at": _now(),
                    "passed": False,
                    "trusted": False,
                }
            )
            cell.pop("infrastructure_error", None)
            cell.pop("interrupted_at", None)
            _write_receipt(receipt_path, receipt)
            _execute_cell(root, plan, receipt_path, receipt, cell)
        except RunInterrupted as error:
            cell.update(
                {
                    "status": "interrupted",
                    "run": str(error.run_root),
                    "interrupted_at": _now(),
                }
            )
            receipt["status"] = "interrupted"
            _write_receipt(receipt_path, receipt)
            raise MatrixInterrupted(receipt_path) from error
        except KeyboardInterrupt as error:
            cell.update({"status": "interrupted", "interrupted_at": _now()})
            receipt["status"] = "interrupted"
            _write_receipt(receipt_path, receipt)
            raise MatrixInterrupted(receipt_path) from error
        except PlanDriftError as error:
            cell.update(
                {
                    "status": "infrastructure-error",
                    "passed": False,
                    "trusted": False,
                    "infrastructure_error": str(error),
                    "completed_at": _now(),
                }
            )
            receipt["status"] = "invalidated"
            _write_receipt(receipt_path, receipt)
            raise
        except (OSError, RuntimeError, ValueError) as error:
            cell.update(
                {
                    "status": "infrastructure-error",
                    "passed": False,
                    "trusted": False,
                    "infrastructure_error": str(error),
                    "completed_at": _now(),
                }
            )
            _write_receipt(receipt_path, receipt)
            break
        _write_receipt(receipt_path, receipt)

    unfinished = any(
        cell.get("status") in _RESUMABLE_CELL_STATUSES | {"running"}
        for cell in receipt["cells"]
    )
    receipt["status"] = "incomplete" if unfinished else "complete"
    receipt["completed_at"] = _now()
    receipt["summary"] = {
        "total": len(receipt["cells"]),
        "trusted": sum(cell.get("trusted") is True for cell in receipt["cells"]),
        "candidate_failures": sum(
            cell.get("status") == "candidate-failure" for cell in receipt["cells"]
        ),
        "evidence_failures": sum(
            cell.get("status") == "evidence-failure" for cell in receipt["cells"]
        ),
        "infrastructure_errors": sum(
            cell.get("status") == "infrastructure-error" for cell in receipt["cells"]
        ),
    }
    _write_receipt(receipt_path, receipt)


def start_matrix(root: Path, plan_path: Path, *, backend: str = "container") -> Path:
    plan_path = plan_path.expanduser().resolve()
    plan = load_preflight_plan(plan_path)
    season_id = plan["season"]["id"]
    if season_id == "season-1" and backend != "container":
        raise MatrixError("season-1 matrices require the container backend")
    verify_frozen_inputs(root, plan)
    with SeasonLock(season_id):
        receipt_path = runs_dir() / f"matrix-{plan['plan_id']}-{uuid.uuid4().hex[:8]}.json"
        receipt = _new_receipt(plan_path, plan, backend)
        receipt["receipt_path"] = str(receipt_path.resolve())
        _write_receipt(receipt_path, receipt)
        _claim_canonical_matrix(season_id, receipt_path, receipt)
        _drive_matrix(root, plan_path, plan, receipt_path, receipt)
        if receipt.get("status") == "complete":
            _seal_canonical_matrix(season_id, receipt_path, receipt)
    return receipt_path


def resume_matrix(root: Path, receipt_path: Path, *, backend: str | None = None) -> Path:
    receipt_path = receipt_path.expanduser().resolve()
    receipt = load_matrix_receipt(receipt_path)
    if backend is not None and backend != receipt.get("backend"):
        raise MatrixError("resume backend does not match the original matrix")
    season_id = receipt.get("season")
    if not isinstance(season_id, str):
        raise MatrixError("matrix receipt has no season")
    if season_id == "season-1" and receipt.get("backend") != "container":
        raise MatrixError("season-1 matrices require the container backend")
    plan_reference = receipt.get("plan")
    if not isinstance(plan_reference, dict) or not isinstance(plan_reference.get("path"), str):
        raise MatrixError("matrix receipt has no plan path")
    plan_path = Path(plan_reference["path"])
    with SeasonLock(season_id):
        _assert_canonical_matrix(season_id, receipt_path, receipt)
        plan = _verify_plan_file(plan_path, receipt)
        verify_frozen_inputs(root, plan)
        if receipt.get("status") == "complete":
            closure_path = _canonical_closure_path(season_id)
            if closure_path.is_file():
                _verify_canonical_publication_receipt(receipt)
            else:
                _seal_canonical_matrix(season_id, receipt_path, receipt)
            return receipt_path
        for cell in receipt["cells"]:
            if cell.get("status") == "running":
                cell.update(
                    {
                        "status": "interrupted",
                        "interrupted_at": _now(),
                        "interruption_reason": "stale-running-on-resume",
                    }
                )
        receipt["status"] = "running"
        receipt.pop("completed_at", None)
        receipt.pop("summary", None)
        _write_receipt(receipt_path, receipt)
        _drive_matrix(root, plan_path, plan, receipt_path, receipt)
        if receipt.get("status") == "complete":
            _seal_canonical_matrix(season_id, receipt_path, receipt)
    return receipt_path


def create_and_write_plan(root: Path, season_id: str, path: Path) -> Path:
    return write_preflight_plan(path, create_preflight_plan(root, season_id))


def create_plan_for_matrix(root: Path, season_id: str) -> Path:
    directory = runs_dir() / "plans"
    filename = (
        f"{season_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{uuid.uuid4().hex[:8]}.json"
    )
    return create_and_write_plan(root, season_id, directory / filename)
