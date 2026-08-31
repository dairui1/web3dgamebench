import functools
import http.server
import json
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import web3dgamebench.judge as judge_module
from web3dgamebench.cli import build_parser
from web3dgamebench.evaluator import render_dist_sha256
from web3dgamebench.judge import (
    QuietHandler,
    _write_json_once,
    inspect_judge_report,
    judges_dir,
    resolve_judge_source,
    run_judge,
    validate_judge_assets,
)

ROOT = Path(__file__).resolve().parents[1]


TASK_IDS = {
    "signal-drift",
    "ashen-duel",
    "bombsite-retake",
    "canyon-strike",
    "dinner-rush",
    "first-night",
    "frontier-command",
    "linked-chamber",
    "star-course",
    "turbo-circuit",
    "village-quest",
}


def _write_trusted_evaluation(
    run_root: Path,
    task_id: str,
    *,
    trusted: bool = True,
    passed: bool = True,
) -> Path:
    evaluation_path = run_root / "evaluation/report.json"
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "task_id": task_id,
                "trusted": trusted,
                "passed": passed,
                "evidence": {
                    "render_dist_sha256": render_dist_sha256(run_root / "render/dist")
                },
            }
        )
    )
    return evaluation_path


def test_all_task_rubrics_match_their_prompts() -> None:
    rubric_ids = {path.stem for path in (ROOT / "infra/judge/rubrics").glob("*.json")}
    prompt_ids = {path.stem for path in (ROOT / "infra/judge/prompts").glob("*.md")}
    assert rubric_ids == TASK_IDS
    assert prompt_ids == TASK_IDS
    for task_id in sorted(TASK_IDS):
        rubric = validate_judge_assets(ROOT, task_id)
        prompt = (ROOT / f"infra/judge/prompts/{task_id}.md").read_text()
        assert rubric["schema_version"] == 2
        assert rubric["task_id"] == task_id
        assert rubric["minimum_evidence_coverage"] >= 70
        assert rubric["viewports"] == {
            "desktop": {"width": 1440, "height": 900, "mobile": False},
            "phone": {"width": 390, "height": 844, "mobile": True},
        }
        assert set(rubric["budgets"]) == {
            "observations",
            "input_actions",
            "wait_actions",
            "total_wait_ms",
            "max_wait_ms",
            "max_input_duration_ms",
        }
        assert sum(item["weight"] for item in rubric["criteria"]) == 100
        assert len({item["id"] for item in rubric["criteria"]}) == len(rubric["criteria"])
        assert all(
            item["evidence_requirement"] in {"visual", "interaction", "either"}
            for item in rubric["criteria"]
        )
        assert "390 x 844" in prompt
        assert "Runtime" in prompt


def test_long_tasks_have_larger_but_bounded_playtest_budgets() -> None:
    for task_id in ("dinner-rush", "first-night", "frontier-command", "turbo-circuit"):
        budgets = validate_judge_assets(ROOT, task_id)["budgets"]
        assert budgets["observations"] >= 64
        assert budgets["input_actions"] >= 220
        assert budgets["total_wait_ms"] >= 360_000
        assert budgets["total_wait_ms"] <= 600_000
        assert budgets["max_wait_ms"] <= 30_000


def test_preflight_rejects_missing_runtime_budget(tmp_path: Path) -> None:
    rubric = validate_judge_assets(ROOT, "first-night")
    rubric["budgets"] = dict(rubric["budgets"])
    del rubric["budgets"]["wait_actions"]
    prompt_dir = tmp_path / "infra/judge/prompts"
    rubric_dir = tmp_path / "infra/judge/rubrics"
    prompt_dir.mkdir(parents=True)
    rubric_dir.mkdir(parents=True)
    (prompt_dir / "first-night.md").write_text(
        (ROOT / "infra/judge/prompts/first-night.md").read_text()
    )
    (rubric_dir / "first-night.json").write_text(json.dumps(rubric))
    with pytest.raises(ValueError, match="budgets"):
        validate_judge_assets(tmp_path, "first-night")


