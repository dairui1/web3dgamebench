from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, override

from harbor.agents.installed.base import BaseInstalledAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


OBJECTIVE = "Complete and verify the benchmark contract in the unmodified TASK.md."
CONTROL = """Web3DGameBench external persistent-goal control (web3dgamebench-native-goal-v2).
This control is supplied by the benchmark runner and is separate from TASK.md.
Persistent objective: Complete and verify the benchmark contract in the unmodified TASK.md.
Keep working autonomously across context compaction until the complete task contract is implemented.
Before finishing, build the production bundle and inspect the game at every required viewport.
Finish only after the implementation and truthful verification evidence satisfy the task contract.
Do not weaken, rewrite, or add this control to TASK.md, and do not claim checks you did not run."""


class _FrozenAgent(BaseInstalledAgent):
    expected_model: str
    expected_versions: dict[str, str]

    def version(self) -> str:
        return "web3dgamebench-harbor-parity-0.0.1"

    async def install(self, environment: BaseEnvironment) -> None:
        checks = " && ".join(f"{binary} --version" for binary in self.expected_versions)
        result = await self.exec_as_agent(environment, command=checks)
        output = f"{result.stdout or ''}\n{result.stderr or ''}"
        missing = [value for value in self.expected_versions.values() if value not in output]
        if result.return_code != 0 or missing:
            raise RuntimeError(f"frozen runtime version check failed; missing={missing!r}")

    def _require_model(self) -> None:
        if self.model_name != self.expected_model:
            raise ValueError(f"expected model {self.expected_model!r}, got {self.model_name!r}")

    async def _upload_secret(
        self, environment: BaseEnvironment, source: Path, target: str
    ) -> None:
        if not source.is_file():
            raise RuntimeError(f"credential file is missing: {source}")
        await environment.upload_file(source, target)
        await self.exec_as_root(
            environment,
            command=f"chown candidate:candidate {shlex.quote(target)} && chmod 0600 {shlex.quote(target)}",
        )


class Web3DCodex(_FrozenAgent):
    expected_model = "gpt-5.6-sol"
    expected_versions = {"codex": "0.149.1"}

    @staticmethod
    def name() -> str:
        return "web3d-codex"

    @override
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        self._require_model()
        source = Path(self._get_env("CODEX_AUTH_JSON_PATH") or Path.home() / ".codex/auth.json")
        await self.exec_as_agent(environment, command="mkdir -p /runtime-home /logs/agent")
        await self._upload_secret(environment, source, "/runtime-home/auth.json")
        payload = shlex.quote(instruction)
        command = (
            f"set -o pipefail; printf %s {payload} | "
            "CODEX_HOME=/runtime-home python3 /usr/local/bin/web3dgamebench-codex-goal "
            "--cwd /workspace --model gpt-5.6-sol --effort medium "
            f"--objective {shlex.quote(OBJECTIVE)} "
            f"--developer-instructions {shlex.quote(CONTROL)} "
            "--final /workspace/.web3dgamebench-final.txt "
            "2>&1 | tee /logs/agent/events.jsonl"
        )
        await self.exec_as_agent(environment, command=command)


class Web3DClaude(_FrozenAgent):
    expected_model = "claude-sonnet-5"
    expected_versions = {"claude": "2.1.243"}

    @staticmethod
    def name() -> str:
        return "web3d-claude"

    @override
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        self._require_model()
        await self.exec_as_agent(environment, command="mkdir -p /runtime-home /logs/agent")
        explicit = self._get_env("CLAUDE_CREDENTIALS_PATH")
        temporary: tempfile.NamedTemporaryFile[str] | None = None
        try:
            if explicit:
                source = Path(explicit)
            else:
                source = Path.home() / ".claude/.credentials.json"
                if not source.is_file():
                    result = subprocess.run(
                        ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if result.returncode or not result.stdout:
                        raise RuntimeError("Claude Code OAuth credential is unavailable")
                    json.loads(result.stdout)
                    temporary = tempfile.NamedTemporaryFile("w", delete=False)
                    temporary.write(result.stdout)
                    temporary.close()
                    source = Path(temporary.name)
            await self._upload_secret(environment, source, "/runtime-home/.credentials.json")
        finally:
            if temporary is not None:
                Path(temporary.name).unlink(missing_ok=True)

        argv = [
            "claude", "-p", "--model", self.expected_model,
            "--setting-sources", "project", "--no-chrome", "--strict-mcp-config",
            "--tools", "Bash,Read,Edit,Write,Glob,Grep", "--permission-mode", "acceptEdits",
            "--allowedTools", "Bash,Read,Edit,Write,Glob,Grep",
            "--output-format", "stream-json", "--verbose", "--include-hook-events",
            "--append-system-prompt", CONTROL, f"/goal {OBJECTIVE}",
        ]
        command = (
            "set -o pipefail; CLAUDE_CONFIG_DIR=/runtime-home CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 "
            "DISABLE_AUTOUPDATER=1 "
            + " ".join(shlex.quote(item) for item in argv)
            + " 2>&1 </dev/null | tee /logs/agent/events.jsonl"
        )
        await self.exec_as_agent(environment, command=command)


class Web3DPi(_FrozenAgent):
    expected_model = "opencode-go/deepseek-v4-flash"
    expected_versions = {"pi": "0.84.4"}

    @staticmethod
    def name() -> str:
        return "web3d-pi"

    @override
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        self._require_model()
        key = self._get_env("OPENCODE_GO_APIKEY")
        if not key:
            raise RuntimeError("OPENCODE_GO_APIKEY is required")
        await self.exec_as_agent(
            environment,
            command=(
                "mkdir -p /runtime-home/pi-agent /logs/agent && "
                "printf '%s\n' '{\"rpc\":{\"enabled\":true}}' > /runtime-home/pi-agent/pi-goal.json"
            ),
        )
        argv = [
            "pi", "--provider", "opencode-go", "--model", "deepseek-v4-flash",
            "--mode", "json", "--print", "--no-context-files", "--no-extensions",
            "--extension", "/opt/web3dgamebench/pi_command_timeout.js",
            "--extension", "/usr/lib/node_modules/@narumitw/pi-goal/dist/index.ts",
            "--extension", "/opt/web3dgamebench/pi_goal_runner.ts",
            "--no-skills", "--no-prompt-templates", "--no-themes",
            "--tools", "read,bash,edit,write,grep,find,ls,goal_complete,goal_blocked,goal_wait",
            "--no-approve", "--append-system-prompt", CONTROL, f"/benchmark-goal {OBJECTIVE}",
        ]
        command = (
            "set -o pipefail; " + " ".join(shlex.quote(item) for item in argv)
            + " 2>&1 </dev/null | tee /logs/agent/events.jsonl"
        )
        await self.exec_as_agent(
            environment,
            command=command,
            env={
                "OPENCODE_API_KEY": key,
                "PI_CODING_AGENT_DIR": "/runtime-home/pi-agent",
                "WEB3DGAMEBENCH_COMMAND_TIMEOUT_SECONDS": "1200",
            },
        )
