import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from web3dgamebench.config import load_profiles, load_task
from web3dgamebench.process import ProcessTimedOut
from web3dgamebench.runner import RunInterrupted, _candidate_prompt, prepare, run_once

ROOT = Path(__file__).resolve().parents[1]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_prepare_preserves_the_canonical_task_brief(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    task = load_task(ROOT, "first-night")
    profile = load_profiles(ROOT)["codex-sol-medium"]
    canonical = task.brief.read_bytes()

    _, workspace = prepare(ROOT, task, profile)

    assert task.brief.read_bytes() == canonical
    assert (workspace / "TASK.md").read_bytes() == canonical
    assert b"external persistent-goal control" not in canonical
    assert _candidate_prompt(task).endswith(canonical.decode("utf-8"))


def test_run_manifest_records_goal_receipt_and_observed_codex_lifecycle(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    objective = "Implement TASK.md and stop after a successful npm run build."
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "tool": "create_goal",
                        "arguments": {"objective": objective},
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "tool": "update_goal",
                        "arguments": {"status": "complete"},
                    },
                }
            ),
        ]
    )

    def completed_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("web3dgamebench.runner.run_captured", completed_run)

    run_root = run_once(
        ROOT,
        "first-night",
        "codex-sol-medium",
        backend="native",
    )
    manifest = json.loads((run_root / "manifest.json").read_text())
    canonical = load_task(ROOT, "first-night").brief.read_bytes()

    assert manifest["goal"]["mode"] == "external-goal"
    assert manifest["goal"]["activation_method"] == "codex-app-server-thread-goal-set"
    assert manifest["goal"]["native_goal"] is True
    assert manifest["goal"]["activation_status"] == "observed-complete"
    assert manifest["goal"]["lifecycle"] == [
        {
            "tool": "create_goal",
            "objective_sha256": _sha256(objective.encode()),
        },
        {"tool": "update_goal", "status": "complete"},
    ]
    assert len(manifest["goal"]["receipt_sha256"]) == 64
    assert manifest["prompt"]["task_brief_sha256"] == _sha256(canonical)
    assert manifest["prompt"]["task_brief_preserved"] is True
    assert (run_root / "workspace/TASK.md").read_bytes() == canonical


def test_interrupted_run_preserves_a_resumable_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("web3dgamebench.runner.run_captured", interrupted)

    with pytest.raises(RunInterrupted) as raised:
        run_once(ROOT, "first-night", "codex-sol-medium", backend="native")

    manifest = json.loads(
        (raised.value.run_root / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "interrupted"
    assert manifest["backend"] == "native"
    assert manifest["goal"]["activation_status"] == "not-observed"
    assert manifest["goal"]["lifecycle"] == [
        {"tool": "update_goal", "status": "interrupted"}
    ]
    assert (raised.value.run_root / "workspace/TASK.md").is_file()


def test_nonzero_harness_exit_is_infrastructure_not_candidate_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))

    def failed_runtime(*args, **kwargs):
        return SimpleNamespace(returncode=17, stdout="", stderr="provider unavailable")

    monkeypatch.setattr("web3dgamebench.runner.run_captured", failed_runtime)
    run_root = run_once(ROOT, "first-night", "codex-sol-medium", backend="native")
    manifest = json.loads((run_root / "manifest.json").read_text())

    assert manifest["status"] == "infrastructure-error"
    assert manifest["failure_scope"] == "candidate-runtime"
    assert manifest["exit_code"] == 17


def test_total_timeout_preserves_run_and_classifies_candidate_nontermination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))

    def timed_out(*args, **kwargs):
        kwargs["stdout_path"].write_text('{"type":"partial"}\n')
        kwargs["stderr_path"].write_text("still working\n")
        raise ProcessTimedOut(7200)

    monkeypatch.setattr("web3dgamebench.runner.run_captured", timed_out)
    run_root = run_once(ROOT, "first-night", "codex-sol-medium", backend="native")
    manifest = json.loads((run_root / "manifest.json").read_text())

    assert manifest["status"] == "candidate-failure"
    assert manifest["failure_scope"] == "candidate-non-termination"
    assert manifest["timed_out"] is True
    assert manifest["timeout_seconds"] == 7200
    events = (run_root / "events.jsonl").read_text().splitlines()
    assert json.loads(events[0]) == {"type": "partial"}
    assert json.loads(events[-1])["entry"]["data"]["status"] == "timed_out"


def test_adapter_verification_overrun_is_candidate_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("OPENCODE_GO_APIKEY", "test-key")
    objective = "Implement TASK.md and stop after a successful npm run build."
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "entry_appended",
                    "entry": {
                        "customType": "goal-state",
                        "data": {"goal": {"status": "active", "text": objective}},
                    },
                }
            ),
            json.dumps(
                {
                    "type": "entry_appended",
                    "entry": {
                        "customType": "web3dgamebench-lifecycle",
                        "data": {"schema_version": 2, "status": "timed_out"},
                    },
                }
            ),
        ]
    )

    monkeypatch.setattr(
        "web3dgamebench.runner.run_captured",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout=stdout, stderr="verification overrun"
        ),
    )
    run_root = run_once(ROOT, "first-night", "pi-qwen3-8-flash", backend="native")
    manifest = json.loads((run_root / "manifest.json").read_text())

    assert manifest["status"] == "candidate-failure"
    assert manifest["failure_scope"] == "candidate-verification-overrun"
    assert manifest["goal"]["activation_status"] == "observed-timed_out"


def test_harbor_outer_watchdog_remains_infrastructure_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))

    def timed_out(*args, **kwargs):
        raise ProcessTimedOut(8100)

    monkeypatch.setattr("web3dgamebench.harbor_backend.execute_harbor", timed_out)
    run_root = run_once(ROOT, "first-night", "codex-sol-medium", backend="harbor")
    manifest = json.loads((run_root / "manifest.json").read_text())

    assert manifest["status"] == "infrastructure-error"
    assert manifest["failure_scope"] == "harbor-watchdog"
    assert manifest["goal"]["lifecycle"] == []


def test_argv_prompt_runtime_never_inherits_operator_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("OPENCODE_GO_APIKEY", "test-key")
    observed: dict[str, object] = {}

    def completed_run(*args, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("web3dgamebench.runner.run_captured", completed_run)

    run_once(ROOT, "first-night", "pi-qwen3-8-flash", backend="native")

    assert observed["input_text"] is None


def test_pi_calibration_uses_external_short_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB3DGAMEBENCH_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("OPENCODE_GO_APIKEY", "test-key")
    observed: dict[str, object] = {}

    def completed_run(*args, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("web3dgamebench.runner.run_captured", completed_run)
    run_root = run_once(
        ROOT,
        "first-night",
        "pi-qwen3-8-flash",
        backend="native",
        calibration=True,
    )
    manifest = json.loads((run_root / "manifest.json").read_text())

    assert observed["timeout_seconds"] == 2700
    assert manifest["execution_mode"] == "calibration"
    assert manifest["candidate_timeout_seconds"] == 2700
