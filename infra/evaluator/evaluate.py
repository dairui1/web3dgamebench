from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import io
import json
import math
import re
import threading
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

try:
    from web3dgamebench import runtime_schema as runtime_schema_module
except ModuleNotFoundError:
    import runtime_schema as runtime_schema_module  # type: ignore[no-redef]

validate_runtime_contract_definition = runtime_schema_module.validate_runtime_contract_definition

SUBMISSION = Path("/submission")
OUTPUT = Path("/output")


class ProductionRouteHandler(http.server.SimpleHTTPRequestHandler):
    """Serve a bundle only beneath the nested route used by the public site."""

    def __init__(
        self,
        *args: object,
        directory: str | Path | None = None,
        mount_path: str,
        **kwargs: object,
    ) -> None:
        self.mount_path = f"/{mount_path.strip('/')}/"
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _mounted_target(self) -> str | None:
        parsed = urlsplit(self.path)
        if not parsed.path.startswith(self.mount_path):
            return None
        relative_path = f"/{parsed.path[len(self.mount_path):]}"
        return urlunsplit(("", "", relative_path, parsed.query, parsed.fragment))

    def send_head(self) -> Any:
        target = self._mounted_target()
        if target is None:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None
        original_path = self.path
        self.path = target
        try:
            return super().send_head()
        finally:
            self.path = original_path

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def _json_safe(value: object, *, depth: int = 0) -> object:
    if depth > 6:
        return "<depth-limit>"
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else f"<non-finite:{value}>"
    if isinstance(value, list):
        items = [_json_safe(item, depth=depth + 1) for item in value[:20]]
        if len(value) > 20:
            items.append(f"<{len(value) - 20} more items>")
        return items
    if isinstance(value, dict):
        items = list(value.items())
        result = {
            str(key): _json_safe(item, depth=depth + 1) for key, item in items[:50]
        }
        if len(items) > 50:
            result["<truncated>"] = f"{len(items) - 50} more fields"
        return result
    return repr(value)


def check(name: str, passed: bool, detail: object = None) -> dict:
    return {"name": name, "passed": bool(passed), "detail": _json_safe(detail)}


