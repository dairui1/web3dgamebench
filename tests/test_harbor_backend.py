import json
from pathlib import Path
from types import SimpleNamespace

from web3dgamebench.config import load_profiles
from web3dgamebench.container import ContainerConfig
from web3dgamebench.harbor_backend import HARBOR_COMMIT, _write_task, execute_harbor
from web3dgamebench.runtimes import build_invocation

ROOT = Path(__file__).resolve().parents[1]


def container_config() -> ContainerConfig:
    return ContainerConfig(
        image="candidate:test",
        evaluator_image="evaluator:test",
        internal_network="internal",
        egress_network="egress",
        proxy_container="proxy",
        proxy_port=8888,
        egress_allow=("openai.com", "anthropic.com"),
        memory="8g",
        cpus="6",
        command_timeout_seconds=1200,
        candidate_total_timeout_seconds=7200,
        pids_limit=1024,
    )


def minimal_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "vendor/npm-cache").mkdir(parents=True)
    for relative in (
        "infra/candidate/chromium",
        "infra/candidate/codex_goal_runner.py",
        "infra/candidate/egress_proxy.py",
        "infra/candidate/pi_command_timeout.js",
        "infra/candidate/pi_goal_runner.ts",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frozen", encoding="utf-8")
    return root


def test_harbor_task_materialization_is_profile_generic_and_preserves_boundaries(
    tmp_path: Path,
) -> None:
    root = minimal_root(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "TASK.md").write_text("task\n", encoding="utf-8")
    (workspace / "package.json").write_text('{"private":true}\n', encoding="utf-8")
    profile = load_profiles(ROOT)["codex-terra-high"]

    task = _write_task(
        root,
        tmp_path / "task",
        workspace,
        "canyon-strike",
        profile,
        "instruction",
        container_config(),
    )

    task_toml = (task / "task.toml").read_text(encoding="utf-8")
    compose = (task / "environment/docker-compose.yaml").read_text(encoding="utf-8")
    assert 'source_profile = "codex-terra-high"' in task_toml
    assert 'source = "/workspace"' in task_toml
    assert 'source = "/logs/agent/events.jsonl"' in task_toml
    assert "pids_limit: 1024" in compose
    assert compose.count("- --allow") == 2
    assert "internal: true" in compose


def test_harbor_trial_is_converted_to_canonical_workspace_and_provenance(
    monkeypatch, tmp_path: Path
) -> None:
    root = minimal_root(tmp_path)
    workspace = tmp_path / "run/workspace"
    workspace.mkdir(parents=True)
    (workspace / "TASK.md").write_text("task\n", encoding="utf-8")
    (workspace / "package.json").write_text('{"private":true}\n', encoding="utf-8")
    run_root = workspace.parent
    profile = load_profiles(ROOT)["codex-sol-medium"]
    instruction = "instruction"
    invocation = build_invocation(profile, Path("/workspace"), instruction)
    cancel_event = object()

    monkeypatch.setattr("web3dgamebench.harbor_backend.harbor_version", lambda: "0.22.0")
    monkeypatch.setattr(
        "web3dgamebench.harbor_backend.load_container_config",
        lambda _root: container_config(),
    )

    def completed(argv, **kwargs):
        assert kwargs["cancel_event"] is cancel_event
        invocation_payload = json.loads(
            kwargs["env"]["WEB3DGAMEBENCH_INVOCATION_JSON"]
        )
        assert invocation_payload["argv"] == list(invocation.argv)
        jobs_dir = Path(argv[argv.index("--jobs-dir") + 1])
        job_name = argv[argv.index("--job-name") + 1]
        trial = jobs_dir / job_name / "trial-1"
        artifact = trial / "artifacts/workspace"
        artifact.mkdir(parents=True)
        (artifact / "TASK.md").write_text("task\n", encoding="utf-8")
        (artifact / "done.txt").write_text("done\n", encoding="utf-8")
        (trial / "artifacts/events.jsonl").write_text("{}\n", encoding="utf-8")
        (trial / "artifacts/stderr.log").write_text("", encoding="utf-8")
        result = {
            "task_checksum": "checksum",
            "exception_info": None,
            "verifier_result": {
                "rewards": {"capture": 1, "task_brief_preserved": 1}
            },
        }
        (trial / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (jobs_dir / job_name / "result.json").write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("web3dgamebench.harbor_backend.run_captured", completed)
    monkeypatch.setattr(
        "web3dgamebench.harbor_backend.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="sha256:image\n", stderr=""
        ),
    )

    result = execute_harbor(
        root,
        run_root,
        workspace,
        task_id="canyon-strike",
        profile=profile,
        instruction=instruction,
        invocation=invocation,
        cancel_event=cancel_event,  # type: ignore[arg-type]
    )

    provenance = json.loads((run_root / "harbor.json").read_text(encoding="utf-8"))
    assert result.returncode == 0
    assert result.stdout == "{}\n"
    assert (workspace / "done.txt").read_text(encoding="utf-8") == "done\n"
    assert provenance["commit"] == HARBOR_COMMIT
    assert provenance["task_checksum"] == "checksum"
    assert provenance["exception"] is None
    assert provenance["adapter_lock_sha256"]
