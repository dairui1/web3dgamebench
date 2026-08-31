# Web3DGameBench Contributor Instructions

Web3DGameBench evaluates coding agents building playable browser-native 3D games.

- Candidate-visible inputs live only in `tasks/*/task/`.
- Keep evaluator checks, unpublished prompts, vote exports, runtime logs, and credentials outside candidate workspaces.
- Candidate workspaces must live outside this repository so they do not inherit this file or repository history.
- Run a complete season matrix before publishing task prompts or submission code. Publishing one cell early contaminates later cells.
- Candidate dependency installation is offline from `vendor/npm-cache`. Runtime network access is limited to the selected model API.
- Never pass GitHub or Cloudflare credentials into a candidate workspace. The publisher, not the candidate, commits and deploys successful artifacts.
- Preserve raw runtime logs and immutable manifests. Infrastructure failures may be retried; candidate build or behavior failures are benchmark evidence.
- Human preference votes determine the public ranking. Automated checks are admission and reliability gates, not a substitute for game feel.
- Generated game source belongs in the separate `web3dgamebench-games` repository. This infrastructure repository contains only tasks, harness, evaluator, and site.
- Do not call production write APIs from candidate code. Games must be static and self-contained after build.

Useful commands:

```bash
uv run web3dgamebench doctor
uv run web3dgamebench plan --season pilot-2026-09
uv run web3dgamebench vendor
uv run web3dgamebench run --task signal-drift --profile codex-sol-medium --backend native
uv run web3dgamebench matrix --season pilot-2026-09 --backend container
uv run web3dgamebench publish --season pilot-2026-09 --games-repo ../web3dgamebench-games
uv run pytest
npm --prefix site test
npm --prefix site run deploy
```