def test_first_night_and_linked_chamber_require_spatial_evidence() -> None:
    first_night = validate_judge_assets(ROOT, "first-night")
    shelter = next(
        item for item in first_night["criteria"] if item["id"] == "shelter.spatial"
    )
    assert "visibly construct" in shelter["description"]
    assert "shelterValid" in shelter["description"]

    linked = validate_judge_assets(ROOT, "linked-chamber")
    traversal = next(
        item for item in linked["criteria"] if item["id"] == "portals.traversal"
    )
    cube = next(item for item in linked["criteria"] if item["id"] == "cube.traversal")
    assert "differently oriented surface normals" in traversal["description"]
    assert "transported through a portal" in cube["description"]


def test_canyon_strike_requires_extraction_after_targets() -> None:
    rubric = validate_judge_assets(ROOT, "canyon-strike")
    mission = next(item for item in rubric["criteria"] if item["id"] == "mission.causality")
    assert "then visibly flying through the extraction gate" in mission["description"]
    assert "must not auto-win" in mission["description"]


def test_new_task_discriminators_are_required_by_judge_rubrics() -> None:
    village = validate_judge_assets(ROOT, "village-quest")
    village_combat = next(
        item for item in village["criteria"] if item["id"] == "combat.abilities"
    )
    assert "two enemy roles" in village_combat["description"]
    assert "improve survival" in village_combat["description"]
    assert "two enemy roles" in (ROOT / "infra/judge/prompts/village-quest.md").read_text()

    star = validate_judge_assets(ROOT, "star-course")
    star_text = " ".join(item["description"] for item in star["criteria"])
    assert "requires at least one actual moving-platform transfer" in star_text
    assert "no more than seven" in star_text
    assert "required on the victory route" in star_text
    star_prompt = (ROOT / "infra/judge/prompts/star-course.md").read_text()
    assert "moving-platform transfer" in star_prompt
    assert "at most seven coins" in star_prompt

    turbo = validate_judge_assets(ROOT, "turbo-circuit")
    turbo_text = " ".join(item["description"] for item in turbo["criteria"])
    assert "idle or no-drift player" in turbo_text
    assert "Both boost and slow-field items" in turbo_text
    turbo_prompt = (ROOT / "infra/judge/prompts/turbo-circuit.md").read_text()
    assert "idle or no-drift" in turbo_prompt
    assert "both boost and slow-field" in turbo_prompt


def test_report_state_distinguishes_terminal_from_sufficient_coverage() -> None:
    insufficient = inspect_judge_report(
        {
            "schema_version": 2,
            "task_id": "first-night",
            "status": "insufficient-evidence",
            "evidence_coverage": 65,
            "minimum_evidence_coverage": 70,
            "meets_minimum_evidence_coverage": False,
        },
        expected_task_id="first-night",
    )
    assert insufficient.valid
    assert insufficient.terminal
    assert not insufficient.coverage_sufficient
    assert not insufficient.usable

    complete = inspect_judge_report(
        {
            "schema_version": 2,
            "task_id": "first-night",
            "status": "complete",
            "evidence_coverage": 70,
            "minimum_evidence_coverage": 70,
            "meets_minimum_evidence_coverage": True,
        },
        expected_task_id="first-night",
    )
    assert complete.valid
    assert complete.terminal
    assert complete.coverage_sufficient
    assert complete.usable

    dishonest = inspect_judge_report(
        {
            "schema_version": 2,
            "task_id": "first-night",
            "status": "complete",
            "evidence_coverage": 65,
            "minimum_evidence_coverage": 70,
            "meets_minimum_evidence_coverage": False,
        }
    )
    assert not dishonest.valid
    assert not dishonest.terminal


