from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path


class ProcessCancelled(KeyboardInterrupt):
    pass


class ProcessTimedOut(TimeoutError):
    def __init__(self, timeout_seconds: float):
        super().__init__(f"process exceeded {timeout_seconds:g} seconds")
        self.timeout_seconds = timeout_seconds


def _stop_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            process.terminate()
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            process.kill()
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _best_effort_cleanup(cleanup: Callable[[], None] | None) -> None:
    if cleanup is None:
        return
    try:
        cleanup()
    except Exception:
        pass


def run_captured(
    argv: Sequence[str],
    *,
    cwd: os.PathLike[str] | str,
    env: dict[str, str],
    input_text: str | None,
    cancel_event: threading.Event | None = None,
    cleanup: Callable[[], None] | None = None,
    timeout_seconds: float | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an isolated process whose full tree can be cancelled reliably."""

    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if (stdout_path is None) != (stderr_path is None):
        raise ValueError("stdout_path and stderr_path must be provided together")
    output_handles = None
    if stdout_path is not None and stderr_path is not None:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        output_handles = (
            stdout_path.open("w+", encoding="utf-8"),
            stderr_path.open("w+", encoding="utf-8"),
        )
    stdout_target = output_handles[0] if output_handles else subprocess.PIPE
    stderr_target = output_handles[1] if output_handles else subprocess.PIPE
    process = subprocess.Popen(
        argv, cwd=cwd, env=env,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=stdout_target, stderr=stderr_target,
        text=True, start_new_session=True,
    )
    sent_input = False
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise ProcessCancelled
            if deadline is not None and time.monotonic() >= deadline:
                raise ProcessTimedOut(timeout_seconds)
            if output_handles is not None:
                if not sent_input and process.stdin is not None:
                    try:
                        if input_text is not None:
                            process.stdin.write(input_text)
                            process.stdin.flush()
                    except BrokenPipeError:
                        pass
                    process.stdin.close()
                    sent_input = True
                returncode = process.poll()
                if returncode is not None:
                    for handle in output_handles:
                        handle.flush()
                        handle.seek(0)
                    return subprocess.CompletedProcess(
                        list(argv), returncode,
                        output_handles[0].read(), output_handles[1].read(),
                    )
                time.sleep(0.25)
                continue
            try:
                stdout, stderr = process.communicate(
                    input=input_text if not sent_input else None,
                    timeout=0.25,
                )
                return subprocess.CompletedProcess(
                    list(argv), process.returncode, stdout, stderr
                )
            except subprocess.TimeoutExpired:
                sent_input = True
    except (KeyboardInterrupt, ProcessCancelled, ProcessTimedOut):
        _stop_process_group(process)
        _best_effort_cleanup(cleanup)
        raise
    finally:
        if process.poll() is None:
            _stop_process_group(process)
        # Give Docker's --rm cleanup a brief chance before the caller inspects state.
        if process.returncode not in (0, None):
            _best_effort_cleanup(cleanup)
        if output_handles is not None:
            for handle in output_handles:
                handle.close()
        time.sleep(0.01)
