# Web3DGameBench Pi Goal Adapter

This directory is a narrow, repository-frozen fork of `@narumitw/pi-goal` 0.54.4.
The upstream MIT license is preserved in `LICENSE.upstream`.

`benchmark.ts` is the only loaded entrypoint. It retains upstream managed-run,
session persistence, context-compaction continuation, and workflow ownership,
while replacing the interactive command and generic completion tools with:

- build-gated `benchmark_complete` and `benchmark_blocked` tools;
- source/build-revision-aware completion convergence that stops post-build automation;
- an externally observable benchmark lifecycle.

Normal implementation work has no adapter turn or tool-call cap. A successful
production build for the current source revision is the candidate completion gate;
runtime verification remains the evaluator's job.
