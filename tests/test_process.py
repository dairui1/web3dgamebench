import os
import sys
import threading
import time

import pytest

from web3dgamebench.process import ProcessCancelled, ProcessTimedOut, run_captured


def test_argv_process_receives_eof_instead_of_operator_stdin() -> None:
    result = run_captured(
        [sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"],
        cwd=os.getcwd(),
        env=os.environ.copy(),
        input_text=None,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "0"


def test_cancel_event_terminates_isolated_process_group() -> None:
    cancel = threading.Event()
    timer = threading.Timer(0.1, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(ProcessCancelled):
            run_captured(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=os.getcwd(),
                env=os.environ.copy(),
                input_text=None,
                cancel_event=cancel,
            )
    finally:
        timer.cancel()

    assert time.monotonic() - started < 3


def test_timeout_preserves_streamed_output(tmp_path) -> None:
    stdout_path = tmp_path / "events.jsonl"
    stderr_path = tmp_path / "stderr.log"
    with pytest.raises(ProcessTimedOut):
        run_captured(
            [
                sys.executable,
                "-c",
                "import sys,time; print('before-timeout', flush=True); "
                "print('stderr-before-timeout', file=sys.stderr, flush=True); time.sleep(60)",
            ],
            cwd=os.getcwd(),
            env=os.environ.copy(),
            input_text=None,
            timeout_seconds=0.2,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

    assert stdout_path.read_text().strip() == "before-timeout"
    assert stderr_path.read_text().strip() == "stderr-before-timeout"
