from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import load_judges
from .evaluator import render_dist_sha256
from .runtimes import parse_resolved_model


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args: object,
        directory: str | os.PathLike[str] | None = None,
        mount_path: str = "/",
        **kwargs: object,
    ) -> None:
        self.mount_path = f"/{mount_path.strip('/')}/" if mount_path != "/" else "/"
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _mounted_target(self) -> str | None:
        parsed = urlsplit(self.path)
        if self.mount_path == "/":
            return self.path
        if not parsed.path.startswith(self.mount_path):
            return None
        relative_path = f"/{parsed.path[len(self.mount_path) :]}"
        return urlunsplit(("", "", relative_path, parsed.query, parsed.fragment))

    def send_head(self) -> Any:
        target = self._mounted_target()
        if target is None:
            self.send_error(http.HTTPStatus.NOT_FOUND, "File not found")
            return None
        original_path = self.path
        self.path = target
        try:
            return super().send_head()
        finally:
            self.path = original_path

    def end_headers(self) -> None:
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self' data: blob:; "
            "base-uri 'none'; connect-src 'self' data: blob:; form-action 'none'; "
            "frame-src 'none'; object-src 'none'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'",
        )
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def judges_dir() -> Path:
    return Path.home() / ".local" / "state" / "web3dgamebench" / "judges"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"judge source must not contain symbolic links: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _safe_id(value: str, field: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(
            f"{field} must be 1-128 characters using only letters, digits, '.', '_', or '-'"
        )
    return value


@dataclass(frozen=True)
class JudgeSource:
    kind: str
    id: str
    game_root: Path
    metadata: dict[str, Any]


@dataclass(frozen=True)
class JudgeReportState:
    status: str | None
    valid: bool
    terminal: bool
    evidence_coverage: float | None
    minimum_evidence_coverage: float | None
    coverage_sufficient: bool
    usable: bool


def inspect_judge_report(
    report: Mapping[str, Any],
    *,
    expected_task_id: str | None = None,
    expected_minimum_evidence_coverage: float | None = None,
) -> JudgeReportState:
    """Return the terminal and coverage gate for a parsed judge report."""
    raw_status = report.get("status")
    status = raw_status if isinstance(raw_status, str) else None
    raw_coverage = report.get("evidence_coverage")
    raw_minimum = report.get("minimum_evidence_coverage")
    coverage = (
        float(raw_coverage)
        if isinstance(raw_coverage, (int, float)) and not isinstance(raw_coverage, bool)
        else None
    )
    minimum = (
        float(raw_minimum)
        if isinstance(raw_minimum, (int, float)) and not isinstance(raw_minimum, bool)
        else None
    )
    task_id = report.get("task_id")
    task_valid = isinstance(task_id, str) and bool(task_id)
    if expected_task_id is not None:
        task_valid = task_id == expected_task_id
    coverage_valid = (
        coverage is not None
        and minimum is not None
        and 0 <= coverage <= 100
        and 0 < minimum <= 100
    )
    if expected_minimum_evidence_coverage is not None:
        coverage_valid = bool(
            coverage_valid and minimum == float(expected_minimum_evidence_coverage)
        )
    coverage_sufficient = bool(coverage_valid and coverage >= minimum)
    declared_coverage = report.get("meets_minimum_evidence_coverage")
    status_consistent = (
        isinstance(declared_coverage, bool)
        and declared_coverage == coverage_sufficient
        and (status == "complete") == coverage_sufficient
    )
    valid = bool(
        report.get("schema_version") == 2
        and task_valid
        and coverage_valid
        and status in {"complete", "insufficient-evidence"}
        and status_consistent
    )
    return JudgeReportState(
        status=status,
        valid=valid,
        terminal=valid,
        evidence_coverage=coverage,
        minimum_evidence_coverage=minimum,
        coverage_sufficient=coverage_sufficient,
        usable=bool(valid and status == "complete" and coverage_sufficient),
    )


