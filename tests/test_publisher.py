import json
import tomllib
from pathlib import Path

import pytest

import web3dgamebench.publisher as publisher_module
from web3dgamebench.evaluator import render_dist_sha256, render_source_sha256
from web3dgamebench.publisher import PublishError, publish_runs


def test_publish_copies_source_dist_and_updates_catalog(tmp_path: Path) -> None:
    root = tmp_path / "bench"
    games = tmp_path / "games"
    workspace = tmp_path / "run/workspace"
    render = tmp_path / "run/render"
    dist = render / "dist"
    (root / "site/public/data").mkdir(parents=True)
    (root / "configs").mkdir()
    (root / "configs/pricing.toml").write_text(
        '[pricing]\ncurrency = "USD"\nunit_tokens = 1000000\nas_of = "2026-08-31"\n'
        "[models.model]\ninput = 2\ncached_input = 0.2\noutput = 10\n"
        'source = "https://example.com/pricing"\nsource_label = "Official pricing"\n'
    )
    workspace.mkdir(parents=True)
    dist.mkdir(parents=True)
    (workspace / "src.ts").write_text("mutable workspace")
    (workspace / "TASK.md").write_text("sealed until close")
    (render / "src.ts").write_text("evaluated source")
    (dist / "index.html").write_text(
        '<link rel="stylesheet" href="./assets/game.css">'
        '<script type="module" src="./assets/game.js"></script>'
    )
    catalog = {
        "generatedAt": "old",
        "season": {"id": "test", "status": "private-running"},
        "tasks": [{"id": "task", "titleZh": "信号漂移", "submissions": []}],
    }
    (root / "site/public/data/catalog.json").write_text(json.dumps(catalog))
    manifest = {
        "status": "candidate-complete",
        "task": {"id": "task"},
        "profile": {"id": "profile", "harness": "codex", "model": "model"},
        "workspace": str(workspace),
    }
    manifest["run_id"] = "run-task-profile"
    manifest["duration_seconds"] = 12.5
    manifest["trace_format"] = "codex-jsonl-v1"
    manifest["repair"] = {
        "assisted": True,
        "attempt": 1,
        "penalty_points": 100,
        "source_run_id": "original-run",
    }
    (tmp_path / "run/manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "run/events.jsonl").write_text(
        json.dumps({"type": "thread.started", "thread_id": "thread"})
        + "\n"
        + json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "one", "type": "agent_message", "text": "Starting work"},
            }
        )
        + "\n"
    )
    (tmp_path / "run/evaluation").mkdir()
    (tmp_path / "run/evaluation/report.json").write_text(
        json.dumps(
            {
                "trusted": True,
                "passed": True,
                "build": {"passed": True},
                "checks": [
                    {"name": "build", "passed": True},
                    {"name": "desktop.canvas-visible", "passed": True},
                    {"name": "desktop.nonblank", "passed": True},
                    {"name": "desktop.starts", "passed": True},
                ],
                "evaluator": {"render_source_sha256": render_source_sha256(render)},
                "evidence": {
                    "render_source_sha256": render_source_sha256(render),
                    "post_build_render_source_sha256": render_source_sha256(render),
                    "render_source_unchanged": True,
                    "render_dist_sha256": render_dist_sha256(dist),
                },
            }
        )
    )

    publish_runs(root, [tmp_path / "run"], games)

    assert (games / "games/task/profile/src.ts").read_text() == "evaluated source"
    assert not (games / "games/task/profile/TASK.md").exists()
    assert (root / "site/public/playground/task/profile/index.html").read_text() == (
        '<link rel="stylesheet" href="./assets/game.css">'
        '<script type="module" src="./assets/game.js"></script>'
    )
    updated = json.loads((root / "site/public/data/catalog.json").read_text())
    assert updated["tasks"][0]["submissions"][0]["playUrl"] == "/playground/task/profile/"
    submission = updated["tasks"][0]["submissions"][0]
    assert submission["traceId"] == "run-task-profile"
    assert submission["replayUrl"] == "/replay/run-task-profile"
    assert submission["officialApiCost"]["total"] == 0
    assert submission["officialApiCost"]["source"] == "https://example.com/pricing"
    assert submission["repair"] == {
        "assisted": True,
        "attempt": 1,
        "penaltyPoints": 100,
        "sourceRunId": "original-run",
    }
    assert "assisted-repair" in submission["notices"]
    replay = json.loads(
        (root / "site/public/data/traces/run-task-profile.json").read_text()
    )
    assert replay["events"][0]["title"] == "Agent update"
    assert "信号漂移" in (root / "site/public/data/catalog.json").read_text()