def test_private_run_source_uses_render_dist_without_touching_workspace(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "private-run"
    dist = run_root / "render/dist"
    workspace = run_root / "workspace"
    dist.mkdir(parents=True)
    workspace.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>private</title>")
    marker = workspace / "candidate.ts"
    marker.write_text("const untouched = true")
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-first-night-a1",
                "task": {"id": "first-night"},
                "profile": {"id": "codex-sol-medium"},
            }
        )
    )
    evaluation_path = _write_trusted_evaluation(run_root, "first-night")

    source = resolve_judge_source(ROOT, "first-night", run_root=run_root)

    assert source.kind == "private-run"
    assert source.id == "run-first-night-a1"
    assert source.game_root == dist.resolve()
    assert marker.read_text() == "const untouched = true"
    assert source.metadata["evaluation_report"] == str(evaluation_path)
    assert source.metadata["render_dist_sha256"] == render_dist_sha256(dist)
    assert source.metadata["profile_id"] == "codex-sol-medium"


def test_private_run_rejects_workspace_build_and_task_mismatch(tmp_path: Path) -> None:
    run_root = tmp_path / "private-run"
    (run_root / "workspace/dist").mkdir(parents=True)
    (run_root / "workspace/dist/index.html").write_text("not an immutable render")
    (run_root / "manifest.json").write_text(
        json.dumps({"run_id": "run-wrong", "task": {"id": "star-course"}})
    )
    with pytest.raises(ValueError, match="task mismatch"):
        resolve_judge_source(ROOT, "first-night", run_root=run_root)

    (run_root / "manifest.json").write_text(
        json.dumps({"run_id": "run-first-night", "task": {"id": "first-night"}})
    )
    with pytest.raises(ValueError, match="static game build not found"):
        resolve_judge_source(ROOT, "first-night", run_root=run_root)


@pytest.mark.parametrize(
    ("trusted", "passed"),
    [(False, True), (True, False)],
)
def test_private_run_requires_trusted_passing_evaluation(
    tmp_path: Path, trusted: bool, passed: bool
) -> None:
    run_root = tmp_path / "private-run"
    dist = run_root / "render/dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>private</title>")
    (run_root / "manifest.json").write_text(
        json.dumps({"run_id": "run-first-night", "task": {"id": "first-night"}})
    )
    _write_trusted_evaluation(run_root, "first-night", trusted=trusted, passed=passed)

    with pytest.raises(ValueError, match="must be trusted and passing"):
        resolve_judge_source(ROOT, "first-night", run_root=run_root)


def test_private_run_requires_evaluation_and_rejects_dist_drift(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "private-run"
    dist = run_root / "render/dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>private</title>")
    (run_root / "manifest.json").write_text(
        json.dumps({"run_id": "run-first-night", "task": {"id": "first-night"}})
    )

    with pytest.raises(ValueError, match="evaluation report not found"):
        resolve_judge_source(ROOT, "first-night", run_root=run_root)

    _write_trusted_evaluation(run_root, "first-night")
    (dist / "index.html").write_text("<!doctype html><title>mutated</title>")
    with pytest.raises(ValueError, match="changed after evaluation"):
        resolve_judge_source(ROOT, "first-night", run_root=run_root)