def _validate_game_root(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError(f"judge source must not be a symbolic link: {path}")
    resolved = path.expanduser().resolve()
    if not resolved.is_dir() or not (resolved / "index.html").is_file():
        raise ValueError(f"static game build not found: {resolved}")
    _tree_sha256(resolved)
    return resolved


def _models_compatible(expected: str, resolved: str) -> bool:
    def normalize(value: str) -> str:
        return value.strip().lower().split("/")[-1].split(":")[0].replace("_", "-")

    wanted = normalize(expected)
    actual = normalize(resolved)
    return wanted == actual or actual.startswith(f"{wanted}-")


def resolve_judge_source(
    root: Path,
    task_id: str,
    *,
    submission_id: str | None = None,
    run_root: Path | None = None,
    dist_path: Path | None = None,
) -> JudgeSource:
    """Resolve exactly one published or private static build without copying it."""
    task_id = _safe_id(task_id, "task id")
    selected = sum(value is not None for value in (submission_id, run_root, dist_path))
    if selected != 1:
        raise ValueError(
            "choose exactly one judge source: submission_id, run_root, or dist_path"
        )

    if submission_id is not None:
        source_id = _safe_id(submission_id, "submission id")
        game_root = _validate_game_root(
            root / "site" / "public" / "playground" / task_id / source_id
        )
        return JudgeSource(
            kind="published-submission",
            id=source_id,
            game_root=game_root,
            metadata={"submission_id": source_id},
        )

    if run_root is not None:
        private_root = run_root.expanduser().resolve()
        manifest_path = private_root / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"private run manifest not found: {manifest_path}")
        try:
            run_manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError) as error:
            raise ValueError(f"invalid private run manifest: {manifest_path}") from error
        manifest_task = run_manifest.get("task")
        manifest_task_id = (
            manifest_task.get("id") if isinstance(manifest_task, dict) else None
        )
        if manifest_task_id != task_id:
            raise ValueError(
                f"private run task mismatch: expected {task_id}, found {manifest_task_id!r}"
            )
        source_id = _safe_id(str(run_manifest.get("run_id", "")), "private run id")
        manifest_profile = run_manifest.get("profile")
        manifest_profile_id = (
            manifest_profile.get("id") if isinstance(manifest_profile, dict) else None
        )
        profile_id = (
            _safe_id(manifest_profile_id, "private run profile id")
            if isinstance(manifest_profile_id, str)
            else None
        )
        game_root = _validate_game_root(private_root / "render" / "dist")
        evaluation_path = private_root / "evaluation" / "report.json"
        if not evaluation_path.is_file():
            raise ValueError(
                f"trusted passing evaluation report not found: {evaluation_path}"
            )
        try:
            evaluation = json.loads(evaluation_path.read_text())
        except (json.JSONDecodeError, OSError) as error:
            raise ValueError(
                f"invalid private run evaluation report: {evaluation_path}"
            ) from error
        if (
            not isinstance(evaluation, dict)
            or evaluation.get("task_id") != task_id
            or evaluation.get("trusted") is not True
            or evaluation.get("passed") is not True
        ):
            raise ValueError(
                f"private run evaluation must be trusted and passing for {task_id}: "
                f"{evaluation_path}"
            )
        evidence = evaluation.get("evidence")
        expected_dist_digest = (
            evidence.get("render_dist_sha256") if isinstance(evidence, dict) else None
        )
        if not isinstance(expected_dist_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_dist_digest
        ):
            raise ValueError(
                f"private run evaluation has no valid render dist digest: {evaluation_path}"
            )
        if render_dist_sha256(game_root) != expected_dist_digest:
            raise ValueError(
                f"private run render dist changed after evaluation: {game_root}"
            )
        return JudgeSource(
            kind="private-run",
            id=source_id,
            game_root=game_root,
            metadata={
                "run_id": source_id,
                "run_manifest": str(manifest_path),
                "run_manifest_sha256": _sha256(manifest_path),
                "evaluation_report": str(evaluation_path),
                "evaluation_report_sha256": _sha256(evaluation_path),
                "render_dist_sha256": expected_dist_digest,
                **({"profile_id": profile_id} if profile_id else {}),
            },
        )

    assert dist_path is not None
    game_root = _validate_game_root(dist_path)
    tree_digest = _tree_sha256(game_root)
    return JudgeSource(
        kind="private-dist",
        id=f"dist-{tree_digest[:12]}",
        game_root=game_root,
        metadata={},
    )


