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
| `programs/pairs.json`, `programs/workloads/` (and the lecture programs' `workloads/`) | each program is a deployment; its workload is a file of its own, given when it runs, and `pairs.json` pairs them as serQ's `examples/pairs.json` does its examples | the paired-file form (`--workload`, pyserq `workload=`/`workload_source=`) |
| `programs/replay_vllm.sq`, `validation/src/sim/replay_vllm.py` | §4.2's vLLM-rule replay; `scripts/exp/serq_replay42.py` runs LRU and finished-session ablations (`research/serq-replay42.md`) | pyserq; `.serq/bin/serq` for the ablations |
| `scripts/exp/*serq*`, `diff_serq_vllm.sh`, `first_divergence.sh` | testbed comparisons and calibration; each run passes the trace with `--trace` and records what ran as IR (`program.ir.json`) | `.serq/bin/serq`, `.serq/src/examples`, `.serq/src/tools` |

The pin is `v0.1.6` under `[tool.serq]` in `validation/pyproject.toml`, IR 14, and its
pyserq, `pyserq==0.1.6` from PyPI, is the validation package's engine:
`tests/test_units.py` holds pyserq's version equal to the checkout's
`[workspace.package] version` in `.serq/src/Cargo.toml` and to the
`pyserq==` dependency, and, when a tag is pinned, the tag to `v{version}`.
`sim/serq.py` uses pyserq's
report objects and adds only numpy arrays of the samples and the pairing:
`run(path)` runs the workload `programs/pairs.json` gives the deployment,
unless the caller passes `workload=` or `workload_source=`;
`sim/workload.py` reads a trace with `pyserq.read_trace`, and `theory`
draws from `pyserq.Rng` (rand 0.9's `StdRng`). `agentic_model.sq` and
`batch_sampled.sq` name their laws, class parameters and policy keys as
expression `def`s, which the adapters give bodies with `defs=` (`--def`);
the IR is the one the spliced text had. Since v0.1.6 `sim.serq.run` splices
the bodies into the text itself (`_inline_defs`, a stopgap): in a paired
program serQ renames each file's names apart and does not rename a `--def`
body, so a body that reads a `let` (`a * size`) does not link ("unknown
name `a`"). serQ's own examples do the same
(#192): `pd_tandem` and `pd_open` name `prefill_work`, `decode_work`,
`kv_tokens`, `routing` the four session laws, and `mg1` its `service` law and
`servers`. SQT owns configurable copies in `programs/models/`; their declared
`args.number` inputs, rather than arbitrary constants, are bound by `sets=`. The one splice left is `mg1`'s
`arrive poisson(lam)` → `arrive renewal(...)`, which changes the kind of the
arrival declaration; since v0.1.6 it is made in the workload's text
(`workload_source=`), as are `agentic_model`'s and `batch_sampled`'s
`arrive closed(N)` / `arrive poisson(Lambda)`. IR 10 makes a hold's `cache` clause what
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

## Migration to v0.1.6 (IR 14)

Python, CLI and Lean pin `v0.1.6`, commit
`5d7d984a39528b67062ace7a71a6fc17efbbc21d` (2026-10-15), `pyserq==0.1.6`
from PyPI, Lean `rev = "v0.1.6"`. `lean/` needed no change: `make lean`
builds against the new `Serq` and audits 163 theorems with the standard
axioms only, and the pinned commit's interpreter and oracle IR are the
release's.

What changed in serQ, and what it changed here:

- **A program is the deployment; the workload is a file of its own**, given
  when it runs (`serq run D --workload W`, pyserq `compile(path,
  workload=…)` or `workload_source=`; serQ `docs/design/paired-workload.md`).
  A `workload` in `fn main` and a server run with no workload are refused.
  Every one of the 24 programs here is split. The layout mirrors serQ's
  (`examples/workloads/`, `examples/pairs.json`): the workloads of
  `programs/*.sq` and `programs/models/*.sq` are `programs/workloads/NAME.sq`,
  those of the lecture programs `lectures/queueing-serving/programs/workloads/`,
  that of `scripts/step_engine/prefill_only.sq` `scripts/step_engine/workloads/`,
  and `programs/pairs.json` maps each deployment (path from the repository
  root) to its workload. `sim.serq.run(path)` reads it; the lecture checker,
  `metastability_serq.py`, `sandwich_check.py` and `serq_replay42.py` pass
  `--workload`; the scripts that run serQ's own `examples/replay/vllm_replay.sq`
  (`diff_serq_vllm.sh`, `first_divergence.sh`, `calibrate_serq.py`,
  `serq_vs_vllm.py`) take its workload from `.serq/src/examples/pairs.json`.
  The text splices of the adapters (`mg1`'s renewal arrival, `agentic_model`'s
  and `batch_sampled`'s arrival kind) moved to the workload's text.
- **The server's request interface** (serQ `docs/design/request-interface.md`):
  `server (P, hidden Q) reply (R)`, the workload's `send (…)` and `reply.R`.
  The server and the scheduler's expressions read only the parameters, the
  workload only what it keeps and the reply. Every program sends its
  attributes as they are (`send (K, n, o, cold)`), which keeps the IR; the
  eviction keys of `open_vllm` and `agentic_model` read the class's `p`, `Z`,
  `nm` (`p`, `tau`, `mean_new`, `mean_out`), now parameters. `hidden o` moved
  into the signature (`pd_batching`, the lecture `vllm.sq`). Where the
  session read what the server set (`prompt` in `open_vllm`, `replay_vllm`,
  the lecture `vllm.sq`) it sums its own (`K + n + o`); `agentic_model`'s
  session reads `reply.rejected`; `metastable.sq` sends its `K` (= `K0`),
  since an input is declared in one file only.
- **Each file reads its own names, and declares an input once.** A
  workload's limit that defaulted to the deployment's pool (`maxctx`: `C / 2`
  in `agentic`, `agentic_model`, `0.5 C` in `open_vllm`, `0.9 C` in
  `replay_vllm`) is the workload's own input with the default's value; the
  adapters that set `C` also set `maxctx` (they did in `sim.agentic`;
  `sim.replay_vllm` and `serq_replay42.py` now pass `0.9 C`). A live-session
  cap (`pool live`) is the workload's pool.
- **A session's `drop kv` is the server's**: the workload sends `final`, and
  the server `if (final) { drop kv; }`. See Numbers.
- **`agg`**: `pd_batching`'s colocated engine `queue E[N] : decode` with a
  local `decode (prompt)` is `: agg` (no IR change).
- **Whole token counts** (serQ `docs/design/whole-tokens.md`): a KV pool's
  units, `cache`/`reuse`/`prefix`, an engine request's input and output must
  be provably whole. `agentic`, `agentic_model`, `lecture_pd` (both copies)
  and the lecture `vllm.sq` drew real token counts; their draws are rounded
  up, `ceil(…)` (the lecture `vllm.sq`'s output `ceil(~exp(200)) + 1`, which
  runs the decode steps the fractional `~exp(200) + 1` ran). `open_vllm`,
  `replay_vllm`, `metastable` and the step programs were whole already. The
  inline step program of `tests/test_serq_models.py` writes
  `floor(omega / a)` and `ceil(1 / a)` (`1 / a` is 49999.99999999999 in
  floating point; its 5000 iterations are unchanged).
- **IR 14**: a run's latency is its own wait, not a delay stage (#612). In
  `pd_batching` with `x0 > 0` the `D.nic.latency` stage is gone and its wait
  is in `D.nic`'s and `P.nic`'s; no observation moves.

Numbers. Each split program was run old (v0.1.5 CLI, the old single file)
against new (v0.1.6, the pair) with the same seed and inputs, `serq run
--json`. Identical, field for field: `batch_sampled` (open and closed),
`price_vllm`, `replay_vllm` (price and LRU keys, `keep_cache = 0`, `delta`),
`open_vllm` (default), `programs/models/*` (`mg1` with a `--def` law and two
servers, `pd_*` in both modes), the lecture `closed`, `mg1`, `ps`,
`pd_tandem`, `price`, `metastable` (with a burst), and `prefill_only`.
With the old file's draws rounded the same way, `agentic`, `agentic_model`,
both `lecture_pd` and the lecture `vllm.sq` are identical too, apart from
the drop below: the split, the signatures and the reordered draws move no
sample path. What moves:

- **Rounding** (by design; 10 seeds, the recorded executions). `lecture_pd`:
  TTFT 0.042942 → 0.042975 s (+0.08 %), response 0.088284 → 0.088419 s
  (+0.15 %), decode service 0.039935 → 0.040035 s (+0.25 %: `E[ceil(Exp(200))]`
  is 200.5). Lecture `vllm.sq`: TTFT 0.015899 → 0.015923 s, response
  0.062835 → 0.062871 s, hit 0.8930 → 0.8929, client TPOT 2.527e-4 →
  2.507e-4 s. `agentic` (N = 16–48, C = 3e5, 4e5): within the seeds'
  standard error (hit ±0.002, response ±1 %).
- **A finished session's KV is dropped at the end of its last request,
  before its last tool call**, where `agentic` and `agentic_model` dropped
  it after (`open_vllm` with the end known likewise; `replay_vllm` and the
  `!more` path of every program dropped right after the turn and do not
  move). The workload draws the tool time and whether it goes on before the
  request, in the order it drew them after, so the sample path is the
  same; only the dead entry's lifetime moves. `agentic`, 10 seeds, horizon
  5500: N = 16, C = 4e5, hit 0.679 → 0.729, response 5.47 → 4.83 s,
  throughput 1.895 → 2.056 turn/s; N = 16, C = 3e5, hit 0.454 → 0.478; at
  N ≥ 32 the hit rises by 0.002–0.006 and the response is unchanged within
  noise; the evicted entries fall by about 10–18 % (the dead ones). `open_vllm`,
  `keep_cache = 0`, Λ = 0.05, 8 seeds: hit 0.747 → 0.749, TTFT 41.55 →
  41.24 s, within noise.

`paper/sim/` is regenerated (`make tables`, `make figs`; Linux x86-64,
Python 3.13.16). Against the same tables generated on this machine at
v0.1.5 (the parent commit, pyserq 0.1.5), only the agentic tables and the
end-known open-session cells move, by the drop above: `tab-closed`
(N = 32: hit 0.50 → 0.52, work CV² 0.97 → 1.11; N = 16: hit 0.99 → 1.00),
`tab-offload` (hit and response by at most 0.07), the non-starred rows of
`tab-evict-dyn` and the rows of `tab-admission` (TTFT within ±0.4 s at
Λ = 0.05, the bold ties reshuffle), and `\simEvictLruRatioMax` 1.9 → 1.8.
Every other table and macro is identical to v0.1.5. The committed tables
were last generated at v0.1.3 (macOS arm64; v0.1.4 and v0.1.5 did not
regenerate them), so the diff against the parent commit also carries
those releases' sample paths: e.g. `\simEvictLruRatioMin` 1.0 → 1.7,
`\simEndKnownHit` 1.00 → 0.97, `\simEndUnknownHit` 0.59 → 0.54,
`\simTracePkRatioMin` 4 → 7, and `\simTracePkRatioMax` 12 → `inf`: in two
finite-pool trace cells (C = 4e6 cap 16, C = 2e6 cap 8) a seed's prefill
load reaches 1, so the PK mean over seeds is infinite, and
`paper/simulation.tex` would read "7 to inf times". That is a property of
the v0.1.5 sample paths (the parent commit's tables regenerated at v0.1.5
read the same), not of this migration; the sentence needs the generator to
report the finite cells. The commit after the migration does that
(`fix(report)`): the ratio is over the cells whose load stays below one in
every seed, the macros `\simTracePkFiniteCells` (6) and
`\simTracePkUnboundedCells` (2) count them, and the generator writes the
sentence (`\simTracePkClaim`) in the variant the counts call for, so the
paper reads "by 7 to 15 times in the 6 cells whose prefill load stays below
one in every seed, and without bound in the other 2", where it would have
read "by 7 to inf times". No other macro or table moved.

Why did it happen? The request interface and the paired file make explicit
what the programs here left implicit: which attributes a request carries
and which side owns a pool. The one change of model is the drop: a
deployment's KV is the server's to drop, and the server knows the session
ended only when its last request says so. The old timing, a dead entry
kept through a last tool call, is not expressible without a request after
that call; the validation package's rule ("frees a finished session's
KV") holds either way. The rounding is serQ's whole-token check finding
fractional counts the programs drew; the ceilings are the rounding the
engine applied to a fractional output's last token anyway.

The `--def` stopgap (`sim.serq._inline_defs`) is the one place this
repository works around v0.1.6; the change it waits for is serQ renaming a
`--def` body with its def's file in a pair.

## Migration to v0.1.5 (IR 13)

Python, CLI and Lean pin `v0.1.5`, commit
`8a578475b9447749ab8962c413175854886a19bc` (2026-10-13). A step stage is
written only as an engine (`engine E on gpu { tokens cap …; scheduler { … }
worker { forward (…); } }`), which keeps a request's state, admits it,
and is called by the server, `E (input, output);`; the server no longer
runs an engine's prefill or decode itself. `branch (e)` is `if (e)` and
`branch with (p)` is `if (~bernoulli(p))`. `use` reads only `std/…`, so
`lectures/queueing-serving/programs/vllm-library.sq` is inlined into
`vllm.sq` and `metastable.sq` and deleted. A declaration may not share a
name with the language or an attribute, nor an observation with an
attribute, so programs rename `think` (`user`, `thinking`), `batch`
(`slots`), `size` (`prompt_len`), `forced` (`forced_miss`), `engine`
(`replica`, `vllm`), `service` (`service_time`) and the observed `think`
(`think_time`). The CLI takes inputs as `--name value`; every script that
ran it is changed.

Numbers. serQ #493 mixes the seed before a session's serial: under v0.1.4
seed `s` and session `i` drew from a stream close to `s + i`, so
consecutive seeds were not independent replications, and every seed-1
sample path changes. The ports were compared old against new with
independent seeds (spaced 1,000,003 apart) and, for the vLLM family, with
the draws replaced by deterministic functions of serial and turn.
`programs/models/*`, `lecture_pd`, `agentic`, `agentic_model`,
`batch_sampled`, `price_vllm` and the lecture `vllm.sq` agree within their
intervals; deterministic runs without preemption are identical. Two
programs change their model where the old form has no equivalent:

- `open_vllm.sq`, `replay_vllm.sq`: the per-turn overhead `c0` was a
  separate prefill run of `ceil(c0/a)` tokens issued by the server, which
  took budget, grew no KV and, as a side effect, delayed each admitted
  turn's KV growth by one iteration. It is now time in the admitting
  iteration (`state newcomers; set newcomers = waiting.admitted;`, added
  to `forward`). With `c0 = 0`, `open_vllm` matches v0.1.4 to the digit,
  eviction and preemption included; with `c0`, TTFT moves by 0–6 %. In the
  replay with a finite pool, the old one-iteration delay let `reserve`
  admit turns against a low `used`; without it, preemptions fall (C = 1e6,
  cap 4: 14.7 → 0.6) and the slots wait rises by 20–47 %. The paper's
  §4.2 finite cells are generated tables and are not regenerated in this
  migration.
- `metastable.sq`: the library's hold consumed the session's whole cached
  entry (`cache` without `reuse`). The engine prefills `known − cached`, so
  the hit is bounded by `reuse (floor(request.known − 1, blocksize(kv)))`,
  as serQ's `vllm.sq` does, and the excess stays a dead entry, as in vLLM.
  Deterministic Z = 4: full-hit share 0.378 → 0.371, TTFT +3.6 %; Z = 1.5
  identical.

Under preemption only, serQ's engine differs from what the v0.1.4
programs wrote: a preempted request keeps its generated tokens (#478),
and per-admission observations (`hit`, `kind`, `work`) are made once per
turn, from the last admission.

Why did it happen? The v0.1.4 programs wrote vLLM's per-request steps in
the server, so the overhead run and the whole-entry hit were rules a
program could get wrong without the language noticing. serQ now keeps the
request's state in the engine and refuses the server form. No check here
applies; the port records the two changes of model above.

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
   Today all three pins are the release v0.1.6 (`rev = "v0.1.6"`). The oracle theorems are
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
