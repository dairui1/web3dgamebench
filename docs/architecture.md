# Architecture

## Repositories and trust boundaries

`web3dgamebench` owns benchmark inputs and operations. `web3dgamebench-games` is a separate publication repository populated only by the trusted publisher after every cell in a season has reached a terminal state. Candidate workspaces live under the user state directory, never below either repository.

The candidate receives only:

- the selected task's `task/` directory;
- the neutral Vite, TypeScript, and Three.js starter;
- an offline npm cache;
- one model runtime and its minimum credential;
- an egress proxy whose allowlist contains model API hosts only.

It does not receive other submissions, evaluator scripts, release data, Git history, GitHub credentials, Cloudflare credentials, votes, or the public site.

## Publication

The publisher validates a trusted passing run, copies source into
`web3dgamebench-games/games/<task>/<profile>/`, and syncs only rendered `dist/` output into the
arena Worker's static assets. Raw traces, credentials, evaluator output, task prompts, and
run manifests remain private.

For every published run, the publisher also derives a bounded trace replay. It removes the
candidate prompt, redacts credential-shaped values, clips large tool inputs and outputs, and
normalizes harness-specific events into messages, changes, tools, errors, phases, and a common
time axis. The derived replay is addressed by the immutable run ID:

```text
https://web3dgamebench.dairui1.com/replay/<run-id>
```

Catalog submissions carry `traceId`, `replayUrl`, and compact replay metrics. A publication fails
when its runtime event stream is missing or cannot be normalized, so future published runs cannot
silently ship without a replay path.

Playable URLs are stable:

```text
https://web3dgamebench.dairui1.com/playground/<task-id>/<submission-id>/
```

The public catalog deliberately labels systems only after a vote is recorded or when the visitor opens the results view. Pair pages are blind.

## Execution runtime

The official Season 1 matrix is owned by the repository runner. Harbor executes each candidate
cell, while the repository serializes tasks, runs the
Codex, Claude Code, and Pi families concurrently within a task, and serializes models within each
family. Candidate containers use Docker init, a 1024-PID ceiling, a supervised Chromium process
group, streamed trace files, and a two-hour cell deadline. The task barrier stops on infrastructure
failure so an operator can classify and resume the same immutable receipt.

Harbor job and trial artifacts are converted into the canonical run layout. `harbor.json` binds the
raw job and trial results, while `harbor-task-lock.json` binds the generated task to the frozen
task/profile inputs. The repository evaluator independently rebuilds and checks the collected
workspace; the publisher continues to accept only a closed canonical matrix receipt.

## Ranking

Votes compare two submissions for the same task. Choices are left, right, tie, left broken, and right broken. Preference votes feed a Bradley-Terry model. Broken votes are reported as reliability evidence but do not masquerade as aesthetic preference. A system becomes rank-eligible only after it has a terminal submission for every active task.