_JUDGE_BUDGET_LIMITS = {
    "observations": (1, 100),
    "input_actions": (1, 500),
    "wait_actions": (1, 300),
    "total_wait_ms": (1_000, 600_000),
    "max_wait_ms": (50, 30_000),
    "max_input_duration_ms": (50, 15_000),
}


def _validate_judge_runtime_config(rubric: Mapping[str, Any], path: Path) -> None:
    viewports = rubric.get("viewports")
    if not isinstance(viewports, dict) or set(viewports) != {"desktop", "phone"}:
        raise ValueError(f"judge rubric requires desktop and phone viewports: {path}")
    for name, viewport in viewports.items():
        if not isinstance(viewport, dict) or set(viewport) != {"width", "height", "mobile"}:
            raise ValueError(f"judge rubric viewport {name} is invalid: {path}")
        width = viewport["width"]
        height = viewport["height"]
        mobile = viewport["mobile"]
        if (
            isinstance(width, bool)
            or not isinstance(width, int)
            or not 320 <= width <= 3840
            or isinstance(height, bool)
            or not isinstance(height, int)
            or not 320 <= height <= 2160
            or not isinstance(mobile, bool)
        ):
            raise ValueError(f"judge rubric viewport {name} values are invalid: {path}")
    if viewports["desktop"]["mobile"] or not viewports["phone"]["mobile"]:
        raise ValueError(f"judge rubric viewport mobile flags are invalid: {path}")

    budgets = rubric.get("budgets")
    if not isinstance(budgets, dict) or set(budgets) != set(_JUDGE_BUDGET_LIMITS):
        raise ValueError(f"judge rubric budgets are missing or invalid: {path}")
    for name, (minimum, maximum) in _JUDGE_BUDGET_LIMITS.items():
        value = budgets[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not minimum <= value <= maximum
        ):
            raise ValueError(f"judge rubric budget {name} is invalid: {path}")
    if budgets["max_wait_ms"] > budgets["total_wait_ms"]:
        raise ValueError(f"judge rubric max wait exceeds total wait budget: {path}")


def _load_rubric(path: Path, task_id: str) -> dict[str, Any]:
    try:
        rubric = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid judge rubric: {path}") from error
    if rubric.get("schema_version") != 2 or rubric.get("task_id") != task_id:
        raise ValueError(f"judge rubric does not match task {task_id}: {path}")
    criteria = rubric.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError(f"judge rubric has no criteria: {path}")
    if any(not isinstance(item, dict) for item in criteria):
        raise ValueError(f"judge rubric criteria must be objects: {path}")
    criterion_ids = [item.get("id") for item in criteria]
    if any(not isinstance(value, str) or not value for value in criterion_ids):
        raise ValueError(f"judge rubric criterion IDs must be non-empty strings: {path}")
    if len(set(criterion_ids)) != len(criteria):
        raise ValueError(f"judge rubric criterion IDs must be unique: {path}")
    weights = [item.get("weight") for item in criteria]
    if any(
        isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0
        for weight in weights
    ):
        raise ValueError(f"judge rubric weights must be positive integers: {path}")
    if sum(weights) != 100:
        raise ValueError(f"judge rubric weights must sum to 100: {path}")
    if any(
        not isinstance(item.get("description"), str) or not item["description"]
        for item in criteria
    ):
        raise ValueError(f"judge rubric descriptions must be non-empty strings: {path}")
    minimum_coverage = rubric.get("minimum_evidence_coverage")
    if (
        isinstance(minimum_coverage, bool)
        or not isinstance(minimum_coverage, (int, float))
        or not 0 < minimum_coverage <= 100
    ):
        raise ValueError(f"judge rubric requires a valid minimum evidence coverage: {path}")
    allowed_evidence = {"visual", "interaction", "either"}
    if any(item.get("evidence_requirement") not in allowed_evidence for item in criteria):
        raise ValueError(f"judge rubric has an invalid evidence requirement: {path}")
    _validate_judge_runtime_config(rubric, path)
    return rubric


