from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONVERGENCE = ROOT / "infra/candidate/pi-goal-benchmark/convergence.js"


def _run_module(expression: str) -> object:
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", expression],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_verification_commands_are_strict_and_revision_scoped() -> None:
    module = CONVERGENCE.as_uri()
    result = _run_module(
        f"""import {{ classifyVerificationCommand as classify }} from {json.dumps(module)};
console.log(JSON.stringify([
  classify('web3dgamebench-smoke --viewport 1440x900'),
  classify('cd /workspace && web3dgamebench-smoke --viewport 390x844'),
  classify('web3dgamebench-smoke --viewport 1440x900; chromium --headless'),
  classify('node full-playthrough.mjs'),
  classify('chromium --version'),
  classify('which chromium web3dgamebench-smoke'),
  classify('grep -rl "chromium" /workspace'),
  classify('echo chromium')
]));"""
    )
    assert result == [
        {"key": "smoke:1440x900", "viewport": "1440x900"},
        {"key": "smoke:390x844", "viewport": "390x844"},
        {"key": "unbounded", "viewport": None},
        {"key": "unbounded", "viewport": None},
        None,
        None,
        None,
        None,
    ]


def test_verification_convergence_allows_warns_then_terminates() -> None:
    module = CONVERGENCE.as_uri()
    result = _run_module(
        f"""import {{ verificationDecision as decide }} from {json.dumps(module)};
console.log(JSON.stringify([decide(1, 2, 3), decide(2, 2, 3), decide(3, 2, 3)]));"""
    )
    assert result == ["allow", "warn", "terminate"]


def test_completion_contract_is_build_only() -> None:
    source = (ROOT / "infra/candidate/pi-goal-benchmark/benchmark.ts").read_text(
        encoding="utf-8"
    )
    assert 'const ADAPTER_VERSION = "web3dgamebench-pi-adapter-v3"' in source
    assert "successful production build is recorded" in source
    assert "desktop: smokeSchema" not in source
    assert "phone: smokeSchema" not in source
    assert 'viewports: ["1440x900", "390x844"]' not in source
