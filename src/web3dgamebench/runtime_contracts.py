from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .runtime_schema import RuntimeSchemaError, validate_runtime_contract_definition


class RuntimeContractError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedRuntimeContract:
    path: Path
    data: dict
    sha256: str


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def load_runtime_contract(
    root: Path,
    *,
    task_id: str,
    seed: int,
    viewports: Mapping[str, Mapping[str, int]],
) -> LoadedRuntimeContract:
    path = root / "infra" / "evaluator" / "contracts" / f"{task_id}.json"
    try:
        payload = path.read_bytes()
    except FileNotFoundError as error:
        raise RuntimeContractError(f"missing runtime contract for task {task_id}: {path}") from error
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as error:
        raise RuntimeContractError(f"invalid runtime contract JSON in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise RuntimeContractError(f"runtime contract for task {task_id} must be an object")
    try:
        validate_runtime_contract_definition(raw)
    except RuntimeSchemaError as error:
        raise RuntimeContractError(f"invalid runtime contract for task {task_id}: {error}") from error
    if raw.get("task_id") != task_id:
        raise RuntimeContractError(f"runtime contract task id mismatch for {task_id}")
    if raw.get("seed") != seed:
        raise RuntimeContractError(f"runtime contract seed mismatch for task {task_id}")
    expected_viewports = {
        label: {"width": int(value["width"]), "height": int(value["height"])}
        for label, value in viewports.items()
    }
    if raw.get("viewports") != expected_viewports:
        raise RuntimeContractError(f"runtime contract viewport mismatch for task {task_id}")
    return LoadedRuntimeContract(path=path, data=raw, sha256=_sha256_bytes(payload))
