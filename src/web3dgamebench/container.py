from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Profile


class ContainerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContainerConfig:
    image: str
    evaluator_image: str
    internal_network: str
    egress_network: str
    proxy_container: str
    proxy_port: int
    egress_allow: tuple[str, ...]
    memory: str | None
    cpus: str | None
    command_timeout_seconds: int

    @property
    def proxy_url(self) -> str:
        return f"http://{self.proxy_container}:{self.proxy_port}"


def load_container_config(root: Path) -> ContainerConfig:
    import tomllib

    raw = tomllib.loads((root / "configs/container.toml").read_text())["container"]
    config = ContainerConfig(
        image=str(raw["image"]),
        evaluator_image=str(raw["evaluator_image"]),
        internal_network=str(raw["internal_network"]),
        egress_network=str(raw["egress_network"]),
        proxy_container=str(raw["proxy_container"]),
        proxy_port=int(raw["proxy_port"]),
        egress_allow=tuple(raw["egress_allow"]),
        memory=raw.get("memory"),
        cpus=raw.get("cpus"),
        command_timeout_seconds=int(raw.get("command_timeout_seconds", 1200)),
    )
    if config.command_timeout_seconds <= 0:
        raise ContainerError("command_timeout_seconds must be positive")
    return config


def docker(*args: str, timeout: int = 180, check: bool = True) -> subprocess.CompletedProcess[str]:
    if not shutil.which("docker"):
        raise ContainerError("docker is not installed")
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=False)
    if check and result.returncode:
        raise ContainerError((result.stderr or result.stdout).strip())
    return result


def _network(name: str, internal: bool) -> None:
    if docker("network", "inspect", name, check=False).returncode == 0:
        return
    args = ["network", "create"]
    if internal:
        args.append("--internal")
    docker(*args, name)


def ensure_plane(root: Path, config: ContainerConfig) -> dict:
    if docker("image", "inspect", config.image, check=False).returncode:
        raise ContainerError(
            f"missing image {config.image}; build it with docker build -t {config.image} infra/candidate"
        )
    _network(config.egress_network, False)
    _network(config.internal_network, True)
    running = docker("inspect", "--format", "{{.State.Running}}", config.proxy_container, check=False)
    if running.returncode or running.stdout.strip() != "true":
        docker("rm", "-f", config.proxy_container, check=False)
        proxy_script = root / "infra/candidate/egress_proxy.py"
        allow: list[str] = []
        for host in config.egress_allow:
            allow.extend(["--allow", host])
        docker(
            "run", "-d", "--name", config.proxy_container, "--network", config.egress_network,
            "--restart", "unless-stopped", "-v", f"{proxy_script}:/egress_proxy.py:ro",
            config.image, "python3", "/egress_proxy.py", "--port", str(config.proxy_port), *allow,
        )
        docker("network", "connect", config.internal_network, config.proxy_container)
    return {
        "image": config.image,
        "image_digest": docker("image", "inspect", "--format", "{{.Id}}", config.image).stdout.strip(),
        "network": config.internal_network,
        "proxy": config.proxy_container,
        "egress_allow": list(config.egress_allow),
    }


def stage_credentials(profile: Profile, destination: Path) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)
    staged: dict[str, str] = {}
    if profile.harness == "codex":
        source = Path.home() / ".codex/auth.json"
        if not source.is_file():
            raise ContainerError("Codex auth.json is missing")
        shutil.copy2(source, destination / "auth.json")
        staged["CODEX_HOME"] = "/runtime-home"
    elif profile.harness == "claude-code":
        source = Path.home() / ".claude/.credentials.json"
        if source.is_file():
            shutil.copy2(source, destination / ".credentials.json")
        elif platform.system() == "Darwin" and shutil.which("security"):
            result = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode or not result.stdout:
                raise ContainerError("Claude Code credential is unavailable")
            payload = json.loads(result.stdout)
            if "claudeAiOauth" not in payload:
                raise ContainerError("Claude Code keychain payload has no OAuth credential")
            (destination / ".credentials.json").write_text(result.stdout)
        else:
            raise ContainerError("Claude Code credential is unavailable")
        staged["CLAUDE_CONFIG_DIR"] = "/runtime-home"
    return staged


def prepare_dependencies(root: Path, config: ContainerConfig, workspace: Path) -> None:
    vendor = root / "vendor"
    result = docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "-v",
        f"{workspace}:/workspace",
        "-v",
        f"{vendor}:/vendor:ro",
        "-w",
        "/workspace",
        "-e",
        "HOME=/tmp",
        "-e",
        "npm_config_cache=/vendor/npm-cache",
        "-e",
        "npm_config_offline=true",
        config.image,
        "npm",
        "ci",
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
        timeout=300,
        check=False,
    )
    if result.returncode:
        raise ContainerError(f"offline dependency preparation failed: {result.stderr.strip()}")


def wrap_command(
    argv: tuple[str, ...],
    *,
    root: Path,
    config: ContainerConfig,
    workspace: Path,
    profile: Profile,
    credential_dir: Path,
) -> tuple[list[str], dict[str, str]]:
    vendor = root / "vendor"
    if not (vendor / "manifest.json").is_file():
        raise ContainerError("offline vendor store is missing; run web3dgamebench vendor")
    runtime_env = stage_credentials(profile, credential_dir)
    environment = {
        "HOME": "/home/candidate",
        "HTTPS_PROXY": config.proxy_url,
        "HTTP_PROXY": config.proxy_url,
        "NO_PROXY": "127.0.0.1,localhost",
        "npm_config_cache": "/vendor/npm-cache",
        "npm_config_offline": "true",
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
        "CI": "1",
        **runtime_env,
    }
    if profile.harness == "pi":
        if not profile.credential_env or not profile.runtime_env:
            raise ContainerError("pi profile is missing credential mapping")
        value = os.environ.get(profile.credential_env)
        if not value:
            raise ContainerError(f"missing {profile.credential_env}")
        environment[profile.runtime_env] = value
        environment["PI_CODING_AGENT_DIR"] = "/tmp/pi-agent"
        environment["WEB3DGAMEBENCH_COMMAND_TIMEOUT_SECONDS"] = str(
            config.command_timeout_seconds
        )
    args = [
        "docker", "run", "--rm", "-i", "--network", config.internal_network,
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--init",
        "-v", f"{workspace}:/workspace", "-v", f"{vendor}:/vendor:ro",
        "-v", f"{credential_dir}:/runtime-home", "-w", "/workspace",
    ]
    if profile.harness == "pi":
        timeout_extension = root / "infra/candidate/pi_command_timeout.js"
        if not timeout_extension.is_file():
            raise ContainerError(f"missing Pi command timeout extension: {timeout_extension}")
        extension_target = (
            "/usr/lib/node_modules/@earendil-works/pi-coding-agent/"
            "web3dgamebench-command-timeout.js"
        )
        args.extend(["-v", f"{timeout_extension}:{extension_target}:ro"])
    if config.memory:
        args.extend(["--memory", config.memory])
    if config.cpus:
        args.extend(["--cpus", config.cpus])
    for key, value in sorted(environment.items()):
        args.extend(["-e", f"{key}={value}"])
    args.append(config.image)
    if profile.harness == "pi":
        args.extend(
            [
                argv[0],
                "--extension",
                "/usr/lib/node_modules/@earendil-works/pi-coding-agent/web3dgamebench-command-timeout.js",
                *argv[1:],
            ]
        )
    else:
        args.extend(argv)
    # Return redacted environment metadata separately; never persist values.
    return args, {key: "<passed>" for key in environment}