def validate_judge_assets(root: Path, task_id: str) -> dict[str, Any]:
    """Validate static judge assets without requiring Pi or Chromium."""
    task_id = _safe_id(task_id, "task id")
    prompt_path = root / "infra" / "judge" / "prompts" / f"{task_id}.md"
    rubric_path = root / "infra" / "judge" / "rubrics" / f"{task_id}.json"
    for required in (prompt_path, rubric_path):
        if not required.is_file():
            raise ValueError(f"judge input not found: {required}")
    rubric = _load_rubric(rubric_path, task_id)
    prompt = prompt_path.read_text()
    for index, criterion in enumerate(rubric["criteria"], start=1):
        marker = f"{index}. {criterion['id']} ({criterion['weight']})"
        if marker not in prompt:
            raise ValueError(
                f"judge prompt is missing rubric marker {marker!r}: {prompt_path}"
            )
    return rubric


def _write_json_once(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as destination:
        json.dump(value, destination, indent=2)
        destination.write("\n")


def _captured_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _chromium() -> Path:
    configured = os.environ.get("W3GB_CHROMIUM")
    if configured and Path(configured).is_file():
        return Path(configured)
    candidates = sorted(
        (Path.home() / "Library" / "Caches" / "ms-playwright").glob(
            "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"
        ),
        reverse=True,
    )
    if not candidates:
        raise ValueError("Playwright Chromium was not found; set W3GB_CHROMIUM")
    return candidates[0]


def _pi_version() -> str:
    result = subprocess.run(
        ["pi", "--version"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or result.stderr.strip() or "unknown"


def _stop_judge_chromium(output: Path) -> None:
    pid_path = output / "chromium.pid"
    if not pid_path.is_file():
        return
    try:
        os.killpg(int(pid_path.read_text().strip()), signal.SIGKILL)
    except (ProcessLookupError, ValueError):
        pass


def run_judge(
    root: Path,
    task_id: str,
    submission_id: str | None = None,
    judge_id: str = "pi-sol-medium",
    timeout_seconds: int = 900,
    *,
    run_root: Path | None = None,
    dist_path: Path | None = None,
) -> Path:
    source = resolve_judge_source(
        root,
        task_id,
        submission_id=submission_id,
        run_root=run_root,
        dist_path=dist_path,
    )
    judges = load_judges(root)
    if judge_id not in judges:
        raise ValueError(f"unknown judge: {judge_id}")
    judge = judges[judge_id]
    if judge.harness != "pi" or judge.runs != 1:
        raise ValueError("the judge runner requires one Pi rollout")
    if shutil.which("pi") is None:
        raise ValueError("pi executable not found")

    extension = root / "infra" / "judge" / "pi" / "playtest-judge.ts"
    prompt_path = root / "infra" / "judge" / "prompts" / f"{task_id}.md"
    rubric_path = root / "infra" / "judge" / "rubrics" / f"{task_id}.json"
    judge_config_path = root / "configs" / "judges.toml"
    for required in (extension, prompt_path, rubric_path, judge_config_path):
        if not required.is_file():
            raise ValueError(f"judge input not found: {required}")
    rubric = validate_judge_assets(root, task_id)

    chromium = _chromium()
    pi_version = _pi_version()
    source_digest = _tree_sha256(source.game_root)
    source_label = source.id
    if len(source_label) > 64:
        source_label = (
            f"{source_label[:51]}-{hashlib.sha256(source.id.encode()).hexdigest()[:12]}"
        )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{task_id}-{source_label}-{judge_id}"
    output = judges_dir() / run_id
    output.mkdir(parents=True, exist_ok=False)

    route_id = source.metadata.get("profile_id", source.id)
    if not isinstance(route_id, str):
        raise TypeError("judge source has an invalid route identity")
    mount_path = f"/playground/{task_id}/{route_id}/"
    handler = functools.partial(
        QuietHandler, directory=source.game_root, mount_path=mount_path
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}{mount_path}"
    manifest_path = output / "manifest.json"
    manifest = {
        "schema_version": 2,
        "run_id": run_id,
        "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
        "task_id": task_id,
        "source": {
            "kind": source.kind,
            "id": source.id,
            "path": str(source.game_root),
            "tree_sha256": source_digest,
            **source.metadata,
        },
        "judge": {
            "id": judge.id,
            "harness": judge.harness,
            "provider": judge.provider,
            "model": judge.model,
            "effort": judge.effort,
            "runs": judge.runs,
            "pi_version": pi_version,
        },
        "inputs": {
            "extension_sha256": _sha256(extension),
            "runner_sha256": _sha256(Path(__file__)),
            "judge_config_sha256": _sha256(judge_config_path),
            "prompt_sha256": _sha256(prompt_path),
            "rubric_sha256": _sha256(rubric_path),
            "build_index_sha256": _sha256(source.game_root / "index.html"),
        },
        "scoring": {
            "unverified_is_zero": True,
            "minimum_evidence_coverage": rubric["minimum_evidence_coverage"],
        },
        "viewports": rubric["viewports"],
        "budgets": rubric["budgets"],
        "browser": str(chromium),
        "served_url": url,
        "served_path": mount_path,
    }

    env = os.environ.copy()
    env.update(
        {
            "W3GB_JUDGE_OUTPUT": str(output),
            "W3GB_JUDGE_URL": url,
            "W3GB_CHROMIUM": str(chromium),
            "W3GB_JUDGE_RUBRIC": str(rubric_path),
        }
    )
    command = [
        "pi",
        "--provider",
        judge.provider,
        "--model",
        judge.model,
        "--thinking",
        judge.effort,
        "--mode",
        "json",
        "--print",
        "--no-session",
        "--no-context-files",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-extensions",
        "--extension",
        str(extension),
        "--no-builtin-tools",
        "--tools",
        "game_observe,game_act,game_set_viewport,game_restart,judge_record_criterion,judge_finish",
        "--no-approve",
        "--system-prompt",
        prompt_path.read_text(),
        "Evaluate the delivered game now. Complete the structured rubric using only the provided tools.",
    ]
    started = time.monotonic()
    interrupted = False
    deferred_error: Exception | None = None
    judge_identity_valid = False
    judge_identity_error: str | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="web3dgamebench-judge-") as temporary:
            result = subprocess.run(
                command,
                cwd=temporary,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        (output / "events.jsonl").write_text(result.stdout)
        (output / "stderr.log").write_text(result.stderr)
        report_path = output / "judge-report.json"
        manifest["status"] = (
            "complete" if result.returncode == 0 and report_path.is_file() else "failed"
        )
        manifest["exit_code"] = result.returncode
        resolved_model = parse_resolved_model("pi-jsonl-v1", result.stdout)
        judge_identity_valid = bool(
            isinstance(resolved_model, str)
            and resolved_model.strip()
            and _models_compatible(judge.model, resolved_model)
        )
        manifest["resolved_model"] = resolved_model
        manifest["judge_identity"] = {
            "expected_model": judge.model,
            "resolved_model": resolved_model,
            "compatible": judge_identity_valid,
        }
        if not judge_identity_valid:
            judge_identity_error = (
                "resolved judge model is missing"
                if not isinstance(resolved_model, str) or not resolved_model.strip()
                else (
                    f"resolved judge model {resolved_model!r} is incompatible with "
                    f"configured model {judge.model!r}"
                )
            )
            manifest["status"] = "infrastructure-error"
            manifest["failure_scope"] = "judge-identity"
            manifest["identity_error"] = judge_identity_error
    except subprocess.TimeoutExpired as error:
        (output / "events.jsonl").write_text(_captured_text(error.stdout))
        (output / "stderr.log").write_text(_captured_text(error.stderr))
        manifest["status"] = "timeout"
        manifest["exit_code"] = None
    except KeyboardInterrupt:
        manifest["status"] = "interrupted"
        manifest["exit_code"] = None
        interrupted = True
    except (OSError, RuntimeError, ValueError) as error:
        manifest["status"] = "infrastructure-error"
        manifest["exit_code"] = None
        manifest["error"] = f"{type(error).__name__}: {error}"
        deferred_error = error
    finally:
        _stop_judge_chromium(output)
        server.shutdown()
        server.server_close()
    manifest["duration_seconds"] = round(time.monotonic() - started, 3)
    manifest["completed_at"] = datetime.now(UTC).isoformat()
    try:
        final_source_digest = _tree_sha256(source.game_root)
    except (OSError, ValueError) as error:
        final_source_digest = None
        manifest["status"] = "source-unreadable"
        manifest["source_error"] = f"{type(error).__name__}: {error}"
    manifest["source"]["unchanged"] = final_source_digest == source_digest
    manifest["source"]["tree_sha256_after"] = final_source_digest
    if final_source_digest is not None and final_source_digest != source_digest:
        manifest["status"] = "source-mutated"
    report_path = output / "judge-report.json"
    report_valid = False
    report_usable = False
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text())
            report_state = inspect_judge_report(
                report,
                expected_task_id=task_id,
                expected_minimum_evidence_coverage=rubric["minimum_evidence_coverage"],
            )
            if not report_state.terminal:
                raise ValueError("report schema, task, status, or coverage gate is invalid")
            report_valid = True
            report_usable = report_state.usable
            manifest["report_status"] = report_state.status
            manifest["provisional_score"] = report.get("provisional_score")
            manifest["evidence_coverage"] = report_state.evidence_coverage
            manifest["coverage_sufficient"] = report_state.coverage_sufficient
            if manifest["status"] == "complete":
                manifest["status"] = report_state.status
        except (json.JSONDecodeError, OSError, ValueError) as error:
            manifest["status"] = "invalid-report"
            manifest["report_error"] = f"{type(error).__name__}: {error}"
    if report_path.is_file() and not judge_identity_valid:
        judge_identity_error = judge_identity_error or "resolved judge model is missing"
        manifest["status"] = "infrastructure-error"
        manifest["failure_scope"] = "judge-identity"
        manifest["identity_error"] = judge_identity_error
        manifest.setdefault(
            "judge_identity",
            {
                "expected_model": judge.model,
                "resolved_model": None,
                "compatible": False,
            },
        )
    manifest["usable"] = bool(
        report_usable
        and judge_identity_valid
        and manifest["status"] == "complete"
        and final_source_digest == source_digest
    )
    _write_json_once(manifest_path, manifest)
    if interrupted:
        raise KeyboardInterrupt
    if deferred_error is not None:
        raise deferred_error
    if final_source_digest != source_digest:
        raise RuntimeError(f"judge source changed during playtest: {source.game_root}")
    if report_path.is_file() and not judge_identity_valid:
        raise RuntimeError(
            f"judge report has an invalid model identity: {judge_identity_error}"
        )

    if not report_path.is_file():
        raise RuntimeError(f"judge did not produce a report: {output}")
    if not report_valid:
        raise RuntimeError(f"judge produced an invalid report: {output}")
    return report_path
