# Season Protocol

1. Freeze every public task file and offline dependency digest.
2. Expand `task x profile x attempt` into an immutable plan.
3. Create disposable workspaces outside both repositories.
4. Run candidate cells in isolated containers; preserve stdout, stderr, final response, source, and manifest.
5. Classify runtime infrastructure failures separately from candidate failures.
6. Run deterministic build and browser checks without modifying candidate source.
7. Close the complete matrix before publishing any prompt or source.
8. Publish source and build to `web3dgamebench-games` in one release commit.
9. Deploy the catalog, games, Arena API, and D1 migration.
10. Verify desktop, 390 px phone, keyboard, pointer/touch, restart, pair voting, and leaderboard behavior on the live domain.

The official pilot uses one attempt per profile. Failed candidate code remains visible as a failed cell; only infrastructure failures may be retried.
