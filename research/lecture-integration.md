# Unified lectures and serQ v0.1.0 verification

Date: 2026-09-30. The sole course entry point is
`lectures/queueing-serving/notes.tex`; the two preceding source directories
were removed. The public PDF, README and publication artifact now use
`queueing-serving.pdf`.

## Scope and structure

Chapters 1–4 retain the common probability/queueing foundations once,
including the primer's renewal-reward proof and the PD course's Erlang-C
proof. Chapter 1 keeps both architectural diagrams and the PD sample-path
derivation, stated as a continuous analytical model. Chapter 5 develops the
colocated scheduler; chapter 6 adds the PD transfer price, two-pool shadow
prices and feedback. The repeated variance split and holding-time proof
were replaced by cross-references. All old Route/type/grammar exposition
was removed; the course's executable language is serQ v0.1.0.

## Release and reproducible checks

The release tag resolves to commit
`f9fe9f2cad9e7d88e585860572c3757c295d58c6`, package `serq` version 0.1.0,
IR version 9. Primary release sources read for this change:
`Cargo.toml`, `docs/language.md`, `docs/ir.md`, `src/lib.rs`,
`lib/vllm.sq`, `examples/multi-turn/vllm.sq`, and the pool/PD/preemption
and vLLM-oracle tests. The local tag's clean archive was used rather than
the neighboring repository's dirty working tree.

```sh
make serq
make lecture-results
make check
```

The course uses the existing serQ v0.1.0 pin in
`validation/pyproject.toml` and the existing `scripts/fetch_serq.sh`.
The same release supplies the corpus, CLI, and paper validation. This PR
adds a course check rather than a second fetcher or a separate runtime pin.

The previous-runtime comparison can be reproduced with:

```sh
python3 scripts/check_lecture_results.py \
  --serq .serq/bin/serq \
  --baseline "$BASELINE_BIN" \
  --baseline-source "$BASELINE_PROGRAMS" \
  --out research/lecture-results.json \
  --tex lectures/queueing-serving/results.tex
```

Set `BASELINE_BIN` to the old rc0 CLI and `BASELINE_PROGRAMS` to its
`programs/` directory. They come from the `v0.1.0-rc0` tag in the language
repository and are not installed by the current fetcher. The recorded
comparison was run against that preceding release; no old-language
exposition is retained in the course. The JSON is raw simulation evidence;
`results.tex` is generated from it, not typed by hand. The current-only CI
check writes `/tmp/sqt-lecture-check.json` and leaves the historical table
intact. The runtime source suite was also run with
`cargo test --release --locked -p serq`: **222 tests passed**, including
recorded vLLM scheduler scenarios, prefix-cache, pool, PD-transfer and
preemption cases. These are recorded oracle comparisons, not new GPU runs.

## What changed

The old continuous PD program declared `ps(min(n, phi_cap))`, but also
assigned a workload attribute named `n`. The previous linker's variable
resolution (`src/link.rs`, `expr`) checks attributes before context
variables, so this did not read the station population. New-token counts
were normally above 16 and the expression effectively returned the capped
throughput 16 even when only one turn was decoding. Its per-turn rate was
then 16 instead of 1.

In the v0.1.0 port, the capacity is `ps(min(present, phi_cap))`. Decode work
is `o*w` with mean `200 * 0.0002 = 0.04` seconds. The verifier asserts this
mean at three seeds; it would reject the old roughly 0.0025-second result.
The generated table records TTFT near 0.043 seconds on both versions,
response near 0.051 versus 0.089 seconds, and decode service near 0.0025
versus 0.040 seconds. Different holding times affect closed-loop timing,
so identical random seeds do not imply identical trajectories.

The current release also requires distinguishing a time-only `run link`
from `transfer ... from ... to ...`, which loads computed KV at the
destination and releases the source. `lecture_pd.sq` deliberately runs the
continuous analytical tandem, whose destination admission follows transfer.
The production operation can hold both allocations during transfer and
back destination pressure into the source. The notes explain this difference
rather than applying the old sample-path equations to a new lifetime.

The vLLM example uses the release's shared request definition, explicit
client/server blocks, hidden output length, block reuse, admission-time
cache lookup, and generated-token-aware preemption/resume. PS and step
context names use `present`, `tokens`, `attention`, `decoders`,
`kv_decode` and `kv_prefill`. The underlying tests cover these semantics.

## Which results survive

The verifier passes **18 executable checks**, plus recomputation of the
nonlinear feedback roots and three previous-runtime comparisons:

- FIFO PK under deterministic, exponential, Erlang-4 and H2 work.
- PS mean occupancy under deterministic, exponential and H2 work.
- Finite-source MVA at populations 2, 8 and 32.
- PD saturated bottleneck throughput for three splits and a slow link.
- PD decode-service and TTFT decomposition at seeds 1, 2 and 3.
- A step-engine miss-price comparison at the calibrated cost constants,
  unlimited KV, Poisson turns, an explicit full-prompt gate, and 1% forced
  misses. The occupancy rise is about 0.1432 within the approximate FIFO
  bracket [0.1422, 0.1497]; decode occupancy changes by about 0.056%.

Finite-run tolerances are in the verifier. They test agreement in the named
regimes, not arbitrary deployments. The feedback example's computed roots
remain 0, 0.24964 and 0.88200 at rate 0.25, and 0.88483 at rate 0.18.
The mathematical PK/PS/MVA/threshold/duality/fixed-point statements retain
their explicit assumptions. The paper proof build and standard-axiom audit
are checked separately; they do not certify every serQ IR-v9 construct.

Several descriptions were corrected without changing those conditional
results: tail-block recomputation is concave rather than a linear fractional
item; binary hit/miss moments cannot be reused unchanged for partial hits;
FIFO price claims depend on the engine's serving order; Erlang-C memory-slot
predictions need independent exponential holding times and Poisson arrivals;
and pinning changes available capacity as well as prefix survival. Historical
pinning-cliff numbers lacking current-release reproduction were removed.
The holding-time formula now explicitly assumes positive memory price,
handles zero price separately, and defines the hazard after its survival
probability vanishes.

## Final validation

On the PR branch rebased onto the current `main`, `make check` passed:
`Build completed successfully (3111 jobs)`;
`OK: 120 theorems audited; only standard axioms used.`;
`checked 59 \leanref citations`;
`49 passed, 35 deselected`;
`OK: validation, 35 checks, 0 failed`;
`OK: 18 lecture checks; feedback roots verified; 0 baseline comparisons`.
The separate preceding-runtime comparison completed three seeds and generated
`results.tex`. The unified PDF builds to 60 pages, has no unresolved references or
old-language terms in extracted text, and its figures were visually inspected.

The PD TTFT statements explicitly use first-token production at the prefill
endpoint. Client delivery after KV handoff can also include transfer and
destination waiting; that is not the same metric as the example's observation.

`make site` and the final `mkdocs build --strict` passed. The generated
site links only the unified course PDF, whose bytes match the current
lecture build. No remote publication was performed.
