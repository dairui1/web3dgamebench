from __future__ import annotations

from typing import Any

_REQUIRED_CHECKS = (
    "build",
    "desktop.canvas-visible",
    "desktop.nonblank",
    "desktop.starts",
)


def assess_playability(
    report: dict[str, Any],
) -> tuple[bool, list[str], list[str]]:
    """Separate launch/play failures from non-blocking quality warnings."""

    checks = {
        str(item.get("name")): item
        for item in report.get("checks", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    errors: list[str] = []
    warnings: list[str] = []

    build = report.get("build")
    if not isinstance(build, dict) or build.get("passed") is not True:
        errors.append("game build failed")

    for name in _REQUIRED_CHECKS[1:]:
        check = checks.get(name)
        if check is None or check.get("passed") is not True:
            errors.append(f"required playability check failed: {name}")

    for name, check in checks.items():
        if name in _REQUIRED_CHECKS or check.get("passed") is True:
            continue
        detail = check.get("detail")
        suffix = f": {detail}" if detail not in (None, [], "") else ""
        warnings.append(f"{name}{suffix}")

    if report.get("trusted") is not True:
        warnings.append("evaluator evidence could not be fully verified")
    return not errors, errors, warnings
