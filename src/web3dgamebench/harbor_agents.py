from __future__ import annotations

import asyncio
import json
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, ClassVar, override

from harbor.agents.installed.base import BaseInstalledAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


class _Web3DHarborAgent(BaseInstalledAgent):
    harness: str
    expected_versions: ClassVar[dict[str, str]]

    def version(self) -> str:
        return "web3dgamebench-harbor-1"

    async def install(self, environment: BaseEnvironment) -> None:
        checks = " && ".join(f"{binary} --version" for binary in self.expected_versions)
        result = await self.exec_as_agent(environment, command=checks)
        output = f"{result.stdout or ''}\n{result.stderr or ''}"
        missing = [version for version in self.expected_versions.values() if version not in output]
        if result.return_code != 0 or missing:
            raise RuntimeError(f"frozen runtime version check failed; missing={missing!r}")

    def _invocation(self) -> dict[str, Any]:
        raw = self._get_env("WEB3DGAMEBENCH_INVOCATION_JSON")
        if not raw:
            raise RuntimeError("WEB3DGAMEBENCH_INVOCATION_JSON is required")
        try:
            invocation = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError("invalid Web3DGameBench invocation payload") from error
        if invocation.get("harness") != self.harness:
            raise RuntimeError("Harbor agent does not match the frozen harness invocation")
        if invocation.get("model") != self.model_name:
            raise RuntimeError(
                f"expected model {invocation.get('model')!r}, got {self.model_name!r}"
            )
        argv = invocation.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            raise RuntimeError("frozen Harbor invocation has no argv")
        return invocation

    async def _upload_secret(
        self, environment: BaseEnvironment, source: Path, target: str
    ) -> None:
        if not source.is_file():
            raise RuntimeError(f"credential file is missing: {source}")
        await environment.upload_file(source, target)
        await self.exec_as_root(
            environment,
            command=(
                f"chown candidate:candidate {shlex.quote(target)} "
                f"&& chmod 0600 {shlex.quote(target)}"
            ),
        )

    async def runtime_environment(self, environment: BaseEnvironment) -> dict[str, str]:
        return {}

    @override
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        invocation = self._invocation()
        expected_instruction = invocation.get("instruction")
        if instruction != expected_instruction:
            raise RuntimeError("Harbor changed the frozen candidate instruction")
        await self.exec_as_root(
            environment,
            command=(
                "mkdir -p /runtime-home /logs/agent && "
                "chown -R candidate:candidate /runtime-home /logs/agent"
            ),
        )
        runtime_env = {
            str(key): str(value) for key, value in invocation.get("env", {}).items()
        }
        runtime_env.update(await self.runtime_environment(environment))
        command = shlex.join(invocation["argv"])
        if invocation.get("stdin_prompt"):
            command = f"printf %s {shlex.quote(instruction)} | {command}"
        command += " > /logs/agent/events.jsonl 2> /logs/agent/stderr.log"
        result = await self.exec_as_agent(environment, command=command, env=runtime_env)
        if result.return_code != 0:
            raise RuntimeError(f"candidate harness exited with status {result.return_code}")


class Web3DCodex(_Web3DHarborAgent):
    harness = "codex"
    expected_versions: ClassVar[dict[str, str]] = {"codex": "0.149.1"}

    @staticmethod
    def name() -> str:
        return "web3d-codex"

    async def runtime_environment(self, environment: BaseEnvironment) -> dict[str, str]:
        source = Path(
            self._get_env("CODEX_AUTH_JSON_PATH") or Path.home() / ".codex/auth.json"
        )
        await self._upload_secret(environment, source, "/runtime-home/auth.json")
        return {"CODEX_HOME": "/runtime-home"}


class Web3DClaude(_Web3DHarborAgent):
    harness = "claude-code"
    expected_versions: ClassVar[dict[str, str]] = {"claude": "2.1.258"}

    @staticmethod
    def name() -> str:
        return "web3d-claude"

    async def runtime_environment(self, environment: BaseEnvironment) -> dict[str, str]:
        explicit = self._get_env("CLAUDE_CREDENTIALS_PATH")
        temporary_path: Path | None = None
        try:
            if explicit:
                source = Path(explicit)
            else:
                source = Path.home() / ".claude/.credentials.json"
                if not source.is_file():
                    result = await asyncio.to_thread(
                        subprocess.run,
                        [
                            "security",
                            "find-generic-password",
                            "-s",
                            "Claude Code-credentials",
                            "-w",
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if result.returncode or not result.stdout:
                        raise RuntimeError("Claude Code OAuth credential is unavailable")
                    json.loads(result.stdout)
                    with tempfile.NamedTemporaryFile("w", delete=False) as temporary:
                        temporary.write(result.stdout)
                        temporary_path = Path(temporary.name)
                    source = temporary_path
            await self._upload_secret(environment, source, "/runtime-home/.credentials.json")
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return {"CLAUDE_CONFIG_DIR": "/runtime-home"}


class Web3DPi(_Web3DHarborAgent):
    harness = "pi"
    expected_versions: ClassVar[dict[str, str]] = {"pi": "0.84.4"}

    @staticmethod
    def name() -> str:
        return "web3d-pi"

    async def runtime_environment(self, environment: BaseEnvironment) -> dict[str, str]:
        key = self._get_env("OPENCODE_GO_APIKEY")
        if not key:
            raise RuntimeError("OPENCODE_GO_APIKEY is required")
        command_timeout = self._get_env("WEB3DGAMEBENCH_COMMAND_TIMEOUT_SECONDS")
        if not command_timeout or not command_timeout.isdigit():
            raise RuntimeError("WEB3DGAMEBENCH_COMMAND_TIMEOUT_SECONDS is required")
        raw_adapter = self._get_env("WEB3DGAMEBENCH_PI_ADAPTER_ENV_JSON")
        if not raw_adapter:
            raise RuntimeError("WEB3DGAMEBENCH_PI_ADAPTER_ENV_JSON is required")
        try:
            adapter = json.loads(raw_adapter)
        except json.JSONDecodeError as error:
            raise RuntimeError("invalid Pi adapter environment") from error
        if not isinstance(adapter, dict) or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in adapter.items()
        ):
            raise RuntimeError("invalid Pi adapter environment")
        return {
            "OPENCODE_API_KEY": key,
            "PI_CODING_AGENT_DIR": "/runtime-home/pi-agent",
            "WEB3DGAMEBENCH_COMMAND_TIMEOUT_SECONDS": command_timeout,
            **adapter,
        }
