from __future__ import annotations

import tomllib
from pathlib import Path

from web3dgamebench.config import load_task

ROOT = Path(__file__).resolve().parents[1]
SEASON_ONE_TASKS = (
    "canyon-strike",
    "bombsite-retake",
    "first-night",
    "village-quest",
    "ashen-duel",
    "linked-chamber",
    "star-course",
    "turbo-circuit",
    "frontier-command",
    "dinner-rush",
)


def _raw_task(task_id: str) -> tuple[Path, dict]:
    task_root = ROOT / "tasks" / task_id / "task"
    raw = tomllib.loads((task_root / "task.toml").read_text(encoding="utf-8"))
    return task_root, raw


def test_season_one_has_ten_distinct_ready_tasks() -> None:
    assert len(SEASON_ONE_TASKS) == 10
    assert len(set(SEASON_ONE_TASKS)) == 10

    seeds: set[int] = set()
    references: set[str] = set()
    for task_id in SEASON_ONE_TASKS:
        task_root, raw = _raw_task(task_id)
        task = load_task(ROOT, task_id)

        assert task.id == task_id
        assert task.season == "season-1"
        assert task.status == "ready"
        assert raw["status"] == "ready"
        assert raw["goal"] == {
            "mode": "external-goal",
            "completion": "contract-and-evidence",
        }
        assert task.brief == task_root / "goal.en.md"
        assert (task_root / raw["review_brief"]).is_file()
        seeds.add(raw["seed"])
        references.add(raw["reference_archetype"])

    assert len(seeds) == len(SEASON_ONE_TASKS)
    assert len(references) == len(SEASON_ONE_TASKS)


def test_goal_prompts_are_bilingual_single_paragraph_user_requests() -> None:
    for task_id in SEASON_ONE_TASKS:
        task_root, raw = _raw_task(task_id)
        english = (task_root / raw["brief"]).read_text(encoding="utf-8")
        chinese = (task_root / raw["review_brief"]).read_text(encoding="utf-8")

        assert english.startswith(f"# {raw['title']}\n\n")
        assert chinese.startswith(f"# {raw['title']} / ")
        assert len(english.strip().splitlines()) == 3
        assert len(chinese.strip().splitlines()) == 3
        assert 55 <= len(english.split()) <= 110
        assert "Three.js" in english and "Three.js" in chinese
        assert raw["reference_archetype"] in english
        assert "/goal" not in english
        assert "npm run build" not in english
        assert "window.__WEB3DGAMEBENCH__" not in english
        assert "1440 x 900" not in english
        assert "执行检查点" not in chinese


def test_season_one_tasks_are_in_the_ready_runnable_season() -> None:
    seasons = tomllib.loads(
        (ROOT / "configs" / "seasons.toml").read_text(encoding="utf-8")
    )["seasons"]
    season = seasons["season-1"]
    assert season["status"] == "ready"
    assert tuple(season["tasks"]) == SEASON_ONE_TASKS
