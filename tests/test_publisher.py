import json
from pathlib import Path

from aetherplay.publisher import publish_runs


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
    (dist / "index.html").write_text("game")
    catalog = {"generatedAt": "old", "tasks": [{"id": "task", "submissions": []}]}
    (root / "site/public/data/catalog.json").write_text(json.dumps(catalog))
    manifest = {
        "task": {"id": "task"},
        "profile": {"id": "profile", "harness": "codex", "model": "model"},
        "workspace": str(workspace),
        "evaluation": {"trusted": True, "passed": True},
    }
    (tmp_path / "run/manifest.json").write_text(json.dumps(manifest))

    publish_runs(root, [tmp_path / "run"], games)

    assert (games / "games/task/profile/src.ts").read_text() == "source"
    assert not (games / "games/task/profile/TASK.md").exists()
    assert (root / "site/public/playground/task/profile/index.html").read_text() == "game"
    updated = json.loads((root / "site/public/data/catalog.json").read_text())
    assert updated["tasks"][0]["submissions"][0]["playUrl"] == "/playground/task/profile/"
