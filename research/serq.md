# serQ: the serving-deployment language, and how this repository uses it

serQ is the language in which a serving deployment is a program: memory
pools and stages, a workload, and the program every session runs. Since
2026-09-27 it is its own project, https://github.com/servingQ/serQ (public, in
the `servingQ` organization, since 2026-10-02; it was the private `vrvrv/serQ`).
serQ holds the Rust interpreter and CLI (crate `serq`, library `serq`,
binary `serq`), the example programs (`examples/*/*.sq`, incl. the vLLM
v1 engine and its A100 replay), the vLLM scheduler oracle with its test
vectors (`tools/oracle/`, the A100 engine's answers), the language spec
(`docs/language.md`) and the review and tooling survey (`docs/review.md`).
serQ also holds the Lean model of the language (its `lean/` package
`Serq`, serQ `docs/lean.md`, since 2026-10-01; before that it lived here).
The Lean `Route` type and `[route| … ]` quotation are names in that formal
fragment, not the current serQ surface syntax.

A serQ program is defined by its IR (serQ `docs/ir.md`): a versioned JSON
data structure that the interpreter runs and tools build or edit. The text
syntax compiles to it. This repository requires serQ's Lean package and
proves its queueing results from it, and uses one pinned serQ release:

| Here | What it is | What it takes from serQ |
|---|---|---|
| `lean/lakefile.toml` (`[[require]] Serq`) | serQ's Lean package at a pinned commit: `Serq/Core` (syntax, pool semantics, invariant), `Serq/Exec` (executable semantics, ℕ step clock), `Serq/Serve` (serving order, cited in §2.2), `Serq/Oracle` (the vLLM scenarios as theorems, generated in serQ from `tools/oracle/*.ir.json`) | serQ `lean/`; its own `make lean` builds and audits it |
| `lean/ServingQueueTheory/Deployments.lean` | the paper's two replicas as serQ programs | `Serq.Core` |
| `validation/` | the validation package: every simulation of the paper as a serQ program (`src/sim/`), checked against closed forms that never import serQ (`src/theory/`); `tests/test_serq_models.py` checks serQ programs against closed forms | pyserq (PyPI, the pinned release), `.serq/src/examples` |
| `programs/replay_vllm.sq`, `validation/src/sim/replay_vllm.py` | §4.2's vLLM-rule replay; `scripts/exp/serq_replay42.py` runs LRU and finished-session ablations (`research/serq-replay42.md`) | pyserq; `.serq/bin/serq` for the ablations |
| `scripts/exp/*serq*`, `diff_serq_vllm.sh`, `first_divergence.sh` | testbed comparisons and calibration; each run passes the trace with `--trace` and records what ran as IR (`program.ir.json`) | `.serq/bin/serq`, `.serq/src/examples`, `.serq/src/tools` |

The pin is `v0.1.4` under `[tool.serq]` in `validation/pyproject.toml`, IR 12, and its
pyserq, `pyserq==0.1.4` from PyPI, is the validation package's engine:
`tests/test_units.py` holds pyserq's version equal to the checkout's
`[workspace.package] version` in `.serq/src/Cargo.toml` and to the
`pyserq==` dependency, and, when a tag is pinned, the tag to `v{version}`.
`sim/serq.py` uses pyserq's
report objects and adds only numpy arrays of the samples,
`sim/workload.py` reads a trace with `pyserq.read_trace`, and `theory`
draws from `pyserq.Rng` (rand 0.9's `StdRng`). `agentic_model.sq` and
`batch_sampled.sq` name their laws, class parameters and policy keys as
expression `def`s, which the adapters give bodies with `defs=` (`--def`);
the IR is the one the spliced text had. serQ's own examples do the same
(#192): `pd_tandem` and `pd_open` name `prefill_work`, `decode_work`,
`kv_tokens`, `routing` the four session laws, and `mg1` its `service` law and
`servers`. SQT owns configurable copies in `programs/models/`; their declared
`args.number` inputs, rather than arbitrary constants, are bound by `sets=`. The one splice left is `mg1`'s
`arrive poisson(lam)` → `arrive renewal(...)`, which changes the kind of the
arrival declaration. IR 10 makes a hold's `cache` clause what
consumes the session's own cached prefix (serQ #234: a hold without it
leaves the entry where it is, so a reservation written around the
request's hold on the same pool no longer costs it its hit; `cache (0)` is
the old meaning); the Lean `admit` follows, and no program here
holds a pool with entries without `cache`, so the oracle theorems and the
validation numbers are unchanged. IR 9 orders a
pool's waiting queue when a request is selected; no program here uses
`queue by`, so their FIFO queues keep their meaning. IR 6 added renewal
arrivals and requires finite runs to finish within their horizon; the queue
adapter retries deadline errors with the same seed and a larger horizon
(up to eight attempts). The oracle generator rejects finite arrival limits
and renewal workloads outside its explicit-session fragment. `scripts/fetch_serq.sh`
(`make serq`, first step of `make check`) checks that tag out into
`.serq/src` and installs its CLI into `.serq/bin/serq` (gitignored); `uv sync` in
`validation/` installs pyserq from PyPI, so the validation package needs no
Rust (the CLI, for `scripts/exp`, still does).

## Migration to v0.1.4 (IR 12)

Python, CLI and Lean pin `v0.1.4`, commit
`a99dd649e9353c326ef95311ecdaa3c99a242c85`. Workloads specify request
sizes, servers convert them to resource-bound costs, and `turn;` completes
one server invocation. Models have an explicit `fn main`; execution
conditions belong to the caller. SQT owns configurable copies of the six
release examples it uses, in `programs/models/`. Their `args.number`
inputs replace the former ability to override arbitrary constants.

Before (`programs/agentic.sq` at the previous SQT commit):

```serq
    turn;
    set t0 = now;
    hold slot (1) {
      hold kv (K + n + o) {
```

After (`programs/agentic.sq`, executed by the model comparison tests):

```serq
    session {
      loop {
        turn;
        set K = K + n + o;
```

The serving operations now reside in `server`, whose corresponding header is
`hold slot (cost(slot, 1)) { hold kv (cost(kv, K + n + o)) { ... } }`.
Each primitive resource operation converts its quantity at the original
evaluation moment. A multi-pool hold's cache/reuse is one scalar joint
cost; its reservation still targets only the reserved pool.

`programs/executions.json` records the previous horizon, warmup and seed for
each owned model. Tests select a configuration with `sim.serq.execution`;
the lecture checker selects it by its explicit model path. The Python run
wrapper never loads execution defaults. Testbed replay commands explicitly
pass the release example's former horizon 6000, warmup 0 and seed 1.

The independent Lindley comparison retains its pathwise `1e-8` bound and
init-stream seed derivation. Short paired runs at seed 1, horizon 1000 and
warmup 100 have identical reports apart from version for `agentic`,
`agentic_model`, `batch_sampled` and `lecture_pd`. Price and open models
previously had no turn boundary: their turn counts change from zero to
completed requests. For `open_vllm` the same paired run changes mean ITL
from 0.0782521 to 0.0590953 seconds; other serving/pool/observation results
are unchanged. The interpreter measures token gaps only within the same
turn, so explicit request boundaries exclude tool waits that the old
all-turn-zero model included. This is simulated output, not measurement.

Why did it happen? The old open model assumed that repeated server work
implicitly created request boundaries. A generic loop does not express
those boundaries. A language check cannot infer that every loop iteration
is a request; the migration now states it with `turn`. Separately, array
sizes are parsed before input binding, so `stage rep[J]` cannot take an
input override even when J is four. The language already rejects this.
Routing retains its fixed four-replica topology and existing adapter guard,
and no longer sends J as a runtime input.

Physical measurements are unchanged. Generated paper simulation tables remain
the recorded v0.1.3 evidence. This migration updates executable models and their checks;
it does not retroactively regenerate measurements or claim new testbed runs.

Validation: 145 Lean theorems audited with only standard axioms, 51 unit
and adapter tests, 35 named model checks and 21 lecture checks. The
oversized-request regression exercises the rejected server response before
any service or KV allocation. Paper and lecture PDFs compile.

## Migration to v0.1.3 (IR 11)

Python, CLI and Lean now pin `v0.1.3`, commit
`d91ffa5608f2ecb4b9ef92b3a0083fe9d70c8612`. A seed names a workload:
service draws in `mg1.sq` use each session's init stream rather than one
shared service stream. `theory.queue` reproduces the documented SplitMix64
seed derivation, then computes waiting times with Lindley's recursion;
the existing pathwise check retains its `1e-8` bound.

The Lean fill theorem now requires `D.only = none`. The paper's
`serq_machines_lower` exposes that hypothesis: every resident participates
in the greedy fill. Its conclusion and the paper's queueing assumptions
are otherwise unchanged. `make lean` checks the dependency against the
same interpreter and oracle IR as the CLI pin.

The PS example's high-variance law (CV² = 9) at seed 5 gave mean number
2.1612 over horizon 250,000, versus the theoretical 2.3333. At horizon
2,500,000 with warmup 250,000 it gives 2.3518. Seeds 3 and 7 give 2.3522
and 2.3489 at the longer horizon. The unit and lecture checks use the
longer run for all three laws, retaining their 3% and 6% bounds. The wrong
assumption was that the old finite run would meet the same error bound
after changing its samples. No language check can guarantee a stochastic
estimate's precision; the external checks continue to fail loudly when
the estimate misses its bound. The old Lindley stream assumption was
also in this repository's checker, not an invalid serQ program.

The corpus contains 12 zero-output turns. `replay_vllm.sq` had assumed
`out >= 1` and passed `out - 1` to decode. IR 11 correctly rejects -1;
the program now states `max(out - 1, 0)`, preserving the former zero-work
behavior explicitly. The regression uses the first such WEKA row
(session 20, turn 77) and checks that completion equals prefill completion.
The input is external trace data, so the linker cannot establish that
bound; the runtime already fails loudly. The existing cache policy is
unchanged.

`paper/sim/` is regenerated on macOS arm64 with the published PyPI wheel
and Python 3.13.11, including figures drawn from its CSV files. Linux CI
checks the same models and bounds; libm can change individual trajectories.
All 35 model checks pass in the regenerated tables. In the synthetic
admission sweep no seed meets the recorded thrashing criterion now;
the higher-load hit-rate/latency degradation remains. LRU matches the
other orders at the lower load and costs about 1.6 times their TTFT at
the higher load. The paper now describes those observations rather than
the old synthetic thrashing claim. The trace replay's open-price
lower bound overstates the observed rise by about 3–13 times (formerly
4–10); those numbers remain generated macros. The current lecture checks are recorded in
`research/serq-0.1.3-lecture-results.json`. Lecture 7's five-seed cold/warm sweep and burst experiment are also
rerun with this release (`scripts/metastability_serq.py`); the JSON now
records the binary's actual version instead of a hard-coded v0.1.0 label.
The cold/warm gap is at most 0.020 and recovery after a 60-second burst is
65 seconds (formerly 40), while the 300-second burst still recovers in
50 seconds. Its dependent calibration and figures are regenerated from
that record. The scientific Python environment is numpy 2.5.3, scipy
1.18.1 and matplotlib 3.11.2. The older
`research/lecture-results.json` and appendix comparison table retain the
releases they actually measured; the appendix labels that comparison as
historical.

## Moving to a new serQ release

1. In serQ: bump `version` in `Cargo.toml`, push, then
   `git tag -a vX.Y.Z-rcN && git push origin vX.Y.Z-rcN` (or `vX.Y.Z`); the tag message body is the release notes.
   The release workflow runs the checks and publishes the GitHub release
   (a tag with a dash is a prerelease).
2. Here: change the tag under `[tool.serq]` (drop a `rev`, which wins
   over it) and the `pyserq==` version in `validation/pyproject.toml`
   together; `tests/test_units.py` fails unless pyserq, the checkout's
   `Cargo.toml` version and the tag are one version (a prerelease `vX.Y.Z-rcN` has no
   PyPI wheel: point `[tool.uv.sources] pyserq` at `../.serq/src/pyserq`
   meanwhile), `uv lock`, then `make check` (`make serq` checks out and
   builds the new release). Move the Lean pin with it: set `rev` of the
   `Serq` requirement in `lean/lakefile.toml` to the release's commit and
   run `cd lean && lake update Serq`. The Lean pin may run ahead of the
   release only in `lean/` and docs: `scripts/check_lean.sh` fails if the
   pinned commit's `src/` or `tools/oracle/` differs from the release tag.
   Today all three pins are the release v0.1.3 (`rev = "v0.1.3"`). The oracle theorems are
   regenerated in serQ (`scripts/gen_lean_oracle.py`, checked by its
   `make lean`), not here.

In serQ, the multi-turn prefix-cache theorem is generated the same way: its IR
(`tools/oracle/cache_trace.ir.json`) is `examples/replay/vllm_replay.sq` on a
unit step clock with the trace inlined as the sessions' turns, and the
Lean executable semantics reads those turns at every `turn` statement
(`Exec.Workload`) with serQ's rule.

## Access

serQ is public (since 2026-10-02): Lake (`lean/lakefile.toml`) and
`scripts/fetch_serq.sh` fetch it over https without credentials, and CI needs
no key. The read-only deploy key and `.github/actions/serq-access` that the
private repository needed were removed; the secrets `SERQ_DEPLOY_KEY` and
`SEQ_DEPLOY_KEY` can be deleted from this repository's settings.

## Historical evidence

The experiment directories `data/exp/seq/`, `data/exp/gpu_seq/` and
`data/exp/gpu/seq*` keep their acquisition names. They are external measurement
and comparison artifacts, not runtime names. Analysis scripts still read them;
renaming the source data in prose would break reproducibility.
`research/lecture-results.json` likewise records the previous CLI's actual
binary name and commit. The optional baseline verifier reads that release's
`.seq` source files. Current programs, commands and documentation use serQ and
`.sq`; the baseline metadata is not a claim about today's runtime.
