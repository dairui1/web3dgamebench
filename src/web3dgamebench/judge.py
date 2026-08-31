from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from .config import load_judges
from .runtimes import parse_resolved_model


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self' data: blob:; "
            "base-uri 'none'; connect-src 'none'; form-action 'none'; "
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
    result = subprocess.run(["pi", "--version"], capture_output=True, text=True, check=False)
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
    submission_id: str,
    judge_id: str = "pi-sol-medium",
    timeout_seconds: int = 900,
) -> Path:
    if task_id != "signal-drift":
        raise ValueError("the pilot judge currently supports only signal-drift")
    judges = load_judges(root)
    if judge_id not in judges:
        raise ValueError(f"unknown judge: {judge_id}")
    judge = judges[judge_id]
    if judge.harness != "pi" or judge.runs != 1:
        raise ValueError("the pilot runner requires one Pi rollout")
    if shutil.which("pi") is None:
        raise ValueError("pi executable not found")

    public_root = root / "site" / "public"
    game_root = public_root / "playground" / task_id / submission_id
    if not (game_root / "index.html").is_file():
        raise ValueError(f"published game not found: {game_root}")
    extension = root / "infra" / "judge" / "pi" / "playtest-judge.ts"
    prompt_path = root / "infra" / "judge" / "prompts" / f"{task_id}.md"
    rubric_path = root / "infra" / "judge" / "rubrics" / f"{task_id}.json"
    judge_config_path = root / "configs" / "judges.toml"
    for required in (extension, prompt_path, rubric_path, judge_config_path):
        if not required.is_file():
            raise ValueError(f"judge input not found: {required}")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{task_id}-{submission_id}-{judge_id}"
    output = judges_dir() / run_id
    output.mkdir(parents=True, exist_ok=False)

    handler = functools.partial(QuietHandler, directory=public_root)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/playground/{task_id}/{submission_id}/"
    chromium = _chromium()
    manifest_path = output / "manifest.json"
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
        "task_id": task_id,
        "submission_id": submission_id,
        "judge": {
            "id": judge.id,
            "harness": judge.harness,
            "provider": judge.provider,
            "model": judge.model,
            "effort": judge.effort,
            "runs": judge.runs,
            "pi_version": _pi_version(),
        },
        "inputs": {
            "extension_sha256": _sha256(extension),
            "runner_sha256": _sha256(Path(__file__)),
            "judge_config_sha256": _sha256(judge_config_path),
            "prompt_sha256": _sha256(prompt_path),
            "rubric_sha256": _sha256(rubric_path),
            "build_index_sha256": _sha256(game_root / "index.html"),
        },
        "browser": str(chromium),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

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
        manifest["status"] = "complete" if result.returncode == 0 and report_path.is_file() else "failed"
        manifest["exit_code"] = result.returncode
        manifest["resolved_model"] = parse_resolved_model("pi-jsonl-v1", result.stdout)
    except subprocess.TimeoutExpired as error:
        (output / "events.jsonl").write_text(error.stdout or "")
        (output / "stderr.log").write_text(error.stderr or "")
        manifest["status"] = "timeout"
        manifest["exit_code"] = None
    except KeyboardInterrupt:
        manifest["status"] = "interrupted"
        manifest["exit_code"] = None
        interrupted = True
    finally:
        _stop_judge_chromium(output)
        server.shutdown()
        server.server_close()
    manifest["duration_seconds"] = round(time.monotonic() - started, 3)
    manifest["completed_at"] = datetime.now(UTC).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if interrupted:
        raise KeyboardInterrupt

    report_path = output / "judge-report.json"
    if not report_path.is_file():
        raise RuntimeError(f"judge did not produce a report: {output}")
    return report_path
