import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from web3dgamebench.matrix import MatrixError, create_preflight_plan, write_preflight_plan
from web3dgamebench.smoke import _write_receipt, verify_smoke_receipt

ROOT = Path(__file__).resolve().parents[1]


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


def test_stale_smoke_receipt_is_rejected(tmp_path: Path) -> None:
    plan = create_preflight_plan(ROOT, "season-1")
    plan_path = write_preflight_plan(tmp_path / "plan.json", plan)
    value = _receipt(plan_path, plan)
    value["created_at"] = (datetime.now(UTC) - timedelta(hours=7)).isoformat()
    receipt_path = tmp_path / "smoke.json"
    _write_receipt(receipt_path, value)

    with pytest.raises(MatrixError, match="older than 6 hours"):
        verify_smoke_receipt(plan_path, plan, receipt_path)
