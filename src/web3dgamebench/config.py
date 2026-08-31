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
    timeout_seconds: int
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
    time_limit_seconds: int


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
            timeout_seconds=int(value.get("timeout_seconds", 3600)),
            credential_env=value.get("credential_env"),
            runtime_env=value.get("runtime_env"),
        )
    return profiles


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
        time_limit_seconds=int(raw.get("time_limit_seconds", 3600)),
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
