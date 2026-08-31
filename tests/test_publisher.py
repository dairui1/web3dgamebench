import json
from pathlib import Path

from web3dgamebench.publisher import publish_runs


def test_publish_copies_source_dist_and_updates_catalog(tmp_path: Path) -> None:
    root = tmp_path / "bench"
    games = tmp_path / "games"
    workspace = tmp_path / "run/workspace"
    dist = tmp_path / "run/render/dist"
    (root / "site/public/data").mkdir(parents=True)
    workspace.mkdir(parents=True)
    dist.mkdir(parents=True)
    (workspace / "src.ts").write_text("source")
    (workspace / "TASK.md").write_text("sealed until close")
    (dist / "index.html").write_text(
        '<link rel="stylesheet" href="/assets/game.css">'
        '<script type="module" src="/assets/game.js"></script>'
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
    (tmp_path / "run/manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "run/evaluation").mkdir()
    (tmp_path / "run/evaluation/report.json").write_text(
        json.dumps({"trusted": True, "passed": True})
    )

    publish_runs(root, [tmp_path / "run"], games)

    assert (games / "games/task/profile/src.ts").read_text() == "source"
    assert not (games / "games/task/profile/TASK.md").exists()
    assert (root / "site/public/playground/task/profile/index.html").read_text() == (
        '<link rel="stylesheet" href="./assets/game.css">'
        '<script type="module" src="./assets/game.js"></script>'
    )
    updated = json.loads((root / "site/public/data/catalog.json").read_text())
    assert updated["tasks"][0]["submissions"][0]["playUrl"] == "/playground/task/profile/"
    assert "信号漂移" in (root / "site/public/data/catalog.json").read_text()