def _same_value(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    return bool(left == right)


def _numeric(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _state_errors(value: object, schema: object, path: str = "$") -> list[str]:
    if not isinstance(schema, dict):
        return [f"{path}: malformed schema"]
    kind = schema.get("type")
    errors: list[str] = []
    if kind == "object":
        if not isinstance(value, dict):
            return [f"{path}: expected object"]
        required = schema.get("required")
        if not isinstance(required, dict):
            return [f"{path}: malformed required fields"]
        for name, child_schema in required.items():
            if name not in value:
                errors.append(f"{path}.{name}: missing")
            else:
                errors.extend(_state_errors(value[name], child_schema, f"{path}.{name}"))
        return errors
    if kind == "array":
        if not isinstance(value, list):
            return [f"{path}: expected array"]
        length = schema.get("length")
        if isinstance(length, int) and len(value) != length:
            errors.append(f"{path}: expected length {length}, got {len(value)}")
        for index, item in enumerate(value):
            errors.extend(_state_errors(item, schema.get("items"), f"{path}[{index}]"))
        return errors
    if kind == "vec3":
        if not isinstance(value, dict):
            return [f"{path}: expected vec3 object"]
        for axis in "xyz":
            if axis not in value:
                errors.append(f"{path}.{axis}: missing")
            elif not _numeric(value[axis]):
                errors.append(f"{path}.{axis}: expected finite number")
        return errors
    if kind == "number":
        if not _numeric(value):
            return [f"{path}: expected finite number"]
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{path}: expected integer"]
    elif kind == "boolean":
        if not isinstance(value, bool):
            return [f"{path}: expected boolean"]
    elif kind == "string":
        if not isinstance(value, str):
            return [f"{path}: expected string"]
    elif kind == "string-or-null":
        if value is not None and not isinstance(value, str):
            return [f"{path}: expected string or null"]
    elif kind == "enum":
        values = schema.get("values")
        if not isinstance(values, list) or not any(
            _same_value(value, item) for item in values
        ):
            return [f"{path}: value is outside enum"]
    else:
        return [f"{path}: unsupported schema type {kind!r}"]

    if "const" in schema and not _same_value(value, schema["const"]):
        errors.append(f"{path}: expected constant {schema['const']!r}")
    enum = schema.get("enum")
    if enum is not None and (
        not isinstance(enum, list)
        or not any(_same_value(value, item) for item in enum)
    ):
        errors.append(f"{path}: value is outside enum")
    if _numeric(value):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if _numeric(minimum) and value < minimum:
            errors.append(f"{path}: below minimum {minimum}")
        if _numeric(maximum) and value > maximum:
            errors.append(f"{path}: above maximum {maximum}")
    return errors


def _path_value(value: object, path: str) -> tuple[bool, object]:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _condition_passes(state: object, condition: object) -> bool:
    if not isinstance(condition, dict) or not isinstance(condition.get("path"), str):
        return False
    found, value = _path_value(state, condition["path"])
    return found and "equals" in condition and _same_value(value, condition["equals"])


def _assertion_errors(state: object, assertion: object) -> list[str]:
    if not isinstance(assertion, dict) or not isinstance(assertion.get("path"), str):
        return ["malformed invariant assertion"]
    path = assertion["path"]
    found, value = _path_value(state, path)
    if not found:
        return [f"$.{path}: invariant field missing"]
    if "equals" in assertion and not _same_value(value, assertion["equals"]):
        return [f"$.{path}: invariant expected {assertion['equals']!r}"]
    if "minimum" in assertion and (
        not _numeric(value) or value < assertion["minimum"]
    ):
        return [f"$.{path}: invariant below minimum {assertion['minimum']}"]
    if "maximum" in assertion and (
        not _numeric(value) or value > assertion["maximum"]
    ):
        return [f"$.{path}: invariant above maximum {assertion['maximum']}"]
    if "one_of" in assertion and not any(
        _same_value(value, item) for item in assertion["one_of"]
    ):
        return [f"$.{path}: invariant value is outside allowed reset values"]
    return []


def state_errors(state: object, contract: dict) -> list[str]:
    errors = _state_errors(state, contract.get("state_schema"))
    if errors:
        return errors
    for invariant in contract.get("invariants", []):
        if not isinstance(invariant, dict):
            errors.append("malformed invariant")
            continue
        if _condition_passes(state, invariant.get("when")):
            assertions = invariant.get("assert")
            if not isinstance(assertions, list):
                errors.append("malformed invariant assertions")
                continue
            for assertion in assertions:
                errors.extend(_assertion_errors(state, assertion))
    return errors


def valid_state(state: object, contract: dict) -> bool:
    return not state_errors(state, contract)


def _validate_contract_definition(contract: object) -> dict:
    return validate_runtime_contract_definition(contract)


def load_evaluator_config(path: Path, evaluator_path: Path | None = None) -> dict:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load evaluator config {path}: {error}") from error
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("unsupported evaluator config")
    contract = _validate_contract_definition(config.get("runtime_contract"))
    if config.get("task_id") != contract["task_id"]:
        raise ValueError("evaluator config task id does not match runtime contract")
    checks = config.get("checks")
    expected_checks = {
        "build",
        "canvas_nonblank",
        "keyboard_input",
        "pointer_or_touch_input",
        "restart",
        "resize",
        "runtime_state",
    }
    if not isinstance(checks, dict) or set(checks) != expected_checks:
        raise ValueError("evaluator config has invalid checks")
    if any(not isinstance(value, bool) for value in checks.values()):
        raise ValueError("evaluator checks must be booleans")
    for digest_name in (
        "runtime_contract_sha256",
        "evaluator_sha256",
        "runtime_schema_sha256",
        "render_source_sha256",
        "post_build_render_source_sha256",
        "render_dist_sha256",
    ):
        digest = config.get(digest_name)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"evaluator config has invalid {digest_name}")
    if not isinstance(config.get("render_source_unchanged"), bool):
        raise ValueError(  # noqa: TRY004 - invalid serialized data, not an API type error
            "evaluator config has invalid render_source_unchanged"
        )
    runtime_contract_path = path.parent / "runtime-contract.json"
    try:
        runtime_contract_bytes = runtime_contract_path.read_bytes()
        runtime_contract_copy = json.loads(runtime_contract_bytes)
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot verify runtime contract copy: {error}") from error
    runtime_contract_digest = hashlib.sha256(runtime_contract_bytes).hexdigest()
    if runtime_contract_digest != config["runtime_contract_sha256"]:
        raise ValueError("runtime contract digest mismatch")
    if runtime_contract_copy != contract:
        raise ValueError("runtime contract copy does not match evaluator config")
    if evaluator_path is not None:
        actual = hashlib.sha256(evaluator_path.read_bytes()).hexdigest()
        if actual != config["evaluator_sha256"]:
            raise ValueError("evaluator script digest mismatch")
        schema_path = Path(runtime_schema_module.__file__)
        schema_actual = hashlib.sha256(schema_path.read_bytes()).hexdigest()
        if schema_actual != config["runtime_schema_sha256"]:
            raise ValueError("runtime schema digest mismatch")
    return config


def _state_expression(contract: dict) -> str:
    names = [contract["state_global"], *contract.get("state_global_aliases", [])]
    sources = " ?? ".join(f"window[{json.dumps(name)}]" for name in names)
    return f"() => {sources} ?? null"


def _state(page: Any, contract: dict) -> object:
    return page.evaluate(_state_expression(contract))


def _visible_controls(page: Any) -> list[dict[str, object]]:
    return page.evaluate(
        """() => [...document.querySelectorAll('*')]
          .map((element) => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            const explicit = element.matches(
              'button,[role="button"],[data-control],[data-action],input[type="button"],'
              + '[aria-label],[tabindex]');
            const touchSurface = style.touchAction === 'none' &&
              rect.width >= 44 && rect.height >= 44 &&
              rect.width <= 320 && rect.height <= 320;
            const centerX = rect.x + rect.width / 2;
            const centerY = rect.y + rect.height / 2;
            const hit = document.elementFromPoint(centerX, centerY);
            const accessibleLabel = [element.getAttribute('aria-label'),
                                     element.getAttribute('title'),
                                     element.textContent]
              .filter(Boolean).join(' ').slice(0, 240);
            const label = [accessibleLabel, element.getAttribute('data-action'), element.id]
              .filter(Boolean).join(' ').slice(0, 240);
            return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2,
                    width: rect.width, height: rect.height, touchSurface,
                    label, accessibleLabel,
                    visible: (explicit || touchSurface) &&
                      style.visibility !== 'hidden' && style.display !== 'none' &&
                      style.pointerEvents !== 'none' && !element.disabled &&
                      hit && (hit === element || element.contains(hit)) &&
                      rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight &&
                      rect.left < innerWidth};
          })
          .filter((item) => item.visible && item.width > 8 && item.height > 8)"""
    )


def _activate_point(page: Any, x: float, y: float, *, mobile: bool) -> None:
    if mobile:
        page.touchscreen.tap(x, y)
    else:
        page.mouse.click(x, y)


def _primary_canvas(page: Any) -> Any:
    canvases = page.locator("canvas:visible")
    index = canvases.evaluate_all(
        """(elements) => {
          let best = -1;
          let bestArea = -1;
          elements.forEach((canvas, index) => {
            const rect = canvas.getBoundingClientRect();
            const area = rect.width * rect.height;
            if (area > bestArea) {
              best = index;
              bestArea = area;
            }
          });
          return best;
        }"""
    )
    if index < 0:
        raise ValueError("page has no visible canvas")
    return canvases.nth(index)


def _start(page: Any, contract: dict, *, mobile: bool) -> None:
    def control_key(control: dict) -> tuple[int, float]:
        label = str(control.get("label", "")).casefold()
        named = any(
            token in label
            for token in (
                "start",
                "play",
                "begin",
                "continue",
                "launch",
                "ready",
                "开始",
                "继续",
                "出发",
            )
        )
        return (0 if named else 1, -(control["width"] * control["height"]))

    controls = sorted(_visible_controls(page), key=control_key)
    for control in controls[:16]:
        _activate_point(page, control["x"], control["y"], mobile=mobile)
        page.wait_for_timeout(250)
        state = _state(page, contract)
        if isinstance(state, dict) and state.get("phase") in contract["started_phases"]:
            return
    if mobile:
        box = _primary_canvas(page).bounding_box()
        if box:
            page.touchscreen.tap(
                box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            )
    else:
        page.keyboard.press("Space")
    page.wait_for_timeout(500)


def _wait_until_playable(page: Any, contract: dict, timeout_ms: int = 6_000) -> object:
    target_phases = set(contract.get("probe_phases") or contract["started_phases"])
    elapsed = 0
    state = _state(page, contract)
    while (
        isinstance(state, dict)
        and state.get("phase") not in target_phases
        and elapsed < timeout_ms
    ):
        page.wait_for_timeout(250)
        elapsed += 250
        state = _state(page, contract)
    return state


def _observation(state: object, paths: list[str]) -> dict[str, object]:
    values: dict[str, object] = {}
    for path in paths:
        found, value = _path_value(state, path)
        values[path] = value if found else "<missing>"
    return values


def _value_delta(before: object, after: object) -> float:
    if _numeric(before) and _numeric(after):
        return abs(float(after) - float(before))
    if isinstance(before, dict) and isinstance(after, dict):
        return math.sqrt(
            sum(
                _value_delta(before.get(key), after.get(key)) ** 2
                for key in set(before) | set(after)
            )
        )
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return float(abs(len(before) - len(after)) + 1)
        return math.sqrt(
            sum(_value_delta(left, right) ** 2 for left, right in zip(before, after))
        )
    return 0.0 if _same_value(before, after) else 1.0


def observation_changed(before: object, after: object, paths: list[str]) -> bool:
    return any(
        before_found
        and after_found
        and _value_delta(before_value, after_value) > 1e-4
        for path in paths
        for before_found, before_value in [_path_value(before, path)]
        for after_found, after_value in [_path_value(after, path)]
    )


def _canvas_signature(page: Any) -> bytes:
    from PIL import Image  # type: ignore[import-not-found]

    shot = _primary_canvas(page).screenshot()
    return Image.open(io.BytesIO(shot)).convert("RGB").resize((48, 48)).tobytes()


def _canvas_delta(before: bytes, after: bytes) -> float:
    if len(before) != len(after) or not before:
        return 1.0
    return sum(abs(left - right) for left, right in zip(before, after)) / (
        len(before) * 255
    )


def _dispatch_touch(
    context: Any,
    page: Any,
    *,
    x: float,
    y: float,
    dx: float,
    dy: float,
    duration_ms: int,
) -> None:
    session = context.new_cdp_session(page)
    try:
        session.send(
            "Input.dispatchTouchEvent",
            {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]},
        )
        first_wait = max(100, duration_ms // 2)
        page.wait_for_timeout(first_wait)
        if dx or dy:
            session.send(
                "Input.dispatchTouchEvent",
                {"type": "touchMove", "touchPoints": [{"x": x + dx, "y": y + dy}]},
            )
        page.wait_for_timeout(max(50, duration_ms - first_wait))
        session.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    finally:
        session.detach()


def _apply_probe_input(
    context: Any, page: Any, recipe: dict, viewport: dict
) -> dict[str, object]:
    input_recipe = recipe["input"]
    input_type = input_recipe["type"]
    duration = input_recipe["duration_ms"]
    if input_type == "keyboard":
        for key in input_recipe["keys"]:
            page.keyboard.down(key)
        page.wait_for_timeout(duration)
        for key in reversed(input_recipe["keys"]):
            page.keyboard.up(key)
        return {"type": input_type, "keys": input_recipe["keys"]}

    box = _primary_canvas(page).bounding_box()
    if not box:
        raise ValueError("probe canvas has no bounding box")
    dx = input_recipe["delta"][0] * box["width"]
    dy = input_recipe["delta"][1] * box["height"]
    if input_type == "pointer":
        gesture = input_recipe["gesture"]
        center_x = box["x"] + box["width"] / 2
        center_y = box["y"] + box["height"] / 2
        if gesture == "edge-pan":
            target_x = box["x"] + (box["width"] - 4 if dx >= 0 else 4)
            target_y = box["y"] + (box["height"] - 4 if dy >= 0 else 4)
            page.mouse.move(target_x, target_y)
            page.wait_for_timeout(duration)
        elif gesture == "lock-move":
            page.mouse.click(center_x, center_y)
            page.wait_for_timeout(100)
            page.mouse.move(center_x + dx, center_y + dy, steps=8)
            page.wait_for_timeout(max(100, duration - 100))
        elif gesture == "discover-look":
            page.mouse.click(center_x, center_y)
            page.wait_for_timeout(100)
            page.mouse.move(center_x + dx / 2, center_y + dy / 2, steps=4)
            page.mouse.down()
            page.mouse.move(center_x + dx, center_y + dy, steps=4)
            page.wait_for_timeout(max(100, duration - 100))
            page.mouse.up()
        else:
            page.mouse.move(center_x, center_y)
            page.mouse.down()
            page.mouse.move(center_x + dx, center_y + dy, steps=8)
            page.wait_for_timeout(duration)
            page.mouse.up()
        return {"type": input_type, "gesture": gesture, "delta": [dx, dy]}

    controls = _visible_controls(page)
    region = input_recipe["control_region"]
    candidates = [item for item in controls if item["y"] >= viewport["height"] * 0.45]
    if region == "left":
        candidates = [item for item in candidates if item["x"] < viewport["width"] / 2]
    elif region == "right":
        candidates = [item for item in candidates if item["x"] >= viewport["width"] / 2]
    elif region == "canvas":
        candidates = []
    if input_recipe["gesture"] == "discover-swipe":
        touch_surfaces = [item for item in candidates if item.get("touchSurface")]
        if touch_surfaces:
            candidates = touch_surfaces
    if candidates:
        target = max(candidates, key=lambda item: (item["height"] * item["width"], item["y"]))
        x, y = target["x"], target["y"]
        discovered = True
    else:
        x_fraction = 0.2 if region == "left" else 0.8 if region == "right" else 0.5
        x = box["x"] + box["width"] * x_fraction
        y = box["y"] + box["height"] * 0.78
        discovered = False
    _dispatch_touch(
        context,
        page,
        x=x,
        y=y,
        dx=dx if input_recipe["gesture"] == "discover-swipe" else 0,
        dy=dy if input_recipe["gesture"] == "discover-swipe" else 0,
        duration_ms=duration,
    )
    return {
        "type": input_type,
        "gesture": input_recipe["gesture"],
        "controlDiscovered": discovered,
    }


def _probe_sample(page: Any, contract: dict, observation: dict) -> tuple[object, object]:
    state = _state(page, contract)
    if observation["type"] == "canvas":
        return _canvas_signature(page), state
    return _observation(state, observation["paths"]), state


def _probe_delta(before: object, after: object, observation: dict) -> float:
    if observation["type"] == "canvas":
        return _canvas_delta(before, after)
    return _value_delta(before, after)


def _state_input_residual(
    before_idle: object, after_idle: object, after_input: object
) -> float:
    if _numeric(before_idle) and _numeric(after_idle) and _numeric(after_input):
        idle_change = float(after_idle) - float(before_idle)
        input_change = float(after_input) - float(after_idle)
        return abs(input_change - idle_change)
    if (
        isinstance(before_idle, dict)
        and isinstance(after_idle, dict)
        and isinstance(after_input, dict)
    ):
        keys = set(before_idle) | set(after_idle) | set(after_input)
        return math.sqrt(
            sum(
                _state_input_residual(
                    before_idle.get(key), after_idle.get(key), after_input.get(key)
                )
                ** 2
                for key in keys
            )
        )
    if (
        isinstance(before_idle, list)
        and isinstance(after_idle, list)
        and isinstance(after_input, list)
        and len(before_idle) == len(after_idle) == len(after_input)
    ):
        return math.sqrt(
            sum(
                _state_input_residual(before, idle, after) ** 2
                for before, idle, after in zip(
                    before_idle, after_idle, after_input
                )
            )
        )
    return 1.0 if _same_value(before_idle, after_idle) and not _same_value(
        after_idle, after_input
    ) else 0.0


def probe_delta_passes(baseline_delta: float, input_delta: float, observation: dict) -> bool:
    return (
        input_delta >= observation["minimum_delta"]
        and input_delta > baseline_delta * observation["baseline_multiplier"]
    )


def probe_residual_passes(
    baseline_delta: float, residual_delta: float, observation: dict
) -> bool:
    return (
        residual_delta >= observation["minimum_delta"]
        and residual_delta
        > baseline_delta * (observation["baseline_multiplier"] - 1)
    )


def _run_probe_once(
    context: Any, page: Any, contract: dict, recipe: dict, viewport: dict
) -> tuple[bool, dict]:
    playable = _wait_until_playable(page, contract)
    if not (
        isinstance(playable, dict)
        and playable.get("phase") in contract["probe_phases"]
        and valid_state(playable, contract)
    ):
        return False, {"error": "game did not reach a declared probe phase", "state": playable}
    observation = recipe["observe"]
    sample_a, state_a = _probe_sample(page, contract, observation)
    page.wait_for_timeout(recipe["baseline_ms"])
    sample_b, state_b = _probe_sample(page, contract, observation)
    action = _apply_probe_input(context, page, recipe, viewport)
    page.wait_for_timeout(100)
    sample_c, state_c = _probe_sample(page, contract, observation)
    baseline_delta = _probe_delta(sample_a, sample_b, observation)
    input_delta = _probe_delta(sample_b, sample_c, observation)
    residual_delta = (
        _state_input_residual(sample_a, sample_b, sample_c)
        if observation["type"] == "state"
        else None
    )
    minimum = observation["minimum_delta"]
    multiplier = observation["baseline_multiplier"]
    errors = state_errors(state_c, contract)
    passed = (
        not state_errors(state_a, contract)
        and not state_errors(state_b, contract)
        and not errors
        and (
            probe_residual_passes(baseline_delta, residual_delta, observation)
            if residual_delta is not None
            else probe_delta_passes(baseline_delta, input_delta, observation)
        )
    )
    return passed, {
        "input": action,
        "observation": observation["type"],
        "paths": observation.get("paths", []),
        "baselineDelta": round(baseline_delta, 6),
        "inputDelta": round(input_delta, 6),
        "inputResidualDelta": (
            round(residual_delta, 6) if residual_delta is not None else None
        ),
        "minimumDelta": minimum,
        "baselineMultiplier": multiplier,
        "stateErrors": errors,
    }


def _run_probe(
    context: Any, page: Any, contract: dict, recipe: dict, viewport: dict
) -> tuple[bool, dict]:
    input_recipe = recipe["input"]
    alternatives = input_recipe.get("key_alternatives")
    if input_recipe["type"] != "keyboard" or not isinstance(alternatives, list):
        return _run_probe_once(context, page, contract, recipe, viewport)

    attempts: list[dict] = []
    for keys in alternatives:
        attempt_recipe = {
            **recipe,
            "input": {
                "type": "keyboard",
                "keys": keys,
                "duration_ms": input_recipe["duration_ms"],
            },
        }
        passed, detail = _run_probe_once(
            context, page, contract, attempt_recipe, viewport
        )
        attempts.append(detail)
        if passed:
            return True, {"matchedKeys": keys, "attempts": attempts}
    return False, {"matchedKeys": None, "attempts": attempts}


def _simulate_visibility_pause(page: Any) -> None:
    page.evaluate(
        """() => {
          Object.defineProperty(document, 'hidden', {configurable: true, value: true});
          Object.defineProperty(document, 'visibilityState',
                                {configurable: true, value: 'hidden'});
          document.dispatchEvent(new Event('visibilitychange'));
          Object.defineProperty(document, 'hidden', {configurable: true, value: false});
          Object.defineProperty(document, 'visibilityState',
                                {configurable: true, value: 'visible'});
          document.dispatchEvent(new Event('visibilitychange'));
          delete document.hidden;
          delete document.visibilityState;
        }"""
    )
    page.wait_for_timeout(200)


def _restart_count_valid(before_count: int, after_count: object, *, required: bool) -> bool:
    if isinstance(after_count, bool) or not isinstance(after_count, int):
        return False
    return after_count == before_count + 1 if required else True


def _restart_control_key(control: dict) -> tuple[int, float]:
    label = str(control.get("accessibleLabel", control.get("label", ""))).casefold()
    restart_named = any(
        token in label
        for token in ("restart", "retry", "again", "reset", "重开", "重试", "再来")
    )
    resume_named = any(
        token in label
        for token in ("resume", "continue", "unpause", "继续", "恢复")
    )
    priority = 0 if restart_named else 1 if resume_named else 2
    return (priority, -(control["width"] * control["height"]))


def _restart(page: Any, contract: dict, before_count: int, *, mobile: bool) -> dict:
    if not mobile:
        page.keyboard.press("KeyR")
        page.wait_for_timeout(250)
        state = _state(page, contract)
        if isinstance(state, dict) and _restart_count_valid(
            before_count,
            state.get("restartCount"),
            required=contract["restart"].get("require_increment", True),
        ):
            return {"sent": True, "method": "keyboard"}
        if contract["restart"].get("desktop_method", "any") == "keyboard":
            return {"sent": False, "method": "keyboard"}
    _simulate_visibility_pause(page)
    state_after_visibility = _state(page, contract)
    visibility_count = (
        state_after_visibility.get("restartCount")
        if isinstance(state_after_visibility, dict)
        else None
    )
    if visibility_count != before_count:
        return {
            "sent": False,
            "method": "visibility-state-changed",
            "before": before_count,
            "after": visibility_count,
        }
    seen: set[tuple[object, ...]] = set()
    for index in range(32):
        state_before_click = _state(page, contract)
        phase = (
            state_before_click.get("phase")
            if isinstance(state_before_click, dict)
            else None
        )
        controls = [
            control
            for control in sorted(_visible_controls(page), key=_restart_control_key)
            if _restart_control_key(control)[0] < 2
        ]
        available: list[tuple[tuple[object, ...], dict]] = []
        for control in controls:
            fingerprint = (
                round(control["x"], 1),
                round(control["y"], 1),
                str(
                    control.get("accessibleLabel", control.get("label", ""))
                ).casefold(),
                phase,
            )
            if fingerprint not in seen:
                available.append((fingerprint, control))
        if not available:
            break
        fingerprint, control = available[0]
        seen.add(fingerprint)
        _activate_point(page, control["x"], control["y"], mobile=mobile)
        page.wait_for_timeout(300)
        state = _state(page, contract)
        if isinstance(state, dict) and _restart_count_valid(
            before_count,
            state.get("restartCount"),
            required=contract["restart"].get("require_increment", True),
        ):
            return {"sent": True, "method": "discovered-control", "index": index}
    if contract["restart"].get("fallback") == "reload":
        page.reload(wait_until="networkidle", timeout=30_000)
        page.wait_for_selector("canvas:visible", timeout=15_000)
        page.wait_for_timeout(250)
        return {"sent": True, "method": "reload"}
    return {"sent": False, "method": "none"}


def _canvas_metrics(page: Any) -> dict:
    return _primary_canvas(page).evaluate(
        """(canvas) => {
          const rect = canvas.getBoundingClientRect();
          return {width: rect.width, height: rect.height,
                  viewportWidth: innerWidth, viewportHeight: innerHeight,
                  overflow: document.documentElement.scrollWidth - innerWidth};
        }"""
    )


def _restart_state_errors(initial: object, restarted: object, contract: dict) -> list[str]:
    errors: list[str] = []
    for match in contract["restart"]["match_initial_paths"]:
        path = match["path"]
        initial_found, initial_value = _path_value(initial, path)
        restarted_found, restarted_value = _path_value(restarted, path)
        if not initial_found or not restarted_found:
            errors.append(f"$.{path}: reset comparison field missing")
            continue
        delta = _value_delta(initial_value, restarted_value)
        if delta > match["tolerance"]:
            errors.append(
                f"$.{path}: reset delta {delta:.6f} exceeds {match['tolerance']}"
            )
    for assertion in contract["restart"]["assertions"]:
        errors.extend(_assertion_errors(restarted, assertion))
    return errors


def _runtime_request_allowed(
    request_url: str, play_url: str, *, is_navigation: bool = False
) -> bool:
    request = urlsplit(request_url)
    if request.scheme in {"data", "blob"}:
        return not is_navigation
    play = urlsplit(play_url)
    return (
        request.scheme == play.scheme
        and request.netloc == play.netloc
        and request.path.startswith(play.path)
    )


def _wait_for_visible_canvas(page: Any, label: str, checks: list[dict]) -> bool:
    try:
        page.wait_for_selector("canvas:visible", timeout=15_000)
    except Exception as error:
        error_type = type(error)
        if error_type.__name__ != "TimeoutError" or not error_type.__module__.startswith(
            "playwright."
        ):
            raise
        checks.append(
            check(
                f"{label}.canvas-visible",
                False,
                "no visible canvas appeared within 15000ms",
            )
        )
        return False
    checks.append(check(f"{label}.canvas-visible", True))
    return True


def _evaluate_viewport(
    browser: Any,
    label: str,
    viewport: dict,
    config: dict,
    url: str,
    checks: list[dict],
    browser_errors: list[str],
    external_requests: list[str],
) -> None:
    contract = config["runtime_contract"]
    enabled = config["checks"]
    mobile = label == "phone"
    context_options: dict[str, object] = {
        "viewport": {"width": viewport["width"], "height": viewport["height"]},
        "is_mobile": mobile,
        "has_touch": mobile,
        "device_scale_factor": 1,
    }
    if mobile:
        context_options["user_agent"] = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Mobile Safari/537.36"
        )
    context = browser.new_context(**context_options)
    try:
        page = context.new_page()
        page.on("pageerror", lambda error: browser_errors.append(f"{label}: {error}"))
        page.on(
            "console",
            lambda message: browser_errors.append(f"{label}: {message.text}")
            if message.type == "error"
            else None,
        )
        page.on(
            "request",
            lambda request: external_requests.append(request.url)
            if not _runtime_request_allowed(
                request.url,
                url,
                is_navigation=request.is_navigation_request(),
            )
            else None,
        )
        page.goto(url, wait_until="networkidle", timeout=30_000)
        if not _wait_for_visible_canvas(page, label, checks):
            return
        state_before = _state(page, contract)
        if enabled["runtime_state"]:
            errors = state_errors(state_before, contract)
            checks.append(
                check(
                    f"{label}.runtime-contract",
                    not errors,
                    {"errors": errors, "state": state_before},
                )
            )
        metrics = _canvas_metrics(page)
        checks.append(
            check(f"{label}.no-horizontal-overflow", metrics["overflow"] <= 2, metrics)
        )
        page.screenshot(path=str(OUTPUT / f"{label}.png"), full_page=False)
        if enabled["canvas_nonblank"]:
            from PIL import Image, ImageStat  # type: ignore[import-not-found]

            canvas_shot = _primary_canvas(page).screenshot()
            image = Image.open(io.BytesIO(canvas_shot)).convert("RGB").resize((64, 64))
            variance = sum(ImageStat.Stat(image).var)
            checks.append(check(f"{label}.nonblank", variance > 30, round(variance, 2)))

        _start(page, contract, mobile=mobile)
        state_started = _state(page, contract)
        started = (
            isinstance(state_started, dict)
            and state_started.get("phase") in contract["started_phases"]
            and valid_state(state_started, contract)
        )
        checks.append(check(f"{label}.starts", started, state_started))
        for recipe in contract["probes"][label]:
            input_type = recipe["input"]["type"]
            if input_type == "keyboard" and not enabled["keyboard_input"]:
                continue
            if input_type in {"pointer", "touch"} and not enabled[
                "pointer_or_touch_input"
            ]:
                continue
            probe_passed, detail = _run_probe(
                context, page, contract, recipe, viewport
            )
            checks.append(
                check(f"{label}.probe.{recipe['id']}", probe_passed, detail)
            )

        if enabled["resize"]:
            state_pre_resize = _state(page, contract)
            resized = {
                "width": max(320, viewport["width"] - 73),
                "height": max(480, viewport["height"] - 61),
            }
            page.set_viewport_size(resized)
            page.wait_for_timeout(300)
            state_post_resize = _state(page, contract)
            resized_metrics = _canvas_metrics(page)
            same_run = (
                isinstance(state_pre_resize, dict)
                and isinstance(state_post_resize, dict)
                and state_pre_resize.get("restartCount")
                == state_post_resize.get("restartCount")
            )
            resize_passed = (
                valid_state(state_post_resize, contract)
                and same_run
                and resized_metrics["width"] > 0
                and resized_metrics["height"] > 0
                and resized_metrics["width"] <= resized_metrics["viewportWidth"] + 2
                and resized_metrics["height"] <= resized_metrics["viewportHeight"] + 2
                and resized_metrics["overflow"] <= 2
            )
            checks.append(
                check(
                    f"{label}.resizes-in-place",
                    resize_passed,
                    {"viewport": resized, "canvas": resized_metrics, "sameRun": same_run},
                )
            )
            page.set_viewport_size(
                {"width": viewport["width"], "height": viewport["height"]}
            )
            page.wait_for_timeout(200)

        if enabled["restart"]:
            state_pre_restart = _state(page, contract)
            before_count = (
                state_pre_restart.get("restartCount")
                if isinstance(state_pre_restart, dict)
                else None
            )
            action = (
                _restart(page, contract, before_count, mobile=mobile)
                if isinstance(before_count, int) and not isinstance(before_count, bool)
                else {"sent": False, "method": "invalid-before-state"}
            )
            page.wait_for_timeout(250)
            state_post_restart = _state(page, contract)
            after_count = (
                state_post_restart.get("restartCount")
                if isinstance(state_post_restart, dict)
                else None
            )
            reset_errors = _restart_state_errors(
                state_before, state_post_restart, contract
            )
            restarted = (
                action["sent"]
                and isinstance(before_count, int)
                and not isinstance(before_count, bool)
                and _restart_count_valid(
                    before_count,
                    after_count,
                    required=contract["restart"].get("require_increment", True),
                )
                and valid_state(state_post_restart, contract)
                and not reset_errors
            )
            checks.append(
                check(
                    f"{label}.restart",
                    restarted,
                    {
                        "action": action,
                        "before": before_count,
                        "after": after_count,
                        "resetErrors": reset_errors,
                        "state": state_post_restart,
                    },
                )
            )
    finally:
        context.close()


