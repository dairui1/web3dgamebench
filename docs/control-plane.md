# Local Matrix Control Plane

The local control plane provides a persistent operator surface for the private Matrix. It is
not part of the public arena and is never deployed by `npm --prefix site run deploy`.

## Start

```bash
uv run web3dgamebench control
```

The server listens on `127.0.0.1:8765` by default. Both the CLI and HTTP middleware reject a
non-loopback host. The first page response injects a random write token stored with mode `0600`
under `${WEB3DGAMEBENCH_RUNS_DIR:-~/.local/state/web3dgamebench/runs}/control/token`.
Read endpoints are local-only; every state-changing endpoint additionally requires that token.

## Authority

The browser never runs Harbor or edits a receipt. It sends typed actions to one supervisor,
which launches the existing `web3dgamebench matrix` command in a
separate process group. The
Matrix process still owns `SeasonLock`, frozen-input verification, task scheduling, trusted
evaluation, receipt updates, closure, and canonical-claim enforcement. Harbor remains the
single-cell execution backend.

The supervisor persists its process identity, command, log path, and lifecycle in
`runs/control/runner.json`; operator actions are appended to `runs/control/events.jsonl`.
Restarting the WebUI does not automatically resume an interrupted or incomplete Matrix.

## Actions

- **Prepare configuration** creates a new immutable Season 1 plan from the current repository and
  runs the matching Harbor smoke checks for Codex, Claude Code, and Pi. It never starts a Matrix;
  the resulting pair appears in the launch selector when the smoke receipt passes.
- **Start** accepts only plan and smoke receipt paths below the managed run directory and always
  uses the Harbor backend. Season 1 rejects a stale plan, mismatched smoke receipt, an existing
  canonical claim, or a smoke receipt that does not pass for the exact selected plan digest.
- **Pause at barrier** writes a command bound to the current `matrix_id`. The Matrix acknowledges
  it only after every active harness chain for the current task returns, records the barrier in
  the receipt, and exits as `incomplete`.
- **Interrupt now** sends `SIGINT` to the managed Matrix process group. Existing cancellation and
  trace-preservation behavior marks active work interrupted before the process exits.
- **Resume** accepts only the receipt named by the canonical claim. It cannot switch the plan or
  backend and cannot resume an invalidated Matrix.
- **Invalidate** is available only after the managed runner has stopped and before the Matrix is
  closed. It requires an operator reason and explicit confirmation, preserves the old claim and
  receipt as audit records, writes the immutable invalidation marker, and releases the season for
  a new canonical Matrix.

Candidate and evidence failures remain terminal evidence. They do not gain a retry action in the
WebUI. Infrastructure errors and interrupted cells remain resumable through the canonical receipt.

## Recovery

If the control server exits while its Matrix child remains alive, `runner.json` retains the PID
and process-group ID so a restarted server can display and interrupt it. If the process no longer
exists, the supervisor records that observation as an exited runner and leaves the receipt intact.
It never guesses that an incomplete receipt should resume.
