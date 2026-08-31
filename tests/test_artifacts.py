from pathlib import Path

import pytest

from web3dgamebench.artifacts import candidate_workspace_sha256, normalize_playable_bundle


def test_playable_bundle_is_normalized_before_evaluation_and_publication(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    index = dist / "index.html"
    index.write_text(
        '<script src="/assets/game.js"></script>'
        '<link href="/assets/game.css" rel="stylesheet">',
        encoding="utf-8",
    )

    assert normalize_playable_bundle(dist) == 1
    normalized = index.read_text(encoding="utf-8")
    assert 'src="./assets/game.js"' in normalized
    assert 'href="./assets/game.css"' in normalized
    assert normalize_playable_bundle(dist) == 0


def test_candidate_workspace_digest_tracks_outputs_but_ignores_dependencies(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/main.ts").write_text("source", encoding="utf-8")
    original = candidate_workspace_sha256(tmp_path)

    (tmp_path / "node_modules/pkg").mkdir(parents=True)
    (tmp_path / "node_modules/pkg/index.js").write_text("installed", encoding="utf-8")
    assert candidate_workspace_sha256(tmp_path) == original

    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/index.html").write_text("built", encoding="utf-8")
    assert candidate_workspace_sha256(tmp_path) != original


def test_candidate_workspace_digest_rejects_symbolic_links(tmp_path: Path) -> None:
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "escape.txt").symlink_to(tmp_path / "outside.txt")

    with pytest.raises(ValueError, match="symbolic links"):
        candidate_workspace_sha256(workspace)