def _write_report(report: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(
        json.dumps(_json_safe(report), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=OUTPUT / "evaluator-contract.json")
    args = parser.parse_args(argv)
    checks: list[dict] = [check("build", True)]
    try:
        config = load_evaluator_config(args.contract, Path(__file__))
    except Exception as error:  # noqa: BLE001 - emit a trusted fail-closed report
        report = {
            "schema_version": 1,
            "trusted": False,
            "passed": False,
            "build": {"passed": True, "exit_code": 0},
            "infrastructure_errors": [repr(error)],
            "checks": checks + [check("evaluator-contract", False, repr(error))],
        }
        _write_report(report)
        return 1

    checks.append(check("evaluator-contract", True, {"taskId": config["task_id"]}))
    render_evidence = {
        "render_source_sha256": config["render_source_sha256"],
        "post_build_render_source_sha256": config[
            "post_build_render_source_sha256"
        ],
        "render_source_unchanged": config["render_source_unchanged"],
        "render_dist_sha256": config["render_dist_sha256"],
    }
    checks.append(
        check(
            "render-source-unchanged",
            config["render_source_unchanged"],
            render_evidence,
        )
    )
    if not config["render_source_unchanged"]:
        report = {
            "schema_version": 1,
            "task_id": config["task_id"],
            "trusted": True,
            "passed": False,
            "build": {"passed": True, "exit_code": 0},
            "evaluator": {
                "runtime_contract_sha256": config["runtime_contract_sha256"],
                "script_sha256": config["evaluator_sha256"],
                "runtime_schema_sha256": config["runtime_schema_sha256"],
                "render_source_sha256": config["render_source_sha256"],
            },
            "evidence": render_evidence,
            "checks": checks,
        }
        _write_report(report)
        return 1
    play_path = f"/playground/{config['task_id']}/candidate/"
    handler = functools.partial(
        ProductionRouteHandler,
        directory=SUBMISSION,
        mount_path=play_path,
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}{play_path}"
    browser_errors: list[str] = []
    external_requests: list[str] = []
    infrastructure_errors: list[str] = []
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--use-gl=angle",
                    "--use-angle=swiftshader",
                    "--enable-unsafe-swiftshader",
                ],
            )
            for label in ("desktop", "phone"):
                try:
                    _evaluate_viewport(
                        browser,
                        label,
                        config["runtime_contract"]["viewports"][label],
                        config,
                        url,
                        checks,
                        browser_errors,
                        external_requests,
                    )
                except Exception as error:  # noqa: BLE001 - preserve per-viewport evidence
                    infrastructure_errors.append(f"{label}: {error!r}")
                    checks.append(check(f"{label}.evaluator-completed", False, repr(error)))
            browser.close()
    except Exception as error:  # noqa: BLE001 - report evaluator failures as evidence
        infrastructure_errors.append(repr(error))
        checks.append(check("evaluator-completed", False, repr(error)))
    finally:
        server.shutdown()
        server.server_close()

    checks.append(check("no-page-errors", not browser_errors, browser_errors))
    checks.append(check("no-runtime-network", not external_requests, external_requests))
    report = {
        "schema_version": 1,
        "task_id": config["task_id"],
        "trusted": not infrastructure_errors,
        "passed": not infrastructure_errors and all(item["passed"] for item in checks),
        "infrastructure_errors": infrastructure_errors,
        "build": {"passed": True, "exit_code": 0},
        "evaluator": {
            "runtime_contract_sha256": config["runtime_contract_sha256"],
            "script_sha256": config["evaluator_sha256"],
            "runtime_schema_sha256": config["runtime_schema_sha256"],
            "render_source_sha256": config["render_source_sha256"],
        },
        "evidence": render_evidence,
        "checks": checks,
    }
    _write_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
