# Season Protocol

1. Freeze every candidate-visible task file, private runtime contract, judge rubric, and offline dependency digest.
2. Expand `task x profile x attempt` into an immutable plan, including the publication catalog template. Run the three-family Harbor smoke gate against that exact plan; a fresh, digest-matched Codex/Claude/Pi receipt is required before any paid matrix cell starts.
3. Create disposable workspaces outside both repositories.
4. Activate the runner-owned persistent execution control outside the canonical task prompt, and record its method and digest in the immutable run manifest.
5. Run candidate cells as Harbor trials in isolated containers; preserve the raw Harbor job, stdout, stderr, final response, source, and canonical manifest.
6. Classify runtime infrastructure failures separately from candidate failures.
7. Verify the terminal candidate-workspace digest before snapshotting it, normalize the playable bundle, then run the task-aware deterministic build and browser admission checks without modifying candidate source. Serve the game beneath a production-shaped nested `/playground/<task>/<profile>/` route so root-relative assets fail before publication. The bytes admitted by the evaluator are the bytes eligible for publication.
8. Run task-specific blinded playtest judges directly against the private immutable render when semantic diagnostic evidence is required; never publish a game merely to judge it.
9. Bound each candidate cell to two hours and each Pi shell command to 20 minutes. A command timeout returns control to the agent and remains visible in the raw trace; a cell timeout stops and classifies the run as infrastructure evidence.
10. Run candidate containers with Docker init, a 1024-PID ceiling, and the supervised Chromium launcher. Stream stdout and stderr into the run directory so interruption or timeout preserves the trace accumulated before cleanup.
11. Close the complete matrix before publishing any prompt or source. The first validly started Season 1 matrix is canonical; interruptions and infrastructure failures resume that receipt rather than creating another attempt. A matrix whose frozen inputs are intentionally revised must be explicitly invalidated before a replacement plan is started.
12. Bind each terminal cell's manifest, Harbor task lock and trial receipt, raw event stream, stderr, evaluator report, evaluated source tree, and playable bundle into the closed receipt.
13. Publish every trusted cell from that receipt in one operation. Revalidate the frozen plan and run bindings, then copy source and build only from the evaluator's immutable `render/` snapshot, never from the mutable candidate workspace.
14. Deploy the frozen season catalog, games, Arena API, and D1 migration.
15. Verify desktop, 390 px phone, keyboard, pointer/touch, restart, cross-task pair sampling, voting, and leaderboard behavior on the live domain.

Claude Fable runs as a separate optional backfill lane bound to the frozen core plan. It is excluded
from the task barrier and publication closure gate. Quota exhaustion records `quota-deferred`, stops
the optional lane without affecting the core matrix, and remains resumable by season or task.

The official pilot and Season 1 use one attempt per profile. Failed candidate code and deterministic
evidence failures remain terminal cells; only interrupted or infrastructure-failed cells may be
retried. Task-specific private playtest judges provide semantic diagnostics, while automated checks
remain admission and reliability gates and blind human preference votes determine the ranking.

Harbor is the official candidate execution backend, but it is not the benchmark authority. The
repository runner launches one Harbor trial per cell and retains task/profile scheduling, task
barriers, interruption handling, retry policy, evaluator admission, immutable closure, Fable
backfill, and publication. Harbor rewards are capture diagnostics only and never replace the
task-aware trusted evaluator. Container execution remains an explicit fallback backend.
