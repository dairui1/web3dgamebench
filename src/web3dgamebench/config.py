from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    id: str
    harness: str
    model: str
    effort: str | None
    provider: str | None
    credential_env: str | None
    runtime_env: str | None


@dataclass(frozen=True)
class Season:
    id: str
    status: str
    tasks: tuple[str, ...]
    profiles: tuple[str, ...]
    attempts: int
    publish_prompts_after_close: bool


@dataclass(frozen=True)
class GoalConfig:
    mode: str
    completion: str


@dataclass(frozen=True)
class Viewport:
    width: int
    height: int


@dataclass(frozen=True)
class TaskChecks:
    build: bool
    canvas_nonblank: bool
    keyboard_input: bool
    pointer_or_touch_input: bool
    restart: bool
    resize: bool
    runtime_state: bool

    def as_dict(self) -> dict[str, bool]:
        return {
            "build": self.build,
            "canvas_nonblank": self.canvas_nonblank,
            "keyboard_input": self.keyboard_input,
            "pointer_or_touch_input": self.pointer_or_touch_input,
            "restart": self.restart,
            "resize": self.resize,
            "runtime_state": self.runtime_state,
        }


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    season: str
    status: str
    framework: str
    seed: int
    root: Path
    starter: Path
    brief: Path
    review_brief: Path | None
    reference_archetype: str | None
    goal: GoalConfig | None
    viewports: Mapping[str, Viewport]
    checks: TaskChecks

    @property
    def goal_mode(self) -> str | None:
        return self.goal.mode if self.goal else None

    @property
    def goal_completion(self) -> str | None:
        return self.goal.completion if self.goal else None


@dataclass(frozen=True)
class JudgeProfile:
    id: str
    harness: str
    provider: str
    model: str
    effort: str
    runs: int


def _toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigError(f"missing configuration: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {path}: {error}") from error


def _mapping(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be a TOML table")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{field} must be an integer >= {minimum}")
    return value


def _task_path(task_root: Path, value: object, field: str) -> Path:
    relative = Path(_string(value, field))
    if relative.is_absolute() or ".." in relative.parts:
        raise ConfigError(f"{field} must stay inside the task directory")
    return task_root / relative


def _load_goal(raw: object, task_id: str) -> GoalConfig | None:
    if raw is None:
        return None
    goal = _mapping(raw, f"task {task_id} goal")
    expected = {"mode", "completion"}
    if set(goal) != expected:
        raise ConfigError(
            f"task {task_id} goal must contain exactly: {', '.join(sorted(expected))}"
        )
    return GoalConfig(
        mode=_string(goal["mode"], f"task {task_id} goal.mode"),
        completion=_string(goal["completion"], f"task {task_id} goal.completion"),
    )


def _load_viewports(raw: object, task_id: str) -> Mapping[str, Viewport]:
    viewports = _mapping(raw, f"task {task_id} viewport")
    expected = {"desktop", "phone"}
    if set(viewports) != expected:
        raise ConfigError(
            f"task {task_id} viewport must contain exactly: {', '.join(sorted(expected))}"
        )
    parsed: dict[str, Viewport] = {}
    for label in sorted(expected):
        viewport = _mapping(viewports[label], f"task {task_id} viewport.{label}")
        if set(viewport) != {"width", "height"}:
            raise ConfigError(
                f"task {task_id} viewport.{label} must contain exactly width and height"
            )
        parsed[label] = Viewport(
            width=_integer(
                viewport["width"], f"task {task_id} viewport.{label}.width", minimum=1
            ),
            height=_integer(
                viewport["height"], f"task {task_id} viewport.{label}.height", minimum=1
            ),
        )
    return MappingProxyType(parsed)


def _load_checks(raw: object, task_id: str) -> TaskChecks:
    checks = _mapping(raw, f"task {task_id} checks")
    expected = set(TaskChecks.__dataclass_fields__)
    if set(checks) != expected:
        missing = sorted(expected - set(checks))
        unknown = sorted(set(checks) - expected)
        detail = []
        if missing:
            detail.append(f"missing {', '.join(missing)}")
        if unknown:
            detail.append(f"unknown {', '.join(unknown)}")
        raise ConfigError(f"task {task_id} checks are invalid: {'; '.join(detail)}")
    invalid = sorted(name for name, value in checks.items() if not isinstance(value, bool))
    if invalid:
        raise ConfigError(f"task {task_id} checks must be booleans: {', '.join(invalid)}")
    return TaskChecks(**checks)


def load_profiles(root: Path) -> dict[str, Profile]:
    raw = _toml(root / "configs" / "profiles.toml").get("profiles", {})
    profiles: dict[str, Profile] = {}
    for profile_id, value in raw.items():
        profiles[profile_id] = Profile(
            id=profile_id,
            harness=str(value["harness"]),
            model=str(value["model"]),
            effort=value.get("effort"),
            provider=value.get("provider"),
            credential_env=value.get("credential_env"),
            runtime_env=value.get("runtime_env"),
        )
    return profiles


