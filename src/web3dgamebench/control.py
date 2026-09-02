from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .calibration import load_calibration_gate, require_calibration_gate
from .matrix import MatrixError, load_matrix_receipt, request_matrix_pause
from .runner import runs_dir


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class StartRequest(BaseModel):
    plan: str
    smoke_receipt: str
    backend: str = "harbor"


class CalibrationRequest(BaseModel):
    plan: str
    backend: str = "harbor"


class MatrixSupervisor:
    def __init__(self, root: Path, state_root: Path | None = None):
        self.root = root.resolve()
        self.runs = (state_root or runs_dir()).expanduser().resolve()
        self.control = self.runs / "control"
        self.runner_path = self.control / "runner.json"
        self.events_path = self.control / "events.jsonl"
        self.token_path = self.control / "token"
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._log_handle: Any | None = None
        self.control.mkdir(parents=True, exist_ok=True)
        self.token = self._load_or_create_token()

    def _load_or_create_token(self) -> str:
        if self.token_path.is_file():
            token = self.token_path.read_text(encoding="utf-8").strip()
            if token:
                return token
        token = secrets.token_urlsafe(32)
        self.token_path.write_text(token + "\n", encoding="utf-8")
        self.token_path.chmod(0o600)
        return token

    def _event(self, action: str, **fields: Any) -> None:
        event = {"at": _now(), "action": action, **fields}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")

    def _runner(self) -> dict[str, Any]:
        return _read_json(self.runner_path) or {"status": "idle"}

    @staticmethod
    def _pid_alive(pid: object) -> bool:
        if not isinstance(pid, int) or pid <= 1:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _refresh_runner(self) -> dict[str, Any]:
        with self._lock:
            runner = self._runner()
            if self._process is not None:
                returncode = self._process.poll()
                if returncode is not None:
                    runner.update(
                        {
                            "status": "exited",
                            "returncode": returncode,
                            "exited_at": _now(),
                        }
                    )
                    _atomic_json(self.runner_path, runner)
                    self._event(
                        "runner-exited",
                        operation=runner.get("operation"),
                        returncode=returncode,
                    )
                    self._process = None
                    if self._log_handle is not None:
                        self._log_handle.close()
                        self._log_handle = None
            elif runner.get("status") == "running" and not self._pid_alive(
                runner.get("pid")
            ):
                runner.update(
                    {
                        "status": "exited",
                        "returncode": None,
                        "exited_at": _now(),
                        "exit_reason": "runner process is no longer present",
                    }
                )
                _atomic_json(self.runner_path, runner)
            return runner

    def _canonical(self, season: str = "season-1") -> dict[str, Any] | None:
        return _read_json(self.runs / "matrices" / f"canonical-{season}.json")

    def _receipt(
        self, canonical: dict[str, Any] | None
    ) -> tuple[Path | None, dict[str, Any] | None]:
        candidates: list[Path] = []
        if canonical and isinstance(canonical.get("receipt"), str):
            candidates.append(Path(canonical["receipt"]).expanduser())
        runner = self._runner()
        if isinstance(runner.get("receipt"), str):
            candidates.append(Path(runner["receipt"]).expanduser())
        candidates.extend(
            sorted(
                self.runs.glob("matrix-*.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        )
        for path in candidates:
            try:
                return path.resolve(), load_matrix_receipt(path)
            except (MatrixError, OSError, ValueError):
                continue
        return None, None

    def _options(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        plans: list[dict[str, Any]] = []
        for path in sorted(
            (self.runs / "plans").glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            value = _read_json(path)
            if value is None:
                continue
            plans.append(
                {
                    "path": str(path.resolve()),
                    "name": path.name,
                    "plan_id": value.get("plan_id"),
                    "season": (value.get("season") or {}).get("id")
                    if isinstance(value.get("season"), dict)
                    else None,
                    "digest": value.get("plan_digest_sha256"),
                    "candidate_image": (
                        (value.get("runtime_environment") or {})
                        .get("container_images", {})
                        .get("candidate")
                    ),
                    "modified_at": datetime.fromtimestamp(
                        path.stat().st_mtime, UTC
                    ).isoformat(),
                }
            )
        smokes: list[dict[str, Any]] = []
        for path in sorted(
            (self.runs / "smoke").glob("*/receipt.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            value = _read_json(path)
            if value is None:
                continue
            smokes.append(
                {
                    "path": str(path.resolve()),
                    "name": path.parent.name,
                    "status": value.get("status"),
                    "smoke_id": value.get("smoke_id"),
                    "plan_digest": (value.get("plan") or {}).get("digest_sha256")
                    if isinstance(value.get("plan"), dict)
                    else None,
                    "backend": value.get("backend"),
                    "completed_at": value.get("completed_at"),
                }
            )
        return plans[:30], smokes[:30]

    def _receipt_view(
        self, path: Path | None, receipt: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if path is None or receipt is None:
            return None
        cells = []
        for cell in receipt.get("cells", []):
            if not isinstance(cell, dict):
                continue
            cells.append(
                {
                    key: cell.get(key)
                    for key in (
                        "cell_id",
                        "task",
                        "profile",
                        "attempt",
                        "status",
                        "phase",
                        "passed",
                        "trusted",
                        "playable",
                        "started_at",
                        "completed_at",
                        "run",
                        "evaluation",
                        "infrastructure_error",
                        "evidence_failures",
                    )
                }
            )
        plan_snapshot = None
        plan_reference = receipt.get("plan")
        if isinstance(plan_reference, dict) and isinstance(plan_reference.get("path"), str):
            plan_path = Path(plan_reference["path"]).expanduser().resolve()
            if plan_path.is_file() and plan_path.is_relative_to(self.runs):
                plan_snapshot = _read_json(plan_path)
        runtime_environment = (
            plan_snapshot.get("runtime_environment", {}) if plan_snapshot else {}
        )
        return {
            "path": str(path),
            "matrix_id": receipt.get("matrix_id"),
            "season": receipt.get("season"),
            "status": receipt.get("status"),
            "backend": receipt.get("backend"),
            "created_at": receipt.get("created_at"),
            "updated_at": receipt.get("updated_at"),
            "completed_at": receipt.get("completed_at"),
            "plan": receipt.get("plan"),
            "plan_digest": receipt.get("plan_digest_sha256"),
            "harness_smoke": receipt.get("harness_smoke"),
            "execution_window": receipt.get("execution_window"),
            "summary": receipt.get("summary"),
            "provenance": {
                "container_images": runtime_environment.get("container_images"),
                "harbor": runtime_environment.get("harbor"),
                "runtime_control": plan_snapshot.get("runtime_control")
                if plan_snapshot
                else None,
            },
            "cells": cells,
        }

    def snapshot(self) -> dict[str, Any]:
        runner = self._refresh_runner()
        canonical = self._canonical()
        receipt_path, receipt = self._receipt(canonical)
        if (
            canonical is not None
            and receipt_path is not None
            and runner.get("receipt") != str(receipt_path)
        ):
            runner["receipt"] = str(receipt_path)
            _atomic_json(self.runner_path, runner)
        plans, smokes = self._options()
        active = runner.get("status") == "running" and self._pid_alive(runner.get("pid"))
        receipt_status = receipt.get("status") if receipt else None
        has_canonical = canonical is not None
        calibration = load_calibration_gate(self.runs)
        calibration_passed = bool(calibration and calibration.get("status") == "passed")
        return {
            "server_time": _now(),
            "runner": {**runner, "active": active},
            "canonical": canonical,
            "receipt": self._receipt_view(receipt_path, receipt),
            "calibration": calibration,
            "options": {"plans": plans, "smokes": smokes},
            "controls": {
                "can_calibrate": not active and not has_canonical,
                "can_start": not active and not has_canonical and calibration_passed,
                "can_resume": not active
                and has_canonical
                and receipt_status in {"incomplete", "interrupted", "running"},
                "can_pause": active and has_canonical and receipt_status == "running",
                "can_interrupt": active,
            },
        }

    def _safe_option(self, raw: str, parent: Path) -> Path:
        path = Path(raw).expanduser().resolve()
        allowed = parent.resolve()
        if not path.is_file() or not path.is_relative_to(allowed):
            raise ValueError(f"path is outside the managed state directory: {path}")
        return path

    def _spawn(self, operation: str, argv: list[str], receipt: Path | None = None) -> None:
        with self._lock:
            runner = self._refresh_runner()
            if runner.get("status") == "running" and self._pid_alive(runner.get("pid")):
                raise RuntimeError("a managed operation is already running")
            process_id = (
                f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
            )
            log_path = self.control / "processes" / f"{process_id}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = log_path.open("a", encoding="utf-8")
            self._process = subprocess.Popen(
                argv,
                cwd=self.root,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            state = {
                "schema_version": 1,
                "status": "running",
                "operation": operation,
                "pid": self._process.pid,
                "pgid": os.getpgid(self._process.pid),
                "started_at": _now(),
                "log": str(log_path.resolve()),
                "argv": argv,
                "receipt": str(receipt.resolve()) if receipt else None,
            }
            _atomic_json(self.runner_path, state)
            self._event("runner-started", operation=operation, pid=self._process.pid)

    def start(self, request: StartRequest) -> None:
        if request.backend != "harbor":
            raise ValueError("the control plane only starts trusted Harbor matrices")
        if self._canonical() is not None:
            raise RuntimeError("a canonical matrix already exists; resume it instead")
        plan = self._safe_option(request.plan, self.runs / "plans")
        smoke = self._safe_option(request.smoke_receipt, self.runs / "smoke")
        require_calibration_gate(plan, directory=self.runs)
        self._spawn(
            "matrix-start",
            [
                sys.executable,
                "-m",
                "web3dgamebench.cli",
                "matrix",
                "--plan",
                str(plan),
                "--backend",
                "harbor",
                "--smoke-receipt",
                str(smoke),
            ],
        )

    def calibrate(self, request: CalibrationRequest) -> None:
        if request.backend != "harbor":
            raise ValueError("calibration is frozen to the Harbor backend")
        if self._canonical() is not None:
            raise RuntimeError("calibration cannot run after a canonical Matrix is claimed")
        plan = self._safe_option(request.plan, self.runs / "plans")
        self._spawn(
            "calibration",
            [
                sys.executable,
                "-m",
                "web3dgamebench.cli",
                "calibrate",
                "--plan",
                str(plan),
                "--backend",
                "harbor",
            ],
        )

    def resume(self) -> None:
        canonical = self._canonical()
        if canonical is None or not isinstance(canonical.get("receipt"), str):
            raise RuntimeError("there is no canonical matrix to resume")
        receipt = self._safe_option(canonical["receipt"], self.runs)
        self._spawn(
            "matrix-resume",
            [
                sys.executable,
                "-m",
                "web3dgamebench.cli",
                "matrix",
                "--resume",
                str(receipt),
                "--backend",
                "harbor",
            ],
            receipt=receipt,
        )

    def pause(self) -> Path:
        canonical = self._canonical()
        if canonical is None or not isinstance(canonical.get("matrix_id"), str):
            raise RuntimeError("there is no active canonical matrix")
        runner = self._refresh_runner()
        if runner.get("status") != "running" or not self._pid_alive(runner.get("pid")):
            raise RuntimeError("the matrix runner is not active")
        path = request_matrix_pause(
            canonical["matrix_id"], requested_by="local-webui", directory=self.runs
        )
        self._event("pause-requested", matrix_id=canonical["matrix_id"])
        return path

    def interrupt(self) -> None:
        with self._lock:
            runner = self._refresh_runner()
            if runner.get("status") != "running" or not self._pid_alive(runner.get("pid")):
                raise RuntimeError("there is no active managed process")
            pgid = runner.get("pgid")
            if not isinstance(pgid, int) or pgid <= 1:
                raise RuntimeError("managed process group is unavailable")
            os.killpg(pgid, signal.SIGINT)
            self._event("interrupt-requested", operation=runner.get("operation"), pgid=pgid)

    def tail(self, raw: str, limit: int = 200_000) -> tuple[Path, str]:
        path = Path(raw).expanduser().resolve()
        if not path.is_file() or not path.is_relative_to(self.runs):
            raise ValueError("file is outside the managed run directory")
        if path.suffix not in {".json", ".jsonl", ".log", ".txt"}:
            raise ValueError("unsupported artifact type")
        data = path.read_bytes()
        return path, data[-limit:].decode("utf-8", errors="replace")


def create_control_app(root: Path, state_root: Path | None = None) -> FastAPI:
    supervisor = MatrixSupervisor(root, state_root)
    assets = Path(__file__).with_name("control_ui")
    app = FastAPI(title="Web3DGameBench Control", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def local_origin_only(request: Request, call_next: Any) -> Any:
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return JSONResponse({"detail": "local access only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and not origin.startswith(
            ("http://127.0.0.1:", "http://localhost:", "http://[::1]:")
        ):
            return JSONResponse({"detail": "untrusted origin"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'"
        )
        return response

    def authorize(token: str | None) -> None:
        if token is None or not secrets.compare_digest(token, supervisor.token):
            raise HTTPException(status_code=403, detail="invalid control token")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (assets / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("__CONTROL_TOKEN__", supervisor.token))

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return supervisor.snapshot()

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        async def stream() -> Any:
            last = ""
            while True:
                payload = json.dumps(supervisor.snapshot(), separators=(",", ":"))
                if payload != last:
                    yield f"event: state\ndata: {payload}\n\n"
                    last = payload
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/file")
    def file(path: str, download: bool = False) -> Any:
        try:
            resolved, content = supervisor.tail(path)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if download:
            return FileResponse(resolved, filename=resolved.name)
        return {"path": str(resolved), "content": content}

    @app.post("/api/actions/start", status_code=202)
    def start(
        body: StartRequest, x_web3d_control_token: str | None = Header(default=None)
    ) -> dict[str, str]:
        authorize(x_web3d_control_token)
        try:
            supervisor.start(body)
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "accepted"}

    @app.post("/api/actions/calibrate", status_code=202)
    def calibrate(
        body: CalibrationRequest,
        x_web3d_control_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        authorize(x_web3d_control_token)
        try:
            supervisor.calibrate(body)
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "accepted"}

    @app.post("/api/actions/resume", status_code=202)
    def resume(x_web3d_control_token: str | None = Header(default=None)) -> dict[str, str]:
        authorize(x_web3d_control_token)
        try:
            supervisor.resume()
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "accepted"}

    @app.post("/api/actions/pause", status_code=202)
    def pause(x_web3d_control_token: str | None = Header(default=None)) -> dict[str, str]:
        authorize(x_web3d_control_token)
        try:
            path = supervisor.pause()
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "accepted", "command": str(path)}

    @app.post("/api/actions/interrupt", status_code=202)
    def interrupt(
        x_web3d_control_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        authorize(x_web3d_control_token)
        try:
            supervisor.interrupt()
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "accepted"}

    app.mount("/assets", StaticFiles(directory=assets), name="control-assets")
    app.state.supervisor = supervisor
    return app


def serve_control(root: Path, *, host: str, port: int) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("the Matrix control plane must bind to loopback")
    import uvicorn

    uvicorn.run(create_control_app(root), host=host, port=port, log_level="info")
