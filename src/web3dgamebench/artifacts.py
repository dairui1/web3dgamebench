from __future__ import annotations

import hashlib
import re
from pathlib import Path

_ROOT_ASSET_URL = re.compile(r'(?P<attribute>\b(?:src|href)=["\'])/assets/')


def file_tree_sha256(root: Path, *, excluded: frozenset[str] = frozenset()) -> str:
    """Return a stable digest of a file tree, excluding named path components."""

    digest = hashlib.sha256()
    paths: list[Path] = []
    for path in sorted(root.rglob("*")):
        relative_parts = path.relative_to(root).parts
        if excluded.intersection(relative_parts):
            continue
        if path.is_symlink():
            raise ValueError(f"file tree must not contain symbolic links: {path}")
        if path.is_file():
            paths.append(path)
    for path in paths:
        file_digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                file_digest.update(chunk)
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(file_digest.digest())
    return digest.hexdigest()


def candidate_workspace_sha256(root: Path) -> str:
    """Freeze every candidate-authored workspace file except installed dependencies."""

    return file_tree_sha256(root, excluded=frozenset({"node_modules"}))


def normalize_playable_bundle(destination: Path) -> int:
    """Make Vite asset URLs route-relative before evaluation and digesting."""

    changed = 0
    for html_path in destination.rglob("*.html"):
        html = html_path.read_text(encoding="utf-8")
        rewritten = _ROOT_ASSET_URL.sub(r"\g<attribute>./assets/", html)
        if rewritten != html:
            html_path.write_text(rewritten, encoding="utf-8")
            changed += 1
    return changed
