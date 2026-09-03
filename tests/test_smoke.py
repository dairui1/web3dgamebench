import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from web3dgamebench.matrix import MatrixError, create_preflight_plan, write_preflight_plan
from web3dgamebench.smoke import (
    _FIXTURE,
    _FIXTURE_SCRIPT,
    _write_receipt,
    verify_smoke_receipt,
)

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_fixture_respects_the_bounded_server_csp() -> None:
    assert '<script src="app.js"></script>' in _FIXTURE
    assert "<script>" not in _FIXTURE
    assert "window.__WEB3DGAMEBENCH__" in _FIXTURE_SCRIPT


def _receipt(plan_path: Path, plan: dict) -> dict:
    return {
        "schema_version": 1,
        "smoke_id": "smoke-test",
        "status": "passed",
        "created_at": datetime.now(UTC).isoformat(),
        "plan": {
            "path": str(plan_path),
            "digest_sha256": plan["plan_digest_sha256"],
            "file_sha256": __import__("hashlib").sha256(plan_path.read_bytes()).hexdigest(),
        },
        "candidate_image": copy.deepcopy(
            plan["runtime_environment"]["container_images"]["candidate"]
        ),
        "probes": [
            {"harness": harness, "status": "passed"}
            for harness in ("codex", "claude-code", "pi")
        ],
    }


def test_smoke_receipt_is_bound_to_plan_image_and_all_harnesses(tmp_path: Path) -> None:
    plan = create_preflight_plan(ROOT, "season-1")
    plan_path = write_preflight_plan(tmp_path / "plan.json", plan)
    receipt_path = tmp_path / "smoke.json"
    _write_receipt(receipt_path, _receipt(plan_path, plan))

    verified = verify_smoke_receipt(plan_path, plan, receipt_path)

    assert verified["status"] == "passed"


def test_smoke_receipt_accepts_a_subscription_limited_harness(tmp_path: Path) -> None:
    plan = create_preflight_plan(ROOT, "season-1")
    plan_path = write_preflight_plan(tmp_path / "plan.json", plan)
    value = _receipt(plan_path, plan)
    value["probes"][-1]["status"] = "subscription-limited"
    receipt_path = tmp_path / "smoke.json"
    _write_receipt(receipt_path, value)

    verified = verify_smoke_receipt(plan_path, plan, receipt_path)

    assert verified["probes"][-1]["status"] == "subscription-limited"


def test_stale_smoke_receipt_is_rejected(tmp_path: Path) -> None:
    plan = create_preflight_plan(ROOT, "season-1")
    plan_path = write_preflight_plan(tmp_path / "plan.json", plan)
    value = _receipt(plan_path, plan)
    value["created_at"] = (datetime.now(UTC) - timedelta(hours=7)).isoformat()
    receipt_path = tmp_path / "smoke.json"
    _write_receipt(receipt_path, value)

    with pytest.raises(MatrixError, match="older than 6 hours"):
        verify_smoke_receipt(plan_path, plan, receipt_path)
