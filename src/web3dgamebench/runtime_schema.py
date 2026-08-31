from __future__ import annotations

import math
from typing import Any


class RuntimeSchemaError(ValueError):
    pass


_SCALAR_TYPES = {"number", "integer", "boolean", "string", "string-or-null", "enum"}
_ALL_TYPES = _SCALAR_TYPES | {"object", "array", "vec3"}


def _numeric(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _same_value(left: object, right: object) -> bool:
    return type(left) is type(right) and bool(left == right)


def _literal_matches_schema(value: object, schema: dict) -> bool:
    kind = schema["type"]
    if kind == "number":
        valid = _numeric(value)
    elif kind == "integer":
        valid = not isinstance(value, bool) and isinstance(value, int)
    elif kind == "boolean":
        valid = isinstance(value, bool)
    elif kind == "string":
        valid = isinstance(value, str)
    elif kind == "string-or-null":
        valid = value is None or isinstance(value, str)
    elif kind == "enum":
        valid = any(_same_value(value, item) for item in schema["values"])
    else:
        return False
    if not valid:
        return False
    if "minimum" in schema and (not _numeric(value) or value < schema["minimum"]):
        return False
    if "maximum" in schema and (not _numeric(value) or value > schema["maximum"]):
        return False
    return "enum" not in schema or any(
        _same_value(value, item) for item in schema["enum"]
    )


def _validate_schema(schema: object, path: str) -> dict:
    if not isinstance(schema, dict):
        raise RuntimeSchemaError(f"{path} must be an object")
    kind = schema.get("type")
    if kind not in _ALL_TYPES:
        raise RuntimeSchemaError(f"{path}.type is unsupported: {kind!r}")
    common = {"type"}
    if kind == "object":
        allowed = common | {"required"}
        required = schema.get("required")
        if not isinstance(required, dict) or not required:
            raise RuntimeSchemaError(f"{path}.required must be a non-empty object")
        for name, child in required.items():
            if not isinstance(name, str) or not name:
                raise RuntimeSchemaError(f"{path}.required contains an invalid field name")
            _validate_schema(child, f"{path}.required.{name}")
    elif kind == "array":
        allowed = common | {"length", "items"}
        length = schema.get("length")
        if isinstance(length, bool) or not isinstance(length, int) or length < 1:
            raise RuntimeSchemaError(f"{path}.length must be a positive integer")
        _validate_schema(schema.get("items"), f"{path}.items")
    elif kind == "vec3":
        allowed = common
    elif kind == "enum":
        allowed = common | {"values"}
        values = schema.get("values")
        if not isinstance(values, list) or not values:
            raise RuntimeSchemaError(f"{path}.values must be a non-empty array")
        if any(isinstance(item, (dict, list)) for item in values):
            raise RuntimeSchemaError(f"{path}.values must contain only scalar JSON values")
    else:
        allowed = common | {"const", "enum", "minimum", "maximum"}
        if "enum" in schema and (
            not isinstance(schema["enum"], list) or not schema["enum"]
        ):
            raise RuntimeSchemaError(f"{path}.enum must be a non-empty array")
        for bound in ("minimum", "maximum"):
            if bound in schema and not _numeric(schema[bound]):
                raise RuntimeSchemaError(f"{path}.{bound} must be finite")
        if (
            "minimum" in schema
            and "maximum" in schema
            and schema["minimum"] > schema["maximum"]
        ):
            raise RuntimeSchemaError(f"{path} has inverted numeric bounds")
        for literal_name in ("const",):
            if literal_name in schema and not _literal_matches_schema(
                schema[literal_name], {key: value for key, value in schema.items() if key != "const"}
            ):
                raise RuntimeSchemaError(f"{path}.{literal_name} does not match its schema")
        if "enum" in schema and any(
            not _literal_matches_schema(
                item, {key: value for key, value in schema.items() if key != "enum"}
            )
            for item in schema["enum"]
        ):
            raise RuntimeSchemaError(f"{path}.enum contains a value of the wrong type")
    unknown = set(schema) - allowed
    if unknown:
        raise RuntimeSchemaError(f"{path} has unknown keys: {', '.join(sorted(unknown))}")
    return schema


def _schema_at_path(root: dict, dotted_path: object, context: str) -> dict:
    if not isinstance(dotted_path, str) or not dotted_path:
        raise RuntimeSchemaError(f"{context}.path must be a non-empty string")
    schema = root
    for part in dotted_path.split("."):
        if schema.get("type") == "vec3" and part in "xyz" and len(part) == 1:
            schema = {"type": "number"}
            continue
        if schema.get("type") != "object" or part not in schema["required"]:
            raise RuntimeSchemaError(f"{context}.path does not name a required field")
        schema = schema["required"][part]
    return schema


def _validate_invariants(invariants: object, state_schema: dict, task_id: str) -> None:
    if not isinstance(invariants, list):
        raise RuntimeSchemaError(f"runtime contract {task_id} invariants must be an array")
    for index, invariant in enumerate(invariants):
        prefix = f"runtime contract {task_id} invariant {index}"
        if not isinstance(invariant, dict) or set(invariant) != {"when", "assert"}:
            raise RuntimeSchemaError(f"{prefix} must contain exactly when and assert")
        condition = invariant["when"]
        if not isinstance(condition, dict) or set(condition) != {"path", "equals"}:
            raise RuntimeSchemaError(f"{prefix}.when must contain exactly path and equals")
        condition_schema = _schema_at_path(state_schema, condition["path"], f"{prefix}.when")
        if not _literal_matches_schema(condition["equals"], condition_schema):
            raise RuntimeSchemaError(f"{prefix}.when.equals does not match the field schema")
        assertions = invariant["assert"]
        if not isinstance(assertions, list) or not assertions:
            raise RuntimeSchemaError(f"{prefix}.assert must be a non-empty array")
        for assertion_index, assertion in enumerate(assertions):
            assertion_prefix = f"{prefix}.assert[{assertion_index}]"
            if not isinstance(assertion, dict) or not isinstance(assertion.get("path"), str):
                raise RuntimeSchemaError(f"{assertion_prefix} must contain a path")
            operators = set(assertion) - {"path"}
            if not operators or not operators.issubset(
                {"equals", "minimum", "maximum", "one_of"}
            ):
                raise RuntimeSchemaError(f"{assertion_prefix} has invalid operators")
            assertion_schema = _schema_at_path(
                state_schema, assertion["path"], assertion_prefix
            )
            if "equals" in assertion and not _literal_matches_schema(
                assertion["equals"], assertion_schema
            ):
                raise RuntimeSchemaError(
                    f"{assertion_prefix}.equals does not match the field schema"
                )
            for operator in ("minimum", "maximum"):
                if operator in assertion and (
                    assertion_schema["type"] not in {"number", "integer"}
                    or not _numeric(assertion[operator])
                ):
                    raise RuntimeSchemaError(
                        f"{assertion_prefix}.{operator} requires a numeric field and value"
                    )
            if "one_of" in assertion and (
                not isinstance(assertion["one_of"], list)
                or not assertion["one_of"]
                or any(
                    not _literal_matches_schema(item, assertion_schema)
                    for item in assertion["one_of"]
                )
            ):
                raise RuntimeSchemaError(
                    f"{assertion_prefix}.one_of does not match the field schema"
                )


def _positive_milliseconds(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 100 or value > 10_000:
        raise RuntimeSchemaError(f"{path} must be an integer from 100 to 10000")
    return value


def _finite_non_negative(value: object, path: str) -> float:
    if not _numeric(value) or value < 0:
        raise RuntimeSchemaError(f"{path} must be a non-negative finite number")
    return float(value)


def _validate_probe_input(value: object, *, platform: str, path: str) -> str:
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise RuntimeSchemaError(f"{path} must be an input object")
    input_type = value["type"]
    if input_type == "keyboard":
        if platform != "desktop" or set(value) not in (
            {"type", "keys", "duration_ms"},
            {"type", "key_alternatives", "duration_ms"},
        ):
            raise RuntimeSchemaError(f"{path} has an invalid keyboard recipe")
        alternatives = (
            value["key_alternatives"]
            if "key_alternatives" in value
            else [value["keys"]]
        )
        if (
            not isinstance(alternatives, list)
            or not alternatives
            or any(
                not isinstance(keys, list)
                or not keys
                or any(not isinstance(key, str) or not key for key in keys)
                for keys in alternatives
            )
        ):
            raise RuntimeSchemaError(
                f"{path} keyboard alternatives must contain non-empty key arrays"
            )
    elif input_type == "pointer":
        if platform != "desktop" or set(value) != {
            "type",
            "gesture",
            "duration_ms",
            "delta",
        }:
            raise RuntimeSchemaError(f"{path} has an invalid pointer recipe")
        if value["gesture"] not in {
            "drag",
            "lock-move",
            "discover-look",
            "edge-pan",
        }:
            raise RuntimeSchemaError(f"{path}.gesture is unsupported")
        delta = value["delta"]
        if (
            not isinstance(delta, list)
            or len(delta) != 2
            or any(not _numeric(item) or abs(item) > 1 for item in delta)
        ):
            raise RuntimeSchemaError(f"{path}.delta must be two normalized numbers")
    elif input_type == "touch":
        if platform != "phone" or set(value) != {
            "type",
            "gesture",
            "duration_ms",
            "delta",
            "control_region",
        }:
            raise RuntimeSchemaError(f"{path} has an invalid touch recipe")
        if value["gesture"] not in {"discover-hold", "discover-swipe"}:
            raise RuntimeSchemaError(f"{path}.gesture is unsupported")
        if value["control_region"] not in {"left", "right", "any", "canvas"}:
            raise RuntimeSchemaError(f"{path}.control_region is unsupported")
        delta = value["delta"]
        if (
            not isinstance(delta, list)
            or len(delta) != 2
            or any(not _numeric(item) or abs(item) > 1 for item in delta)
        ):
            raise RuntimeSchemaError(f"{path}.delta must be two normalized numbers")
    else:
        raise RuntimeSchemaError(f"{path}.type is unsupported: {input_type!r}")
    _positive_milliseconds(value["duration_ms"], f"{path}.duration_ms")
    return input_type


def _validate_probe_observation(value: object, state_schema: dict, path: str) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise RuntimeSchemaError(f"{path} must be an observation object")
    observation_type = value["type"]
    if observation_type == "state":
        if set(value) != {"type", "paths", "minimum_delta", "baseline_multiplier"}:
            raise RuntimeSchemaError(f"{path} has an invalid state observation")
        paths = value["paths"]
        if not isinstance(paths, list) or not paths:
            raise RuntimeSchemaError(f"{path}.paths must be a non-empty array")
        for index, state_path in enumerate(paths):
            _schema_at_path(state_schema, state_path, f"{path}.paths[{index}]")
    elif observation_type == "canvas":
        if set(value) != {"type", "minimum_delta", "baseline_multiplier"}:
            raise RuntimeSchemaError(f"{path} has an invalid canvas observation")
    else:
        raise RuntimeSchemaError(f"{path}.type is unsupported: {observation_type!r}")
    _finite_non_negative(value["minimum_delta"], f"{path}.minimum_delta")
    multiplier = value["baseline_multiplier"]
    if not _numeric(multiplier) or multiplier < 1:
        raise RuntimeSchemaError(f"{path}.baseline_multiplier must be finite and >= 1")


def _validate_probes(value: object, state_schema: dict, task_id: str) -> None:
    if not isinstance(value, dict) or set(value) != {"desktop", "phone"}:
        raise RuntimeSchemaError(
            f"runtime contract {task_id} probes must define desktop and phone"
        )
    seen_ids: set[str] = set()
    input_types: set[str] = set()
    for platform in ("desktop", "phone"):
        recipes = value[platform]
        if not isinstance(recipes, list) or not recipes:
            raise RuntimeSchemaError(
                f"runtime contract {task_id} probes.{platform} must be non-empty"
            )
        for index, recipe in enumerate(recipes):
            path = f"runtime contract {task_id}.probes.{platform}[{index}]"
            if not isinstance(recipe, dict) or set(recipe) != {
                "id",
                "baseline_ms",
                "input",
                "observe",
            }:
                raise RuntimeSchemaError(f"{path} has an invalid recipe shape")
            probe_id = recipe["id"]
            if not isinstance(probe_id, str) or not probe_id or probe_id in seen_ids:
                raise RuntimeSchemaError(f"{path}.id must be unique and non-empty")
            seen_ids.add(probe_id)
            _positive_milliseconds(recipe["baseline_ms"], f"{path}.baseline_ms")
            input_types.add(
                _validate_probe_input(recipe["input"], platform=platform, path=f"{path}.input")
            )
            _validate_probe_observation(recipe["observe"], state_schema, f"{path}.observe")
    if "keyboard" not in input_types or "touch" not in input_types:
        raise RuntimeSchemaError(
            f"runtime contract {task_id} needs separate keyboard and touch probes"
        )


def _validate_restart(value: object, state_schema: dict, task_id: str) -> None:
    required = {"match_initial_paths", "assertions"}
    optional = {"fallback", "require_increment", "desktop_method"}
    if (
        not isinstance(value, dict)
        or not required.issubset(value)
        or set(value) - required - optional
    ):
        raise RuntimeSchemaError(f"runtime contract {task_id} restart recipe is invalid")
    if value.get("fallback", "none") not in {"none", "reload"}:
        raise RuntimeSchemaError(
            f"runtime contract {task_id} restart.fallback is unsupported"
        )
    if value.get("desktop_method", "any") not in {"any", "keyboard"}:
        raise RuntimeSchemaError(
            f"runtime contract {task_id} restart.desktop_method is unsupported"
        )
    if not isinstance(value.get("require_increment", True), bool):
        raise RuntimeSchemaError(
            f"runtime contract {task_id} restart.require_increment must be boolean"
        )
    paths = value["match_initial_paths"]
    if not isinstance(paths, list) or not paths:
        raise RuntimeSchemaError(
            f"runtime contract {task_id} restart.match_initial_paths must be non-empty"
        )
    for index, match in enumerate(paths):
        if not isinstance(match, dict) or set(match) != {"path", "tolerance"}:
            raise RuntimeSchemaError(
                f"runtime contract {task_id}.restart.match_initial_paths[{index}] is invalid"
            )
        _finite_non_negative(
            match["tolerance"],
            f"runtime contract {task_id}.restart.match_initial_paths[{index}].tolerance",
        )
        _schema_at_path(
            state_schema,
            match["path"],
            f"runtime contract {task_id}.restart.match_initial_paths[{index}]",
        )
    _validate_invariants(
        [{"when": {"path": "restartCount", "equals": 0}, "assert": value["assertions"]}],
        state_schema,
        f"{task_id} restart",
    )


def validate_runtime_contract_definition(contract: object) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise RuntimeSchemaError("runtime contract must be an object")
    expected = {
        "schema_version",
        "task_id",
        "seed",
        "viewports",
        "state_global",
        "started_phases",
        "probe_phases",
        "observation_paths",
        "probes",
        "restart",
        "state_schema",
        "invariants",
    }
    optional = {"state_global_aliases"}
    if not expected.issubset(contract) or set(contract) - expected - optional:
        raise RuntimeSchemaError("runtime contract has missing or unknown top-level fields")
    if contract["schema_version"] != 1:
        raise RuntimeSchemaError("unsupported runtime contract schema")
    task_id = contract["task_id"]
    if not isinstance(task_id, str) or not task_id:
        raise RuntimeSchemaError("runtime contract has no task_id")
    seed = contract["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise RuntimeSchemaError(f"runtime contract {task_id} has invalid seed")
    viewports = contract["viewports"]
    if not isinstance(viewports, dict) or set(viewports) != {"desktop", "phone"}:
        raise RuntimeSchemaError(
            f"runtime contract {task_id} must define desktop and phone viewports"
        )
    for label, viewport in viewports.items():
        if not isinstance(viewport, dict) or set(viewport) != {"width", "height"}:
            raise RuntimeSchemaError(
                f"runtime contract {task_id} has malformed {label} viewport"
            )
        if any(
            isinstance(viewport[name], bool)
            or not isinstance(viewport[name], int)
            or viewport[name] < 1
            for name in ("width", "height")
        ):
            raise RuntimeSchemaError(
                f"runtime contract {task_id} has invalid {label} viewport"
            )
    if contract["state_global"] != "__WEB3DGAMEBENCH__":
        raise RuntimeSchemaError(f"runtime contract {task_id} has invalid state global")
    aliases = contract.get("state_global_aliases", [])
    if (
        not isinstance(aliases, list)
        or any(
            not isinstance(alias, str)
            or not alias
            or alias == contract["state_global"]
            for alias in aliases
        )
        or len(set(aliases)) != len(aliases)
    ):
        raise RuntimeSchemaError(
            f"runtime contract {task_id} has invalid state global aliases"
        )
    state_schema = _validate_schema(
        contract["state_schema"], f"runtime contract {task_id}.state_schema"
    )
    if state_schema["type"] != "object":
        raise RuntimeSchemaError(f"runtime contract {task_id} state schema must be an object")
    required = state_schema["required"]
    common_fields = {"phase", "score", "seed", "restartCount"}
    if not common_fields.issubset(required):
        raise RuntimeSchemaError(f"runtime contract {task_id} lacks common state fields")
    phase_schema = required["phase"]
    phases = phase_schema.get("enum") if phase_schema.get("type") == "string" else None
    started = contract["started_phases"]
    if (
        not isinstance(phases, list)
        or not isinstance(started, list)
        or not started
        or any(not isinstance(phase, str) or phase not in phases for phase in started)
    ):
        raise RuntimeSchemaError(f"runtime contract {task_id} has invalid started phases")
    probe_phases = contract["probe_phases"]
    if (
        not isinstance(probe_phases, list)
        or not probe_phases
        or any(not isinstance(phase, str) or phase not in phases for phase in probe_phases)
    ):
        raise RuntimeSchemaError(f"runtime contract {task_id} has invalid probe phases")
    seed_schema = required["seed"]
    if seed_schema.get("type") != "integer" or seed_schema.get("const") != seed:
        raise RuntimeSchemaError(
            f"runtime contract {task_id} state seed does not match metadata"
        )
    observations = contract["observation_paths"]
    if not isinstance(observations, list) or not observations:
        raise RuntimeSchemaError(
            f"runtime contract {task_id} has no input observation paths"
        )
    for index, path in enumerate(observations):
        _schema_at_path(state_schema, path, f"runtime contract {task_id}.observation[{index}]")
    _validate_probes(contract["probes"], state_schema, task_id)
    _validate_restart(contract["restart"], state_schema, task_id)
    _validate_invariants(contract["invariants"], state_schema, task_id)
    return contract
