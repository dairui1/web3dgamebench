# Web3DGameBench

Web3DGameBench is a reproducible arena for coding agents that build complete, playable Three.js games. Every system receives the same frozen task, starter dependency set, and browser checks. Candidate cells and Pi shell commands use the same 90-minute timeout. Pi uses upstream `pi-goal` for persistent Goal continuation, with a thin bridge for non-interactive execution. Candidate containers also use a PID limit and a supervised Chromium launcher. Candidate work happens in disposable workspaces with no access to other submissions. Source and playable builds are published only after the full season matrix closes.

The public result is intentionally two-part:

1. Deterministic admission checks establish that a submission builds, renders a visible nonblank canvas at desktop and phone viewports, resizes safely, avoids page errors, and makes no runtime network requests.
2. Blind pairwise play determines the leaderboard. Visitors compare two games from the same task without seeing the model name; ratings use a Bradley-Terry fit.

## Core profiles

| Profile | Harness | Model | Thinking |
| --- | --- | --- | --- |
| `codex-sol-medium` | Codex | `gpt-5.6-sol` | `medium` |
| `codex-terra-high` | Codex | `gpt-5.6-terra` | `high` |
| `codex-luna-max` | Codex | `gpt-5.6-luna` | `max` |
| `claude-sonnet-default` | Claude Code | `claude-sonnet-5` | official default |
| `claude-opus-default` | Claude Code | `claude-opus-5` | official default |
| `claude-fable-default` | Claude Code | `claude-fable-5-1` | optional backfill |
| `pi-deepseek-v4-flash` | pi | `opencode-go/deepseek-v4-flash` | provider default |
| `pi-qwen3-8-flash` | pi | `opencode-go/qwen3.8-flash` | provider default |
| `pi-glm-5-3-flash` | pi | `opencode-go/glm-5.3-flash` | provider default |

The executable matrix is defined by `configs/seasons.toml` and `configs/profiles.toml`, not by
this table. Run `uv run web3dgamebench plan --season <season-id>` and review the complete output
before starting paid cells. `pilot-2026-09` preserves the immutable Signal Drift pilot. `season-1`
is the runnable private matrix for the ten frozen official tasks; no task prompt or generated game
may be published until all 80 cells reach a terminal state.

Claude Fable is a separate optional lane, not a ninth core profile. It never blocks the 80-cell
matrix or publication. A quota-limited run is recorded as `quota-deferred` and can be resumed later,
for the whole season or selected tasks, against the same frozen core plan.

## Boundaries

- `web3dgamebench`: tasks, harness, checks, release manifests, and the arena site.
- `web3dgamebench-games`: immutable published source and builds for completed seasons.
- `${WEB3DGAMEBENCH_RUNS_DIR:-~/.local/state/web3dgamebench/runs}`: private candidate workspaces and raw traces.
- `web3dgamebench.dairui1.com`: public catalog, playable routes, arena voting, and leaderboard.

Published runs also receive an immutable replay route at `/replay/<run-id>`. The publisher
normalizes Codex, Claude Code, and Pi event streams into a compact replay timeline under
`site/public/data/traces/`; raw `events.jsonl`, stderr, evaluator logs, and credentials remain in
the private run directory.

Leaderboard rows also show a reproducible official-API-equivalent cost. The publisher normalizes
uncached input, cached input, cache writes, and output tokens, then applies the versioned official
rates in `configs/pricing.toml`. This is an estimate for cross-system comparison, not the amount
charged by subscription products such as Codex, Claude Code, or OpenCode Go.

See `docs/architecture.md` and `docs/protocol.md` before running a paid matrix.

The authoritative Season 1 control plane remains `web3dgamebench matrix`. Its default Harbor
backend owns only isolated candidate execution. Web3DGameBench still owns the frozen plan, task
barrier, retry classification, canonical receipt, trusted evaluator, closure, and publisher. Every
Harbor trial is converted into the repository run schema and bound by `harbor.json` plus
`harbor-task-lock.json`; raw Harbor job data remains private. The older adapter under
`experiments/harbor_parity/` is retained only as historical comparison evidence.

## Operator quick start

```bash
uv sync
uv run web3dgamebench control
uv run web3dgamebench vendor
docker build -t web3dgamebench-candidate:0.3.0 infra/candidate
docker build -t web3dgamebench-evaluator:0.1.0 infra/evaluator
uv run web3dgamebench doctor
uv run web3dgamebench plan --season season-1 --output /path/to/season-1-plan.json
uv run web3dgamebench smoke --plan /path/to/season-1-plan.json --backend harbor
uv run web3dgamebench matrix --plan /path/to/season-1-plan.json --smoke-receipt /path/to/smoke/receipt.json --backend harbor
# Stop cleanly at a task barrier when operating the season in review windows:
uv run web3dgamebench matrix --plan /path/to/season-1-plan.json --smoke-receipt /path/to/smoke/receipt.json --backend harbor --stop-after-task canyon-strike
# After an interruption or infrastructure failure, resume the same receipt:
uv run web3dgamebench matrix --resume /path/to/matrix-receipt.json
# Optional, quota-aware Fable lane; repeat this command later to resume deferred cells:
uv run web3dgamebench fable --core-plan /path/to/season-1-plan.json
# Or backfill selected tasks into the same receipt:
uv run web3dgamebench fable --core-plan /path/to/season-1-plan.json --task canyon-strike
# After all 80 cells are terminal:
uv run web3dgamebench publish --matrix /path/to/closed-matrix.json --games-repo ../web3dgamebench-games
```

`web3dgamebench control` starts the private operator UI at `http://127.0.0.1:8765`.
It can start a reviewed plan with a matching smoke receipt, request a graceful pause at the next task barrier, interrupt
the managed process group, and resume the same canonical receipt. The control plane listens
only on loopback, keeps its write token outside the repository, and never exposes model
credentials to the browser. See `docs/control-plane.md` for its operating and recovery contract.

The first started `season-1` matrix becomes the season's canonical matrix. A later start is rejected;
operators must resume its receipt instead. Candidate and evidence failures remain terminal benchmark
results, while provider, harness, and evaluator infrastructure failures stop the matrix and remain
resumable. Closing binds every run manifest, trace, evaluator report, evaluated source tree, and
playable bundle digest. Publication revalidates those bindings and uses the frozen Season 1 catalog.

The candidate image deliberately layers the pinned runtimes on ReconBench's local
`reconbench-candidate:0.147.0` base. Candidate generation, production rendering, and browser
evaluation run in separate containers. Only the generation container joins the API allowlist
proxy; production rendering has `--network none`, and the evaluator uses a fresh internal
network with no credentials.
