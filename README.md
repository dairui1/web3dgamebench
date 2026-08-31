# Web3DGameBench

Web3DGameBench is a reproducible arena for coding agents that build complete, playable Three.js games. Every system receives the same frozen task, starter dependency set, and browser checks, with no fixed candidate runtime limit. Individual Pi shell commands are capped at 20 minutes so a completed but unclosed browser probe returns control to the agent without ending the overall task. Candidate work happens in disposable workspaces with no access to other submissions. Source and playable builds are published only after the full season matrix closes.

The public result is intentionally two-part:

1. Deterministic checks establish that a submission builds, renders, responds to input, works on desktop and phone, and exposes a small runtime inspection contract.
2. Blind pairwise play determines the leaderboard. Visitors compare two games from the same task without seeing the model name; ratings use a Bradley-Terry fit.

## Pilot matrix

| Profile | Harness | Model | Thinking |
| --- | --- | --- | --- |
| `codex-sol-medium` | Codex | `gpt-5.6-sol` | `medium` |
| `codex-terra-high` | Codex | `gpt-5.6-terra` | `high` |
| `codex-luna-max` | Codex | `gpt-5.6-luna` | `max` |
| `claude-sonnet-default` | Claude Code | `claude-sonnet-5` | official default |
| `claude-opus-default` | Claude Code | `claude-opus-5` | official default |
| `pi-deepseek-v4-flash` | pi | `opencode-go/deepseek-v4-flash` | provider default |
| `pi-qwen3-8-flash` | pi | `opencode-go/qwen3.8-flash` | provider default |
| `pi-glm-5-3-flash` | pi | `opencode-go/glm-5.3-flash` | provider default |

The executable matrix is defined by `configs/seasons.toml` and `configs/profiles.toml`, not by
this table. Run `uv run web3dgamebench plan --season <season-id>` and review the complete output
before starting paid cells. At present, `pilot-2026-09` is the only runnable season and contains
only `signal-drift`; the proposed Season 1 tasks remain review drafts.

## Boundaries

- `web3dgamebench`: tasks, harness, checks, release manifests, and the arena site.
- `web3dgamebench-games`: immutable published source and builds for completed seasons.
- `${WEB3DGAMEBENCH_RUNS_DIR:-~/.local/state/web3dgamebench/runs}`: private candidate workspaces and raw traces.
- `web3dgamebench.dairui1.com`: public catalog, playable routes, arena voting, and leaderboard.

Published runs also receive an immutable replay route at `/replay/<run-id>`. The publisher
normalizes Codex, Claude Code, and Pi event streams into a compact replay timeline under
`site/public/data/traces/`; raw `events.jsonl`, stderr, evaluator logs, and credentials remain in
the private run directory.

See `docs/architecture.md` and `docs/protocol.md` before running a paid matrix.

## Operator quick start

```bash
uv sync
uv run web3dgamebench vendor
docker build -t web3dgamebench-candidate:0.1.0 infra/candidate
docker build -t web3dgamebench-evaluator:0.1.0 infra/evaluator
uv run web3dgamebench doctor
uv run web3dgamebench plan --season pilot-2026-09
uv run web3dgamebench matrix --season pilot-2026-09 --backend container
```

The candidate image deliberately layers the pinned runtimes on ReconBench's local
`reconbench-candidate:0.147.0` base. Candidate generation, production rendering, and browser
evaluation run in separate containers. Only the generation container joins the API allowlist
proxy; production rendering has `--network none`, and the evaluator uses a fresh internal
network with no credentials.
