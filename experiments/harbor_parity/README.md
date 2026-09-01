# Harbor parity lab

This directory preserves the original non-scoring compatibility experiment for Season 1 task 2,
`bombsite-retake`. The formal all-task/all-profile implementation now lives in
`src/web3dgamebench/harbor_backend.py` and `src/web3dgamebench/harbor_agents.py`. Outputs produced
by this historical experiment still must not enter a canonical receipt or publication.

The experiment answers a narrower question: can Harbor reproduce the same candidate-visible task,
pinned model invocation, native Goal lifecycle, network boundary, collected workspace, and trusted
evaluator surface for one profile from each harness family?

## Runtime boundaries

- Harbor is pinned to `0.22.0`, commit `4407eb5227a2ff4f0d3f16b2eb48849382fdf276`.
- Each trial has a two-hour deadline.
- The candidate service uses Docker init and a 1024-PID ceiling.
- The shared Chromium wrapper supervises and reaps the complete browser process group.
- Pi retains its 20-minute per-command limit inside the two-hour trial.
- The candidate joins only the internal proxy network; the proxy alone has egress.
- Harbor collects `/workspace`; `compare.py` then applies the repository's trusted evaluator.

## Static validation

Generate the isolated Harbor task outside the repository and validate it without model calls:

```bash
SOURCE=/Users/agrimonia/dairui1/web3dgamebench
OUT="$(mktemp -d /tmp/web3dgamebench-harbor-parity.XXXXXX)"

cd "$SOURCE"
python -m experiments.harbor_parity.adapter \
  --source-root "$SOURCE" \
  --output-dir "$OUT"
python -m experiments.harbor_parity.validate_static \
  --source-root "$SOURCE" \
  --generated-task "$OUT/bombsite-retake"
```

The validation checks task order and digests, exact instructions, runtime assets, model
invocations, native Goal configuration, image identity, resource limits, and Harbor config loading.

Optional install-only probes verify the three custom agent adapters without invoking a model:

```bash
PYTHONPATH=$PWD harbor run -p "$OUT/bombsite-retake" \
  -a experiments.harbor_parity.agents:Web3DCodex \
  -m gpt-5.6-sol --install-only --force-build --yes
PYTHONPATH=$PWD harbor run -p "$OUT/bombsite-retake" \
  -a experiments.harbor_parity.agents:Web3DClaude \
  -m claude-sonnet-5 --install-only --yes
PYTHONPATH=$PWD harbor run -p "$OUT/bombsite-retake" \
  -a experiments.harbor_parity.agents:Web3DPi \
  -m opencode-go/deepseek-v4-flash --install-only --yes
```

## Paid parity rule

A paid Harbor trial is separate experimental evidence. Run it only while the formal matrix is
stopped, store it under a dedicated Harbor output directory, and pair it with an independently
identified repository-runner result through `compare.py`. One pair can detect contract drift but
cannot establish score parity.

Formal Harbor execution requires a newly frozen plan and a Harbor-backed three-family smoke
receipt. The Web3DGameBench control plane, not this experiment, materializes canonical manifests,
preserves raw traces, and enforces evaluator, barrier, Fable, closure, and publisher contracts.