def test_explicit_dist_source_has_content_derived_id(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>private</title>")
    first = resolve_judge_source(ROOT, "first-night", dist_path=dist)
    second = resolve_judge_source(ROOT, "first-night", dist_path=dist)
    assert first.kind == "private-dist"
    assert first.id.startswith("dist-")
    assert first.id == second.id


def test_published_source_and_ids_cannot_escape_playground(tmp_path: Path) -> None:
    game = tmp_path / "site/public/playground/first-night/submission-1"
    game.mkdir(parents=True)
    (game / "index.html").write_text("<!doctype html>")
    source = resolve_judge_source(tmp_path, "first-night", submission_id="submission-1")
    assert source.kind == "published-submission"
    assert source.game_root == game.resolve()
    with pytest.raises(ValueError, match="submission id"):
        resolve_judge_source(tmp_path, "first-night", submission_id="../../private")


def test_static_source_rejects_symlinks(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>")
    (tmp_path / "secret.txt").write_text("secret")
    (dist / "escape.txt").symlink_to(tmp_path / "secret.txt")
    with pytest.raises(ValueError, match="symbolic links"):
        resolve_judge_source(ROOT, "first-night", dist_path=dist)


def test_judge_cli_requires_exactly_one_source() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["judge", "--task", "first-night", "--run", "/tmp/private-run"]
    )
    assert args.run == "/tmp/private-run"
    assert args.submission is None
    assert args.dist is None
    with pytest.raises(SystemExit):
        parser.parse_args(["judge", "--task", "first-night"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "judge",
                "--task",
                "first-night",
                "--submission",
                "published",
                "--dist",
                "/tmp/dist",
            ]
        )


def test_judge_outputs_live_in_state_and_manifest_is_write_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert judges_dir() == tmp_path / ".local/state/web3dgamebench/judges"
    manifest = tmp_path / "manifest.json"
    _write_json_once(manifest, {"status": "complete"})
    with pytest.raises(FileExistsError):
        _write_json_once(manifest, {"status": "changed"})
    assert json.loads(manifest.read_text()) == {"status": "complete"}


def test_run_manifest_uses_insufficient_report_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>judge fixture</title>")
    state_root = tmp_path / "judge-state"
    monkeypatch.setattr(judge_module, "judges_dir", lambda: state_root)
    monkeypatch.setattr(judge_module, "_chromium", lambda: Path("/bin/false"))
    monkeypatch.setattr(judge_module, "_pi_version", lambda: "test-pi")
    monkeypatch.setattr(judge_module.shutil, "which", lambda _name: "/fake/pi")

    def fake_pi(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        output = Path(environment["W3GB_JUDGE_OUTPUT"])
        rubric = validate_judge_assets(ROOT, "first-night")
        report = {
            "schema_version": 2,
            "task_id": "first-night",
            "status": "insufficient-evidence",
            "provisional_score": 40,
            "evidence_coverage": 65,
            "minimum_evidence_coverage": 70,
            "meets_minimum_evidence_coverage": False,
            "criteria": rubric["criteria"],
        }
        (output / "judge-report.json").write_text(json.dumps(report))
        stdout = json.dumps({"type": "message_start", "message": {"model": "gpt-5.6-sol"}})
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(judge_module.subprocess, "run", fake_pi)
    report_path = run_judge(ROOT, "first-night", dist_path=dist)
    manifest = json.loads((report_path.parent / "manifest.json").read_text())
    assert manifest["status"] == "insufficient-evidence"
    assert manifest["report_status"] == "insufficient-evidence"
    assert not manifest["coverage_sufficient"]
    assert manifest["judge_identity"]["compatible"] is True
    assert manifest["resolved_model"] == "gpt-5.6-sol"
    assert manifest["usable"] is False


@pytest.mark.parametrize(
    ("stdout", "expected_error"),
    [
        ("", "missing"),
        (
            json.dumps({"type": "message_start", "message": {"model": "gpt-5.6-luna"}}),
            "incompatible",
        ),
    ],
)
def test_run_judge_rejects_missing_or_wrong_resolved_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
    expected_error: str,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>judge fixture</title>")
    state_root = tmp_path / "judge-state"
    monkeypatch.setattr(judge_module, "judges_dir", lambda: state_root)
    monkeypatch.setattr(judge_module, "_chromium", lambda: Path("/bin/false"))
    monkeypatch.setattr(judge_module, "_pi_version", lambda: "test-pi")
    monkeypatch.setattr(judge_module.shutil, "which", lambda _name: "/fake/pi")

    def fake_pi(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        output = Path(environment["W3GB_JUDGE_OUTPUT"])
        rubric = validate_judge_assets(ROOT, "first-night")
        report = {
            "schema_version": 2,
            "task_id": "first-night",
            "status": "complete",
            "provisional_score": 90,
            "evidence_coverage": 100,
            "minimum_evidence_coverage": 70,
            "meets_minimum_evidence_coverage": True,
            "criteria": rubric["criteria"],
        }
        (output / "judge-report.json").write_text(json.dumps(report))
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(judge_module.subprocess, "run", fake_pi)
    with pytest.raises(RuntimeError, match="invalid model identity"):
        run_judge(ROOT, "first-night", dist_path=dist)

    output = next(state_root.iterdir())
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "infrastructure-error"
    assert manifest["failure_scope"] == "judge-identity"
    assert expected_error in manifest["identity_error"]
    assert manifest["judge_identity"]["compatible"] is False
    assert manifest["usable"] is False


def test_pi_judge_keeps_unverified_in_denominator_and_supports_rich_input() -> None:
    extension = (ROOT / "infra/judge/pi/playtest-judge.ts").read_text()
    assert "earnedWeight / totalWeight" in extension
    assert "unverified_is_zero: true" in extension
    assert "minimum_evidence_coverage" in extension
    assert 'Type.Literal("right")' in extension
    assert 'Type.Literal("move")' in extension
    assert 'Type.Literal("relative_move")' in extension
    assert 'Type.Literal("mouse_down")' in extension
    assert 'Type.Literal("mouse_up")' in extension
    assert 'Type.Literal("wheel")' in extension
    assert 'Type.Literal("touch_start")' in extension
    assert 'Type.Literal("touch_move")' in extension
    assert 'Type.Literal("touch_end")' in extension
    assert "waitActionCount" in extension
    assert "totalWaitMs" in extension
    assert "rubric.viewports" in extension
    assert "window.__AETHERPLAY__" not in extension
    for key in ("Key${letter}", "F${index}", "ControlLeft", "AltLeft", "Digit${digit}"):
        assert key in extension


def test_pi_judge_browser_is_origin_locked_and_sandboxed() -> None:
    extension = (ROOT / "infra/judge/pi/playtest-judge.ts").read_text()
    assert '"--no-sandbox"' not in extension
    assert '"about:blank"' in extension
    assert "allowedGameOrigin" in extension
    assert 'cdp.on("Fetch.requestPaused"' in extension
    assert 'cdp.send("Fetch.enable"' in extension
    assert '"Fetch.continueRequest"' in extension
    assert '"Fetch.failRequest"' in extension
    assert 'cdp.on("Page.frameNavigated"' in extension
    assert "Cross-origin top-frame navigation" in extension
    assert 'parsed.protocol === "data:" || parsed.protocol === "blob:"' in extension
    assert "parsed.origin === allowedGameOrigin" in extension
    assert 'cdp.send("Page.navigate", { url: gameUrl })' in extension


def test_judge_server_allows_only_self_contained_runtime_connections(
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>test</title>")
    handler = functools.partial(QuietHandler, directory=tmp_path)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_port}/", timeout=2
        )
        policy = response.headers["Content-Security-Policy"]
        assert "connect-src 'self' data: blob:" in policy
        assert "connect-src *" not in policy
        assert "form-action 'none'" in policy
        assert response.headers["Cache-Control"] == "no-store"
    finally:
        server.shutdown()
        server.server_close()


def test_judge_server_mounts_game_at_production_style_nested_path(
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>nested</title>")
    mount_path = "/playground/first-night/private-run/"
    handler = functools.partial(QuietHandler, directory=tmp_path, mount_path=mount_path)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        response = urllib.request.urlopen(f"{origin}{mount_path}", timeout=2)
        assert b"nested" in response.read()
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"{origin}/", timeout=2)
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
