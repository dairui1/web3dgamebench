# Season Protocol

1. Freeze every candidate-visible task file, private runtime contract, judge rubric, and offline dependency digest.
2. Expand `task x profile x attempt` into an immutable plan, including the publication catalog template; preflight rejects missing or mismatched task contracts before any paid cell starts.
3. Create disposable workspaces outside both repositories.
4. Activate the runner-owned persistent execution control outside the canonical task prompt, and record its method and digest in the immutable run manifest.
5. Run candidate cells in isolated containers; preserve stdout, stderr, final response, source, and manifest.
6. Classify runtime infrastructure failures separately from candidate failures.
7. Verify the terminal candidate-workspace digest before snapshotting it, normalize the playable bundle, then run the task-aware deterministic build and browser admission checks without modifying candidate source. Serve the game beneath a production-shaped nested `/playground/<task>/<profile>/` route so root-relative assets fail before publication. The bytes admitted by the evaluator are the bytes eligible for publication.
8. Run task-specific blinded playtest judges directly against the private immutable render when semantic diagnostic evidence is required; never publish a game merely to judge it.
9. Bound individual candidate shell commands, not the candidate's overall completion time. A command timeout returns control to the agent and remains visible in the raw trace.
10. Close the complete matrix before publishing any prompt or source. The first started Season 1 matrix is canonical; interruptions and infrastructure failures resume that receipt rather than creating another attempt.
11. Bind each terminal cell's manifest, raw event stream, stderr, evaluator report, evaluated source tree, and playable bundle into the closed receipt.
12. Publish every trusted cell from that receipt in one operation. Revalidate the frozen plan and run bindings, then copy source and build only from the evaluator's immutable `render/` snapshot, never from the mutable candidate workspace.
13. Deploy the frozen season catalog, games, Arena API, and D1 migration.
14. Verify desktop, 390 px phone, keyboard, pointer/touch, restart, cross-task pair sampling, voting, and leaderboard behavior on the live domain.

The official pilot and Season 1 use one attempt per profile. Failed candidate code and deterministic
evidence failures remain terminal cells; only interrupted or infrastructure-failed cells may be
retried. Task-specific private playtest judges provide semantic diagnostics, while automated checks
remain admission and reliability gates and blind human preference votes determine the ranking.
