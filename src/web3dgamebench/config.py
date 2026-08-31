from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


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


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    season: str
    root: Path
    starter: Path
    brief: Path


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
    return {
        season_id: Season(
            id=season_id,
            status=str(value["status"]),
            tasks=tuple(value["tasks"]),
            profiles=tuple(value["profiles"]),
            attempts=int(value.get("attempts", 1)),
        )
        for season_id, value in raw.items()
    }


def load_task(root: Path, task_id: str) -> Task:
    task_root = root / "tasks" / task_id / "task"
    raw = _toml(task_root / "task.toml")
    if raw.get("id") != task_id:
        raise ConfigError(f"task id mismatch in {task_root / 'task.toml'}")
    starter = task_root / str(raw["starter"])
    brief = task_root / str(raw["brief"])
    if not starter.is_dir() or not brief.is_file():
        raise ConfigError(f"task {task_id} is missing its starter or brief")
    return Task(
        id=task_id,
        title=str(raw["title"]),
        season=str(raw["season"]),
        root=task_root,
        starter=starter,
        brief=brief,
    )


def validate_matrix(root: Path, season_id: str) -> tuple[Season, dict[str, Profile]]:
    seasons = load_seasons(root)
    profiles = load_profiles(root)
    if season_id not in seasons:
        raise ConfigError(f"unknown season: {season_id}")
    season = seasons[season_id]
    missing = [profile for profile in season.profiles if profile not in profiles]
    if missing:
        raise ConfigError(f"season references unknown profiles: {', '.join(missing)}")
    for task_id in season.tasks:
        task = load_task(root, task_id)
        if task.season != season.id:
            raise ConfigError(f"task {task.id} belongs to {task.season}, not {season.id}")
    return season, profiles