def load_judges(root: Path) -> dict[str, JudgeProfile]:
    raw = _toml(root / "configs" / "judges.toml").get("judges", {})
    judges: dict[str, JudgeProfile] = {}
    for judge_id, value in raw.items():
        runs = int(value.get("runs", 1))
        if runs < 1:
            raise ConfigError(f"judge {judge_id} must run at least once")
        judges[judge_id] = JudgeProfile(
            id=judge_id,
            harness=str(value["harness"]),
            provider=str(value["provider"]),
            model=str(value["model"]),
            effort=str(value["effort"]),
            runs=runs,
        )
    return judges


def load_seasons(root: Path) -> dict[str, Season]:
    raw = _toml(root / "configs" / "seasons.toml").get("seasons", {})
    seasons: dict[str, Season] = {}
    for season_id, value in raw.items():
        publish_after_close = value.get("publish_prompts_after_close", False)
        if not isinstance(publish_after_close, bool):
            raise ConfigError(
                f"season {season_id} publish_prompts_after_close must be a boolean"
            )
        seasons[season_id] = Season(
            id=season_id,
            status=str(value["status"]),
            tasks=tuple(value["tasks"]),
            profiles=tuple(value["profiles"]),
            attempts=int(value.get("attempts", 1)),
            publish_prompts_after_close=publish_after_close,
        )
    return seasons


def load_task(root: Path, task_id: str) -> Task:
    task_root = root / "tasks" / task_id / "task"
    raw = _toml(task_root / "task.toml")
    if raw.get("id") != task_id:
        raise ConfigError(f"task id mismatch in {task_root / 'task.toml'}")
    starter = _task_path(task_root, raw.get("starter"), f"task {task_id} starter")
    brief = _task_path(task_root, raw.get("brief"), f"task {task_id} brief")
    if not starter.is_dir() or not brief.is_file():
        raise ConfigError(f"task {task_id} is missing its starter or brief")
    review_brief = None
    if "review_brief" in raw:
        review_brief = _task_path(
            task_root, raw["review_brief"], f"task {task_id} review_brief"
        )
        if not review_brief.is_file():
            raise ConfigError(f"task {task_id} is missing its review brief")
    return Task(
        id=task_id,
        title=_string(raw.get("title"), f"task {task_id} title"),
        season=_string(raw.get("season"), f"task {task_id} season"),
        status=_string(raw.get("status", "active"), f"task {task_id} status"),
        framework=_string(raw.get("framework"), f"task {task_id} framework"),
        seed=_integer(raw.get("seed"), f"task {task_id} seed"),
        root=task_root,
        starter=starter,
        brief=brief,
        review_brief=review_brief,
        reference_archetype=(
            _string(raw["reference_archetype"], f"task {task_id} reference_archetype")
            if "reference_archetype" in raw
            else None
        ),
        goal=_load_goal(raw.get("goal"), task_id),
        viewports=_load_viewports(raw.get("viewport"), task_id),
        checks=_load_checks(raw.get("checks"), task_id),
    )


def validate_matrix(root: Path, season_id: str) -> tuple[Season, dict[str, Profile]]:
    from .judge import validate_judge_assets
    from .runtime_contracts import RuntimeContractError, load_runtime_contract

    seasons = load_seasons(root)
    profiles = load_profiles(root)
    if season_id not in seasons:
        raise ConfigError(f"unknown season: {season_id}")
    season = seasons[season_id]
    missing = [profile for profile in season.profiles if profile not in profiles]
    if missing:
        raise ConfigError(f"season references unknown profiles: {', '.join(missing)}")
    if season.id == "season-1" and season.status != "ready":
        raise ConfigError("season-1 must be ready before planning paid runs")
    for task_id in season.tasks:
        task = load_task(root, task_id)
        if task.season != season.id:
            raise ConfigError(f"task {task.id} belongs to {task.season}, not {season.id}")
        if season.id == "season-1":
            if task.status != "ready":
                raise ConfigError(f"season-1 task {task.id} is not ready")
            if task.goal != GoalConfig(
                mode="external-goal", completion="contract-and-evidence"
            ):
                raise ConfigError(f"season-1 task {task.id} has incomplete goal metadata")
            viewports = {
                label: {"width": viewport.width, "height": viewport.height}
                for label, viewport in task.viewports.items()
            }
            try:
                load_runtime_contract(
                    root, task_id=task.id, seed=task.seed, viewports=viewports
                )
            except RuntimeContractError as error:
                raise ConfigError(str(error)) from error
            try:
                validate_judge_assets(root, task.id)
            except ValueError as error:
                raise ConfigError(f"invalid judge assets for task {task.id}: {error}") from error
    return season, profiles
