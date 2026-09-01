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


def test_goal_contracts_are_bilingual_and_external_goal_safe() -> None:
    english_sections = (
        "## Objective",
        "## Operational completion contract",
        "## Target game systems",
        "## Execution checkpoints",
        "## Quality targets",
        "## Runtime inspection contract",
        "## Constraints and final evidence",
    )
    chinese_sections = (
        "## 目标",
        "## 运行完成合同",
        "## 目标游戏系统",
        "## 执行检查点",
        "## 质量目标",
        "## 运行时检查合同",
        "## 约束与最终证据",
    )

    for task_id in SEASON_ONE_TASKS:
        task_root, raw = _raw_task(task_id)
        english = (task_root / raw["brief"]).read_text(encoding="utf-8")
        chinese = (task_root / raw["review_brief"]).read_text(encoding="utf-8")

        assert "/goal" not in english
        assert all(section in english for section in english_sections)
        assert all(section in chinese for section in chinese_sections)
        assert "window.__WEB3DGAMEBENCH__" in english
        assert "window.__WEB3DGAMEBENCH__" in chinese
        assert "schema-valid from the first rendered frame" in english
        assert "`R` must restart immediately" in english
        assert "从首个渲染帧起" in chinese
        assert "按 `R` 必须立即重新开始" in chinese
        assert "1440 x 900" in english and "390 x 844" in english
        assert "1440 x 900" in chinese and "390 x 844" in chinese
        assert "horizontal page overflow stays within 2 CSS pixels" in english
        assert "`console.error`" in english
        assert "whose text, `aria-label`, or title identifies it as Restart" in english
        assert "横向溢出都不得超过 2 个 CSS 像素" in chinese
        assert "`console.error`" in chinese
        assert "`aria-label`" in chinese
        assert "npm run build" in english and "npm run build" in chinese
        assert "Do not create an autopilot" in english
        assert "Full win/loss or end-to-end playthrough evidence is neither required" in english
        assert "不要为了证明完成而编写自动驾驶器" in chinese
        assert "无需也不要求提供完整胜负或端到端通关证据" in chinese


def test_season_one_operational_completion_contract_is_uniform() -> None:
    english_contracts: set[str] = set()
    chinese_contracts: set[str] = set()

    for task_id in SEASON_ONE_TASKS:
        task_root, raw = _raw_task(task_id)
        english = (task_root / raw["brief"]).read_text(encoding="utf-8")
        chinese = (task_root / raw["review_brief"]).read_text(encoding="utf-8")
        english_contracts.add(
            english.split("## Operational completion contract", 1)[1].split(
                "## Target game systems", 1
            )[0].strip()
        )
        chinese_contracts.add(
            chinese.split("## 运行完成合同", 1)[1].split("## 目标游戏系统", 1)[0].strip()
        )

    assert len(english_contracts) == 1
    assert len(chinese_contracts) == 1


def test_season_one_goals_do_not_require_end_to_end_self_play() -> None:
    forbidden_english = (
        "complete loop has been played",
        "played at both required viewports",
        "Build and play complete",
        "Build and solve the full",
        "Build and finish full",
        "verified winning run",
    )
    forbidden_chinese = (
        "完整试玩了",
        "分别试玩了完整",
        "完整解谜结果",
        "完整比赛试玩结果",
        "经验证的获胜流程",
    )

    for task_id in SEASON_ONE_TASKS:
        task_root, raw = _raw_task(task_id)
        english = (task_root / raw["brief"]).read_text(encoding="utf-8")
        chinese = (task_root / raw["review_brief"]).read_text(encoding="utf-8")
        assert not any(phrase in english for phrase in forbidden_english)
        assert not any(phrase in chinese for phrase in forbidden_chinese)


def test_season_one_tasks_are_in_the_ready_runnable_season() -> None:
    seasons = tomllib.loads(
        (ROOT / "configs" / "seasons.toml").read_text(encoding="utf-8")
    )["seasons"]
    season = seasons["season-1"]
    assert season["status"] == "ready"
    assert tuple(season["tasks"]) == SEASON_ONE_TASKS