def test_season_one_run_requires_closed_matrix(tmp_path: Path) -> None:
    root = tmp_path / "bench"
    games = tmp_path / "games"
    run = tmp_path / "run"
    (root / "site/public/data").mkdir(parents=True)
    (root / "configs").mkdir()
    (root / "configs/pricing.toml").write_text(
        '[pricing]\ncurrency = "USD"\nunit_tokens = 1000000\nas_of = "2026-08-31"\n'
    )
    (root / "site/public/data/catalog.json").write_text(
        json.dumps(
            {
                "season": {"id": "season-1", "status": "private-running"},
                "tasks": [{"id": "first-night", "submissions": []}],
            }
        )
    )
    run.mkdir()
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "status": "candidate-complete",
                "task": {"id": "first-night"},
                "profile": {"id": "profile"},
            }
        )
    )
    (run / "evaluation").mkdir()
    (run / "evaluation/report.json").write_text(
        json.dumps({"trusted": True, "passed": True})
    )
    with pytest.raises(PublishError, match="closed matrix receipt"):
        publish_runs(root, [run], games)


def test_matrix_publication_requires_exact_playable_run_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "bench"
    (root / "site/public/data").mkdir(parents=True)
    (root / "configs").mkdir()
    (root / "configs/pricing.toml").write_text(
        '[pricing]\ncurrency = "USD"\nunit_tokens = 1000000\nas_of = "2026-08-31"\n'
    )
    (root / "site/public/data/catalog.json").write_text(
        json.dumps(
            {
                "season": {"id": "season-1", "status": "private-running"},
                "tasks": [],
            }
        )
    )
    expected = tmp_path / "expected-run"
    receipt = {
        "season": "season-1",
        "cells": [
            {
                "run": str(expected),
                "playable": True,
                "trusted": True,
                "task": "first-night",
                "profile": "profile",
                "attempt": 1,
            }
        ],
    }
    monkeypatch.setattr(
        publisher_module,
        "validate_publication_receipt",
        lambda _root, value: (value, {}),
    )

    with pytest.raises(PublishError, match="exactly match all playable cells"):
        publish_runs(
            root,
            [tmp_path / "different-run"],
            tmp_path / "games",
            matrix_receipt=receipt,
        )


def test_publish_rejects_render_modified_after_evaluation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    render = tmp_path / "run/render"
    (render / "dist").mkdir(parents=True)
    (render / "src.ts").write_text("evaluated")
    digest = render_source_sha256(render)
    (render / "src.ts").write_text("modified later")
    evaluation = {
        "evaluator": {"render_source_sha256": digest},
        "evidence": {
            "post_build_render_source_sha256": digest,
            "render_source_unchanged": True,
            "render_dist_sha256": render_dist_sha256(render / "dist"),
        },
    }

    with pytest.raises(PublishError, match="changed after admission"):
        publisher_module._verify_render_evidence(tmp_path / "run", evaluation)


def test_frozen_season_one_catalog_matches_the_matrix_task_order() -> None:
    catalog = json.loads(
        (Path(__file__).resolve().parents[1] / "configs/catalogs/season-1.json").read_text(
            encoding="utf-8"
        )
    )
    seasons = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "configs/seasons.toml").read_text(
            encoding="utf-8"
        )
    )["seasons"]

    assert catalog["schema_version"] == 1
    assert catalog["season"]["id"] == "season-1"
    assert [task["id"] for task in catalog["tasks"]] == seasons["season-1"]["tasks"]
    assert all(task["titleZh"] and task["summaryZh"] for task in catalog["tasks"])

    current = {
        "schema_version": 1,
        "season": {"id": "season-1"},
        "tasks": [
            {
                "id": task_id,
                "title": "drifted",
                "submissions": (
                    [{"profileId": "existing", "id": "existing-submission"}]
                    if index == 0
                    else []
                ),
            }
            for index, task_id in enumerate(seasons["season-1"]["tasks"])
        ],
    }
    selected = publisher_module._publication_catalog(
        Path(__file__).resolve().parents[1],
        current,
        "season-1",
        {"season": {"tasks": seasons["season-1"]["tasks"]}},
    )
    assert selected["tasks"][0]["title"] == catalog["tasks"][0]["title"]
    assert selected["tasks"][0]["submissions"] == [
        {"profileId": "existing", "id": "existing-submission"}
    ]
