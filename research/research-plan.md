# Research plan

Working reference for humans and coding agents. It records what the paper
claims, what is proved, what is pending, and in which order validation
should happen: simulation first, then empirical measurement (§4). Update it when the status of a result or experiment
changes. The paper (`paper/main.tex`) is the public statement. This file is
the internal plan and may be blunter.

Last updated: 2026-10-06.

## 0. Where we are / next steps (read this first in a new session)

Experiment names (2026-09-26, user request; the paper never uses the
codes): **cost fit** (E1), **long-context replay** (E2), **short-context
replay** and **price test** (E2b), **offloading test** (E3), **eviction
replay** (E4), **placement test** (E5), **faithfulness scoring** (E6).
The codes survive in directory names (`data/exp/e1`, `e2`, `e2b`),
macros (`\eOne*`, `\eTwo*`, `\eTwob*`) and older review files.

Current integration state as of 2026-10-06. Dated measurement entries below
record the runs made at that time; they do not imply a server is still running.
Keep this section current at the end of every work block.

**Done.**
- **serQ v0.1.4, IR 12 (2026-10-06).** Python, CLI and Lean pin the published release `a99dd64`. Models declare named inputs, workloads own request sizes, and servers convert them to resource costs. Client `turn` completes server execution; previous execution settings are selected externally. Lindley's exact comparison and the existing statistical bounds are retained. Open-session ITL now excludes cross-turn tool waits; historical generated paper results remain recorded evidence. Details and validation: `research/serq.md`.
- **serQ v0.1.3, IR 11 (2026-10-05).** Python, CLI and Lean pin the
  published release `d91ffa5`. Lindley's independent check follows the
  session-local init stream; `serq_machines_lower` exposes the fill
  theorem's no-filter assumption. A real zero-output trace row now has
  explicit zero decode work and a regression. PS checks run longer with
  their error bounds unchanged. Paper tables/figures and the current
  lecture checks use the release; the paper drops the synthetic
  thrashing claim that the new samples no longer support. The older
  lecture comparison remains historical. Validation: `make check`, 145
  audited theorems, 50 unit/adapter tests, 35 model checks and 21 lecture
  checks. Details and numerical changes: `research/serq.md`.
- **serQ v0.1.2, both repositories public (2026-10-02).** serQ and this
  repository moved to the `servingQ` organization and are public. serQ
  v0.1.2 (IR 10, interpreter unchanged) carries the Lean model (`lean/`),
  event-driven `Exec` with iteration costs, three Lean/interpreter
  differences fixed by differential testing (`make drt`, in serQ's CI), and
  `Serq/Fill.lean`; this repository requires it (`lean/lakefile.toml`) and
  `StepEngine.lean` derives a FIFO lower bound from serQ's iteration fill
  (`serq_machines_lower`; run invariants still assumed,
  `research/step-engine-theory.md`). All pins moved to v0.1.2 then; the deploy key is
  gone.
- **Decode scaling identity, issue #28 theory (2026-10-01).**
  `DecodeScaling.lean` separates the PD throughput no-gain (`prop:pd`,
  capacity only; its doc comment now says so) from decode latency at equal
  throughput: for the PS decode stage, scaling the arrival rate and the
  capacity function by one factor keeps the stationary law and the mean
  number and divides the mean sojourn by that factor (Little), so one
  dedicated decode engine `(λ/f, φ)` has the colocated engine's `(λ, fφ)`
  occupancy and `f` times its sojourn; the token-weighted TPOT scales
  with it, the request-weighted TPOT only for a fixed output length
  (two-point counterexample). `psMeanNumber_anti_share` (any capacity
  function, via `stationaryMean_mono`) and `psNum_anti_capacity` record the
  limit: a miss adds no decode demand, but an exclusive prefill step lowers
  the decode capacity, which raises the mean number; §2.2's decode
  paragraph says which step rule `prop:decode` assumes and what the other
  does. Conditions (constant share, Poisson arrivals
  at the decode station, split-independent work law) are in the module's
  doc comment.
- **Colocated vs split in the validation checks, issue #28 execution
  (2026-10-01).** `validation/src/sim/pd_batching.py` runs
  `programs/models/pd_ps.sq` and `pd_batching.sq`, adapted from the
  pinned release's examples (serQ #208; ported to v0.1.4 on 2026-10-06,
  the PS identity's runs lengthened to 3000 s) through pyserq;
  four checks and one observation in `checks.py`: the PS identity in model
  (occupancy ρ/(1−ρ) kept, decode time and token-weighted TPOT ÷ 4 at
  N = 4, f = 1/4); the step engines beyond it (same requests, same output
  throughput, split TPOT below and TTFT above colocated at λ = 20–70, the
  gap growing with load); the 10 ms-step regime where the ratio is
  1/(1−p) within 5 %; exclusive vs mixed vs chunked steps at the same
  prefill share (TPOT 25.7 → 19.7 → 13.0 ms against the split's 10.6 at
  10 ms); and, not asserted, the transfer in the TTFT, a decode engine or
  colocated engines short of KV, and prompts of CV² 9 (300 s runs near
  saturation are not steady-state means). Runs are stable only if they
  kept up with their arrivals; 3–5 seeds with Student-t intervals;
  the multi-turn and closed-session comparison stays in serQ's
  `tools/pd_batching/sessions.md` and is not rerun here. Simulation, not
  measurement.
- **PD docs and metrics, issue #28 (2026-10-01).** `paper/pd-followup.tex`
  limits the equal-capacity latency result to the FIFO tandem without
  batching (the pooling baseline) and defines the follow-up's metrics;
  `research/simulation-design.md` says the same; the lecture's
  `lecture_pd.sq` records the client-visible TTFT (`ttft_client`) and the
  transfer apart from the prefill-instance TTFT (`ttft`, unchanged, the
  checker's), with the course text (ch. 6 TTFT paragraph, ch. 5's
  exact/approximate list, ch. 2's serving note) saying which step rule the
  decode claims assume; §4.2b and §5 of this plan record what not to
  generalise.
- **serQ v0.1.1 pinned, IR 10 (2026-10-01).** The pin moved to the release
  that fixes the overlapping-hold bug Lecture 7 ran into (serQ #230: a hold
  without `cache` now leaves the session's prefix where it is; IR 10, same
  shape). Companion here: `scripts/gen_serq_oracle.py` reads 10,
  `SerqExec.lean`'s `admit` consumes the own prefix only with a `cache`
  clause, `SerqOracle.lean` regenerates to the same file (no oracle
  program holds a pool with entries without `cache`, so the theorems are
  unchanged). (These three files are now in serQ's `lean/`, PR #34.) Also from the release: `serq --version` and `serq_version` in
  the report, a note on a test observe that never held, and the linker
  rejecting a `set present` (serQ #231, the course's old `n` accident).
- **Metastability, Lecture 7 (2026-10-01, serQ #120; lecture note only, not
  the paper).** Serving results proved in Lean (`CacheOrder.lean`,
  `Metastability.lean`): saturated rounds (LRU 0 hits, any rule ≤ `C`, pinning
  `C` attains it; Mattson's criterion as cited prose), the closed FCFS–LRU
  replica (congested queue `N − Z/S_miss`, admission rule `N ≤ C + Z/S_miss`,
  which binds at Z* ≈ 2.5 s, inside serQ's cliff, with C the whole pool), admit-then-hold (barriers at or
  below the batch cap). Experiments after Alvaro et al. (arXiv:2510.03551):
  failure in time, drift, recovery, region (bistable with ≈ one context per
  waiting turn), serQ on vLLM's rules (cliff, no hysteresis), calibration
  (PS chain fails; a one-at-a-time chain fits partly). serQ issues #230–#232.
  Record: `research/metastability.md`. Lecture 6's Tarski proposition is now
  titled "Knaster–Tarski".
- **serQ naming and integration cleanup (2026-10-01).** Runtime notes,
  experiment entry points and review filenames now use `serq`; references
  follow the renames. Removed obsolete Cargo/Rust paths, completed-work
  next steps and whole-session-replica summaries from current instructions.
  Corrected section/appendix mapping and the block-prefix threshold caveat.
  Acquisition paths and previous-runtime metadata remain historical evidence;
  CI prefers `SERQ_DEPLOY_KEY` with the provisioned secret as fallback.
  Validation: `make check` passed (120 audited theorems, 59 paper citations,
  49 unit/adapter tests, 35 simulation checks, 21 lecture checks). The renamed
  comparison entry point replayed 3 321 turns with the pinned serQ runtime.

- **Unified lecture course (2026-09-30).** The primer and PD notes are now
  `lectures/queueing-serving/notes.tex`: common theory once, colocated and PD
  applications in chapters 5–6. All obsolete Route/type/grammar exposition
  removed from the course. Executable examples target serQ v0.1.0, IR v9,
  using the existing pin in `validation/pyproject.toml`; `make lecture-results`
  verifies them. A preceding PD program had its PS capacity variable
  shadowed by a workload attribute: decode service changes from about 2.5 ms
  to 40 ms, response from about 51 ms to 89 ms, while TTFT stays near 43 ms.
  The record is `research/lecture-integration.md`; raw comparison evidence
  is `research/lecture-results.json`. The paper measurements
  remain on their existing data; these are course simulations.

- **serQ v0.1.0 pinned, pyserq from PyPI (2026-09-30).** `validation`
  installs `pyserq==0.1.0` from PyPI and checks out serQ `v0.1.0` for the
  example programs, the oracle IR files (IR 9) and the CLI; a test holds
  the two to one release (`research/serq.md`). On the way (rc6–rc8) the
  package dropped its copies of what pyserq now has: the report classes,
  the trace parser, the port of rand's `StdRng` (`pyserq.Rng`), and most
  program-text splices (named `def`s given with `defs=`). `paper/sim/` is
  byte-identical throughout.
- **Validation in Python (2026-09-29).** `validation/` is a Python package
  (uv, `validation/pyproject.toml`), no longer a Rust crate: every
  simulation is a serQ program run in process by pyserq (the Python
  binding of the pinned serQ release), and the package
  keeps configurations, closed forms, offline eviction instances,
  statistics and table generation. It reproduces the crate bit for bit
  (rand 0.9's `StdRng` and Rust's number formatting ported): the report
  and every file of `paper/sim/` are unchanged apart from the generator
  line. pyserq comes from PyPI (`pyserq==0.1.0`); Rust is needed only for
  the serQ CLI of `scripts/exp`. `make tables`
  regenerates `paper/sim/` (~7 min); `make sim` runs ruff, pytest and the
  report (~5 min).
- **serQ integration (current).** The language is a separate project,
  https://github.com/servingQ/serQ. This repository runs its pinned v0.1.4
  release (IR 12) through pyserq and `.serq/bin/serq`, not a Cargo git
  dependency. `research/serq.md` documents the pin, upgrade procedure and CI
  access. The Lean model is serQ's `lean/` package (since 2026-10-01; it
  was `Serq{,Exec,Oracle,Serve}.lean` here), required by `lean/lakefile.toml`;
  serQ's `scripts/gen_lean_oracle.py` generates the oracle statements from
  its IR, and its `scripts/test_lean_oracle.py` checks the translator's
  accepted fragment. This proves the named fragment, not every IR-v11 feature.
- **vLLM-rule paper simulations (ported 2026-09-27).** The price,
  eviction/admission and WEKA replay experiments run
  `programs/{price,open,replay}_vllm.sq` through
  `validation/src/sim/{price,open,replay}_vllm.py`. `make tables` generates
  the paper's tables and macros. The old `TwoStage` server, whole-session
  replay and Rust cross-checks were removed. Block eviction gives partial
  misses, so the replay reports reused-prefix share alongside hit rate;
  the price check allows the small decode-occupancy change of shared
  iterations rather than asserting it is zero.
- **Scheduler comparisons (recorded 2026-09-27).** Differential replay
  identified admission, reuse and release-order gaps and matched the
  request decisions on the recorded short-context trace. The review record
  is `research/reviews/2026-09-27-serq-round*.md`. The Lean oracle covers
  the deterministic scenarios and the multi-turn cache trace; it is not a
  proof of arbitrary production runs. Historical A100 comparisons and the
  waiting-prefix pinning experiment remain experimental evidence, not
  current-release measurements. The Lambda instance was terminated after
  those runs. Their acquisition paths retain `seq` in the directory names
  (`research/serq.md`, "Historical evidence").
- **Replay ablations (recorded 2026-09-27).**
  `research/serq-replay42.md` and its generated tables compare the paper's
  vLLM-rule configuration with LRU and dropping finished-session blocks.
  `scripts/exp/serq_replay42.py` reruns these ablations. End-of-program
  information matters to the priced eviction key. The superseded comparison
  against whole-session eviction is available in git history; it is not a
  second current paper replica.
- **Open runtime research.** Identify served overhead constants using
  synchronous versus asynchronous scheduling; validate the pool core with
  Kani/Aeneas against the formal fragment. The old requests for an executable
  Lean semantics and for the vLLM replay port are complete and no longer
  next steps. Further runtime work belongs in the serQ repository.
- Paper v0.13 (2026-09-26, after the user's feedback and a clarity
  review `research/reviews/2026-09-26-clarity.md`): §4 renamed "Results"
  (4.1 real-world traces, 4.2 simulation, 4.3 testbed); a "Background"
  paragraph opens §2 (prefill, decode, KV cache, prefix hit/miss,
  chunked prefill); abstract and contributions rewritten in plain
  sentences; notation cleaned (batch size `m`, hit rate `h`, prefill
  load `ρ = λE[S]` defined after (2), `v_i` used in §3.1, `T_s` for the
  session lifetime, `ℓ, σ` in the SF proof); the transient-eviction
  caveat moved before Prop. 1; the block wait named in §2.2 and tied to
  §4.3; figure legends moved outside the axes (Figure 1, Figure 4);
  Figure 4 thrashed-seed counts stacked; App. B tables shortened (no
  overfull boxes); unused E2 macros dropped; Table 11's ρ' and its
  "ρ' ≥ 1" now computed from the same seed-mean loads; SWE-bench CV²
  is a macro (`\trCvN`). Main text ends on page 8 with slack.
- Testbed: MiniMax-M2.7 fp8, DP4+EP on RBLN-CR13 ×4, block 4096,
  sub-block (512-token) prefix cache, max-num-seqs 8, host-tensor
  mode; the server has been up since 2026-09-24 (port 8010). How to
  launch, what failed and why: `research/testbed.md`.
- E1 (prefill cost model): a = 0.194 ms/token, b = 6.51 ns/token²,
  c0 = 44 ms, K_c ≈ 30k, MAPE 3.4 %.
- E2 (50k-context replays, four runs, `paper/exp/tab-e2.tex`): a
  resident prefix does not queue (TTFT 2.0–2.6 s at every cap); a miss
  waits 20–101× longer, for KV blocks (pool 52 × 4096 tokens per rank,
  occupancy 78–80 % while a request waited, running ≤ 4 per rank); both
  compute-only predictions are 1–2 orders below the observation; the
  cap moves the wait to the entry queue (sojourn incl. entry wait
  2583 → 1344 s, throughput 0.070 → 0.092 turns/s). The PK regime is
  not reachable at 50k contexts on this pool.
- **E2b (2026-09-26, new): the PK regime and the first measurement of
  the price.** Short-context variant of the trace
  (`scripts/exp/make_short_trace.py`: 9 copies of the 37 sessions,
  first prompt 2k, appends scaled ×0.44 so the mean is ~940 tokens,
  contexts 2k → 8.6k, `out ≤ 4` so decode is negligible, per-session
  nonce, round-robin rank pinning; forced arm: 10 % of follow-ups get
  a nonce at the head of the prompt from that turn on). Runs in
  `data/exp/e2b/` (window: 90 s after the first arrival to the last
  arrival), analysed by `analyze_e2.py --warmup 90` and
  `analyze_price.py`, into `paper/exp/tab-e2b.tex`, `tab-e2b-price.tex`,
  `macros-e2b.tex` and Figure 1(d,e):

  | run | ρ/rank (E1) | hit % | CV²_arr | TTFT hit / miss (s) | W_srv (s) | PK (s) | finite (s) |
  |---|---|---|---|---|---|---|---|
  | s = 2.5 s baseline | 0.35–0.36 | 98 | 1.0 | 0.57 / 1.25 | 0.11 | 0.16 | 0.13 |
  | s = 2.5 s, 10 % forced | 0.46–0.49 | 87 | – | 0.9 / 2.5 | 0.4 | 0.54 | 0.29 |
  | s = 1.5 s baseline (saturated) | 0.67–0.74 | 75 | 1.3 | 5.2 / 12.1 | 5.8 | 1.7 | 2.4 |
  | s = 3.5 s baseline | 0.24–0.25 | 99 | 1.3 | 0.5 / 0.3 | 0.05 | 0.09 | 0.08 |
  | s = 5 s baseline | 0.17 | 99 | 1.5 | 0.4 / 0.5 | 0.04 | 0.05 | 0.05 |

  Price test (`analyze_price.py`; bracket of `prop:price` from the
  baseline's λ, ρ, PK wait and each miss's own hit and miss work, over
  every miss the change caused: the forced ones plus the unforced ones
  net of the baseline's, since the forced arm holds more KV and LRU
  evicts the sessions parked at the 30 s gap): at s = 3.5 s, 163 forced
  turns, no unforced misses, L_P 1.39 → 2.14, ΔL_P = 0.75 inside
  [0.74, 0.83]; at s = 2.5 s, 243 forced + 52 extra unforced misses
  (26 → 78), L_P 2.36 → 4.41, ΔL_P = 2.05 inside [1.80, 2.27] (forced
  only it would be [1.56, 1.88]). Per rank ΔL_P / lo is 0.86–1.22. The
  head-of-line term is 55–64 % of the price, the queue's part of the
  rise 1.4–2.9× the added service, 49–58 % of the rise is borne by turns
  that did not miss; the finite-source wait is 0.7–1.8× the server's
  queueing time per rank, its price understates the rise 1.9–2.5×.
  Second seed (nonces and forced draw, `--seed 1`) at 2.5 s
  (`s25_base_s1`, `s25_m10_s1`): ΔL_P = 2.15 inside [1.89, 2.44], so
  the rise is inside the bracket in all three tests; per rank
  ΔL_P / lo 0.86–1.36.
  This is the measurement of Φ_i the round-4 review asked for.
  Two failures worth knowing (details in `research/testbed.md`): with
  `out ≤ 32` the decode batch cap bound (ITL 0.02 s idle → 0.3 s
  loaded, running = 8); at 1.5 s spacing the pool's 4096-token blocks
  filled at ~20 live sessions per rank, LRU evicted the prefixes with
  the longest gap (every miss followed a 30 s gap) and the replica
  thrashed (TTFT 0.6 → 3.6 s over the run). On this stack a prefill
  step is exclusive and has priority over decode, and the DP+EP ranks
  step in lockstep, so ITL rises 100× under prefill load (0.017 s idle,
  0.10 s when a peer rank prefills, 0.17–0.25 s when the own rank does;
  `research/testbed.md`). The paper's "prefill from the budget decode
  leaves" is reversed here; §6 says so.
- Review round 5 (2026-09-26, `research/reviews/2026-09-26-round5.md`,
  verdict "minor revision") and the response (`-round5-response.md`,
  v0.14): every miss the change caused is priced, per-rank rows and the
  three findings (HOL share, bystanders, finite-source wait closest /
  price worst) are in §4.3, both wait denominators, the 1.5 s arm's two
  routes, the derived trace described, E2's three TTFT classes (miss
  46–107× a hit), W_q = W_q^P + W_q^M, R_j for the move cost, abstract
  146 words. Round-4 leftovers done in v0.13.
- Simulator recalibrated on E1/E2 (`CAL_*`), ω = 0.057 s; `make sim`
  OK (35 checks).
- **Memory model (2026-09-26, three review rounds, accepted).**
  `scripts/exp/memory_model.py`, `research/memory-model.md`,
  `research/reviews/2026-09-26-memory-round{1,2,3}*.md`, outputs
  `data/exp/memory/`. A closed-loop replica model of the testbed:
  strict FCFS admission of whole prompts from 51 allocatable blocks per
  rank, block-level LRU with the engine's sub-block copy semantics
  (a hit needs one block more than a miss), prompt-only reuse, one
  exclusive prefill, growth during decode, E1 prefill cost, **measured
  decode durations** as input. It reproduces which turns hit (κ
  0.73–0.99), per-class TTFT, door waits and the per-rank waiting-count
  series of /metrics in the long-context replays, and the classes of the
  short-context runs incl. the saturated arm. Finding: the long-context
  misses are the turns that queued (92–100 % arrived to a queue); the
  hit/miss TTFT ratio is congestion, not the price of a miss. Paper
  corrected accordingly (abstract, intro, §4.3; macros
  `\eTwoMissQueue*`, `\eTwoHitQueue*`, `\eTwo*Think*`, `\eTwoAnyPf*`
  from `analyze_e2.py`); no model output is in the paper (rule 7).

- **Miss feedback (2026-09-27, analysis only, not in the paper).**
  `research/analytic-memory.md`, Lean `MissFeedback.lean` (Tarski extremal
  equilibria, comparative statics, bistability, the PK instance, the
  forced-miss multiplier), `scripts/exp/analyze_feedback.py`. The hit
  rate is a fixed point `h = E[G(Z + W(h); h)]`; in the short-context
  price test the implied secant slope is 0.18–0.19 at 2.5 s and ~0 at
  3.5 s; the wait channel is excluded, the pool channel inferred by
  elimination and association (insertion +42 %, misses after the 30 s
  gaps; no fixed-threshold version fits). With forced misses alone the
  price bracket misses the rise at 2.5 s; with the induced ones it holds.
  Next: registered channel-separation run (redesigned, review round 2).

**Next (in order).**
0. **Memory model, decode stretch: status 2026-09-26 23:06.** Probes A–G run
   (`data/exp/decode/`, `probe_decode.py`, `analyze_decode.py`); lockstep
   replica model `scripts/exp/lockstep_model.py`. The pre-registered
   validation **failed** (v1 deviated from the registered max rule and
   charged c0 as engine time; see research/memory-model.md "Deviations and
   corrections"). Post hoc, the registered max rule on probes A+B with c0
   fixed meets every threshold on the long-context runs and s15's miss
   count, but not metric 1 in the short-context arms. Next, in order:
   (i) commit the model and a new registration **before** any test (the
   user must approve the commit); (ii) the probes review round 4 asks for
   (short appends timed by a decoding observer on another rank; decode cost
   while a peer prefills; randomised order, nonce per prompt), and an
   engine-side step log for one replay if feasible; (iii) a fresh saturated
   held-out replay with ensemble-interval thresholds; (iv) the probe
   measurements into §4.3 / App. D via `make exp`.
   Original plan (review round 3):
   (a) User decision: may `memory_model.py` output enter the paper as
   `make tables` output labelled simulation (AGENTS.md rule 7 now admits
   simulator numbers only via `paper/simulation.tex`)? (b) Decode probe
   on an idle server, E1-style: decode step time vs batch b ∈
   {1,2,3,4,5,8} (compiled buckets 1,4,8) and context, mixed contexts,
   equal and unequal load across ranks, decode rate while a peer or the
   own rank prefills, and the prefill stretch measured directly.
   (c) A step-level lockstep model on one clock for all ranks, a
   preemption frees its victim. (d) Pre-register the validation in
   research/memory-model.md (date, git hash) before the first run: s10c8 and
   s15_base held out, s15 reproduced without a prefill-stretch factor, no
   parameter from E2/E2b. (e) Then the model-based price of a miss at
   50k contexts (force single turns to miss, measure the added summed
   TTFT) against the bracket of `prop:price`; later port the pool
   mechanics into the serQ replay and validate them against held-out runs.
   The replay port is complete; held-out real-system scoring remains open.
1. **A100 testbed (user decision, 2026-09-26).** Reproduce the cost fit
   and both replays on GPU vLLM, then run the pending experiments there
   (offloading test with LMCache, eviction replay with 16-token blocks,
   placement test, faithfulness scoring). Why GPU: the vllm-rbln
   scheduler runs prefill exclusively and with priority over decode and
   the DP+EP ranks step in lockstep, so the §2.2 model ("prefill from
   the budget decode leaves", Prop. 3 insensitivity) and everything that
   needs LMCache or a router cannot be tested on RBLN; the RBLN results
   stay as the second stack. Plan: (a) pick the GPU box and the model
   (MiniMax-M2.7 needs 8×A100-80GB in bf16, since A100 has no fp8; a
   30B-class dense model is enough for the mechanism and needs one
   A100); (b) `scripts/exp/serve_gpu.sh` (draft exists: vLLM with
   prefix caching, chunked prefill, `--max-num-seqs`, `/metrics`);
   (c) `probe_prefill.py` for the cost fit → new `fit.json` under
   `data/exp/gpu/e1`; (d) the replays with `run_e2.sh` (`BASE`, `TRACES`,
   `OUTBASE=data/exp/gpu/...`, `DP_SIZE=0` on a single replica); the
   analysis and table scripts are stack-agnostic; add a stack column or
   a second table. The replayer's `--dp-size` pinning is not needed on
   one GPU replica.
2. Review round 6 (same prompt shape; focus: the second seed, the price
   table, the GPU rows once they exist).
3. E6-lite: replay `cc_traj` and the short trace in the calibrated
   simulator (needs a JSONL adapter to serQ's trace corpus) and compare
   with `tab:e2`/`tab:e2b` per rank (Kendall τ, TTFT MAPE).
4. Remaining review-3 leftovers: UNVERIFIED venue notes in
   `paper/refs.bib`.
5. If more server time: E2b at a 5 % forced share (round-5 item 7b),
   a short-context baseline with the real gaps (7c; the 30 s cap is the
   atom LRU evicts), and the real gaps for the 50k trace.

**Do not.** Attribute a bracket overshoot to the prefill-time
inflation (scaling every service time by it over-corrects; round 5
issue 1). Type measured numbers into the paper; run two replays at
once on the server; leave caches under `~/.cache` (see AGENTS.md);
use `pkill -f` with a pattern that appears in your own command line
(it kills the shell; write the pattern with a bracket, `run_al[l]`).

## 1. Thesis

**Central claim (v0.6).** Every KV decision in agentic serving asks what
it costs to lose a paused program's state. That cost is the *price of
a miss* `Φ_i`: the total TTFT one miss adds across all turns at the
prefill queue.

Model (v0.6, after two user reviews and the cost-model check): sessions
arrive Poisson(Λ); inside a session the turn → tool → turn loop is
closed; tools are a delay station (turn classes allow any turn-count
law). The replica has **two resources and a memory pool**:
- prefill compute: `P(n,K) = a n + b n (K + n/2)`; a miss re-prefills
  the evicted part. Prefill stage = FIFO queue served from the budget the
  decode batch leaves (chunked prefill protects decode, not prefill
  order; Sarathi-Serve/vLLM decode-first). PK as an approximation.
- decode bandwidth: `D = o (β K + ω/n)`; KV reads do not amortise over
  the batch, weights do. Decode stage = PS with capacity φ(n),
  insensitive. Hit/miss does not change D.
- memory: `κ K` bytes while resident; shared by paused states and the
  batch; admission cap; shadow price θ per byte-second.

Cost-model check (roofline, 70B-class, not paper numbers): hit prefill
of a few hundred tokens onto 142K ≈ 0.5 s; miss prefill of 142K ≈ tens
of s (TP1); decode of 444 tokens ≈ several s (KV reads ≈ 14 ms/step at
45 GB per session). So miss/hit is ~100× for prefill/TTFT but only a few
× for the whole turn. The paper's CV² example is therefore about prefill.

- `prop:price` (prefill queue, FIFO): three-term price with the
  head-of-line term (∝ miss²); ranking changes with load. Central.
- `prop:decode` (PS): L_D monotone in ρ_D and insensitive; a miss adds
  no decode demand. Used for admission (load factor) and to separate the
  stages.
- The memory threshold uses whole programs as items in the relaxed problem.
  Tail-block recomputation is concave, so block eviction is not a linear
  fractional knapsack; do not apply its density-optimality claim to tail blocks.
- footprint examples (prose in §2.2, was `prop:footprint` until v0.7): KV footprint variance can shrink or grow the batch
  that fits in memory (no fixed sign), so φ's saturation must be
  measured.
- Withdrawn v0.5 claim: "chunked prefill makes the eviction key
  load-independent". Chunking protects decode; the prefill queue keeps
  the square term. The
scheduler (paper §3, Algorithm 1) compares `u_i = p_i Φ_i /(c_i τ_i)`
with the shadow price θ; SF, recency/TTL keys, always-offload, strict
affinity and admit-all are the special cases where a price is replaced
by `c_i²`, a constant `p_i`, zero, infinity and `θ=0`.
- `prop:blind` (added 2026-09-23): any eviction rule that does not see
  `p_i` has no constant approximation ratio (generalises the SF result);
  SF is the `w=c²` price-per-byte order, a tight 2-approximation.

A queueing model of agentic LLM serving is useful if it is **decision
faithful**: it ranks policies (eviction, offloading, PD split, routing) the
same way the real system does. Exact latency reproduction is secondary.

The model is one causal chain (paper §2):

```
KV policy → hit rate p → (E[S], E[S²]) → (ρ, E[W_q]) → delay cost L → policy
```

## 2. Current paper structure

| § | Content | Our results | Cited results (prose) |
|---|---------|-------------|----------------|
| 1 | Intro: thesis, three contributions | 10× example (inline) | none |
| 2.1 | Sessions, turns and tools (`sec:sessions` = `sec:closed`): Poisson sessions, closed loop inside, BCMP in one sentence | none | BCMP |
| 2.2 | A replica: two resources and a memory pool (`sec:batch` = `sec:queue`): `eq:prefill`, `eq:decode`; prefill FIFO, decode PS; Table 1 (the model at a glance); units κ (bytes/token), β, ω (s) | footprint examples (prose, `footprint_variance_*`) | Sarathi-Serve (chunked prefill), BCMP/Kelly insensitivity, PK (`eq:pk`) |
| 2.3 | Prefill work under KV reuse (`sec:congestion`) with `tab:cv2` (trace-derived split: append vs mixture; generated `paper/traces/tab-weka-cv2.tex`) | `prop:pk`, `prop:cache` as prose | none |
| 2.4 | **The price of a miss** (`sec:price` = `sec:problem`; decision problem, θ, `eq:price`, `eq:utility`) | `prop:price` (bracket only); prose with inline `\provedby`: term ratios, divergence, `missPrice_mono_context`, `price_order_flips_with_load`; **`prop:finite`** (M/M/1//N: `mvaQ_mono`, `finite_source_wait_le_open`, `closed_price_cap`; usable price = min(bracket, N − L_P)); `prop:decode` (stability condition added) | Mendelson–Whang / Dewan–Mendelson externality (UNVERIFIED bib) |
| 3 | Congestion-priced scheduling (`sec:sched`) | | |
| 3 (intro) | Algorithm 1: observe, price, set θ, evict, keep/offload/drop, place, admit (cap from the resident-KV estimate); inputs are estimates | none (design) | none |
| 3.1 | Eviction: threshold rule, block prefix, byte-second variant, guarded greedy as cited known results (inline `\provedby`); "Fixed keys" paragraph with trace evidence (p 0.85–0.99, τ 4–65 s; `tab:resume` in App. C) | `prop:blind` ((i) price-blind keys unbounded, (ii) SF as the `w=c²` price-per-byte order, tight 2-approx); SF non-optimality instance as prose | Dantzig 1957, Csirik et al. 1991, Carnes–Shmoys 2008 |
| 3.2 | Placement: `eq:lookahead`, `eq:rhostar` (inversion load ρ* = μ(M+F)/(1+μ(M+F)), monotone in M, F; lower bound for any real alternative) as prose | inline `\provedby` (`affinity_loses_iff`, `inversionLoad_*`) | none |
| 3.3 | Admission and offloading (thrashing = Ao et al. 2026 instability with reuse; Campbell resident-KV estimate → cap; keep/offload/drop; option value; fixed rules as constants in one sentence) | none (design) | Campbell (M/G/∞), Ao et al. 2026 |
| 4.1 | What the traces say (`sec:exp-traces`, `tab:traces`; TTFT and resume tables in App. C) | none (workload measurements) | cc-traces-weka |
| 4.2 | Replayed production sessions on simulated vLLM rules with a testbed-calibrated cost model (`paper/simulation.tex`); synthetic checks summarized here, detailed in App. B | none (simulation checks) | none |
| 4.3 | Testbed measurements: cost fit, long-context replay, short-context replay and price test | none (serving measurements) | none |
| App. E | Experimental design for a real system (`app:design` = `sec:exp-real`): overview table + one paragraph E1–E6; result-table layouts in §4.2a below | none | none |
| App. D | Testbed tables (`paper/exp/`) | none (measurements) | none |
| App. A | Human-readable proofs (price, decode, blind, finite) | | |
| App. B | Simulation tables (`paper/simulation-appendix.tex`) | | |
| App. C | Trace tables (TTFT by append; resume probability and gap) | | |
| (removed) | PD disaggregation → `paper/pd-followup.tex`, see §4.2b | `prop:pd`, `eq:append` (Lean kept) | |

Conventions that follow from the user's review of v0.1:
- Do not call the model "layered" and do not use a "Layer 1..4" structure.
- Propositions live in the section whose decision they inform. Do not
  collect them in one section.
- Published rules are mentioned in one or two sentences as special cases
  of a step of the scheduler (v0.7, 2026-09-23: the "The claim" /
  "Reading the claim" paragraphs were removed; §3 proposes the method).
  There is no separate claims or special-cases section.
- Lean is not visible in the paper. `\provedby{\leanref{...}}` typesets
  nothing. The only mention is one sentence at the top of Appendix A.
- Appendix proofs are ordinary mathematical proofs, not transcripts of
  Lean proofs.
- No `example` blocks between propositions (removed in v0.2). The two
  numbers that carry an argument (10× latency in §1, CV² > 15 vs < 0.05
  around `eq:cv2`) are prose sentences with an inline `\provedby{}`. The
  other Lean `_example` theorems remain in Lean but are not cited.
- Established results are stated in prose with a citation (no `theorem`
  boxes); they are not proved. Our own results are `proposition`s.

## 3. Status of analytical results

All propositions and cited numbers compile in Lean with no `sorry` and
only standard axioms (`make lean` reports `OK: 170 theorems audited`).

| Result | Status | Notes |
|--------|--------|-------|
| `prop:price` (prefill queue, FIFO): bracket | proved | central result; term ratios, divergence and load-dependent ordering are prose with inline proof references. PK is an approximation for the serving system |
| `prop:decode` (PS) (i) monotone ⇒ ranking by work, (ii) closed-form exact change for constant capacity, (iii) unbounded | proved | (i) is proved in Lean for finite truncations; the untruncated case is the limit (App. A proof). Insensitivity itself is cited (BCMP/Kelly) |
| Memory threshold (cited prose, whole-program relaxation) | proved under its assumptions | `threshold_prefix_le`; tail-block recomputation is concave, so the linear fractional result does not certify block eviction |
| footprint examples (§2.2 prose; was `prop:footprint`) | proved | the review's two examples; `decide +kernel` on ℚ; demoted to one sentence in v0.7 |
| Guarded covering bound (cited prose) | proved | (ii) is proved as a certificate lemma (`guardedGreedy_two_approx`): hypotheses encode the greedy's sorted-prefix property; the algorithm itself is not formalised |
| PK/cache inequalities (prose) | proved | these are no longer proposition boxes; their Lean theorems remain |
| `eq:cv2` examples | proved | prefill-work variance splits into append and hit/miss-mixture contributions |
| option value (prose in §3.3) | proved | trivial math, so demoted from a proposition to a prose sentence; its value is in reading ThunderAgent A.2 correctly |
| `prop:blind` (i) any price-blind rule unbounded | proved | `price_blind_rule_unbounded`; the rule is an arbitrary function of any observation type except `p` |
| `prop:blind` (ii) SF = `w=c²` price-per-byte order, feasible, 2-approx + tightness | proved | formerly `prop:evict` (ii); v0.1 wrongly said the ratio is unbounded |
| SF not optimal on `{4,5,6}`, ΔC=6 | proved | prose sentence after `prop:blind` with inline `\provedby`; contradicts ThunderAgent App. F.3 |
| PD capacity (follow-up only) | proved | capacity model only, no batching; outside the current paper |
| Decode scaling identity (PS, follow-up only; issue #28) | proved | `DecodeScaling.lean`: scaling arrival rate and capacity by the same factor keeps the PS law and mean number, divides the sojourn (Little); a dedicated decode engine `(λ/f, φ)` is the colocated `(λ, fφ)` scaled by `1/f`; token-weighted TPOT scales, request-weighted TPOT only for a fixed output length; a smaller share of the capacity at the same demand raises the mean number (`psMeanNumber_anti_share`, `psNum_anti_capacity`, cited in §2.2). Conditional on a constant share `f`, Poisson arrivals and a split-independent work law; says nothing about a step engine |
| Placement: inversion load and monotonicity (prose, `eq:rhostar`) | proved | a shared KV store enters through the move cost; append routing belongs to the PD follow-up |
| `prop:finite` | proved | M/M/1//N MVA recursion, monotonicity, open-wait bound; finite-source price cap in prose |

Candidate results, not yet in the paper. Each needs a Lean proof, or a
citation to an established theorem, before it becomes a proposition:
- **General finite-source work laws.** The M/M/1//N result is proved and
  in the paper. An M/G/1//N price inequality remains open; replay agreement
  for selected miss fractions does not prove it (`tab:sim-trace-price`).
- **Price with priorities.** Serving hits before misses (Cobham's
  formula) changes the externality in `Φ_i`; a priced rule for queue
  order would complete the scheduler.
- **Transient price.** `prop:price` prices a stationary fraction of
  misses; a bound for a single eviction event would close the gap noted
  in the paper's Limitations.
- **Priced offloading threshold.** A closed-form keep/offload/drop
  threshold in `(p_i, c_i, B_tier, ρ)` derived from `eq:price`.
- **Closed-network throughput knee.** Asymptotic bounds
  `X(N) ≤ min(N/(D+Z), 1/D_max)` applied to ThunderAgent's concurrency
  sweep. Cite Lazowska et al.; the bound itself is standard. The simulator
  already checks it with ample KV
  (`closed_throughput_nondecreasing_fixed_demand`).

## 4. Validation plan: simulation first, then empirical

Validation runs in three phases. Each phase narrows what the next one
has to measure.

1. **Simulation (uncalibrated), done.** Check every proposition in its own
   model, then drop one assumption at a time and ask whether the decision
   survives. Synthetic workloads, fixed seeds. Summarized in paper §4.2, detailed in App. B.
2. **Empirical (E1–E6), partly done.** Measure on the NPU testbed and on traces.
   The hypotheses and the quantities each experiment must record are
   those that phase 1 showed to decide the outcome.
3. **Calibrated simulation, implemented; scoring open.** The vLLM-rule replay
   uses the cost fit. Score it and the analytical model against held-out
   testbed runs (faithfulness scoring).

Platform codes: T = NPU testbed, S = simulator (`validation`,
`research/simulation-design.md`), O = offline on traces.

### 4.1 Phase 1: simulation (uncalibrated)

Status: 35 named checks; report via `make report`. What
each part established, and what it changes for phase 2:

| Question | Current check / evidence | Consequence for empirical work |
|----------|--------------------------|-------------------------------|
| Closed forms under their assumptions | queue, PS, finite-source and PD checks in `validation/src/checks.py` | conditional validation; PD is for the follow-up |
| Bursty arrivals | PK/arrival-variability checks | record interarrival variance alongside wait |
| Finite KV and admission | agentic checks and vLLM-rule open/replay programs | record resident KV, reuse and live population |
| Eviction | offline exact/guarded checks and vLLM-rule comparisons | compare end-to-end TTFT as well as offline cost |
| Offloading | blocking versus asynchronous fetch scenarios | record whether fetch is on the critical path |
| Placement | inversion-load and shared-link checks | measure the move cost and policy ranking |

The old whole-session-replica rows and their manually copied numbers are
superseded. Current outputs are generated by `make tables` into `paper/sim/`;
`research/serq-replay42.md` identifies the historical comparison separately.

Phase 1 numbers are properties of the simulated model. They appear in the
paper only in §4.2 / App. B, generated from the simulator, and never in a `\tbd`
cell.

### 4.2 Phase 2: empirical validation

Order matters: E1 gates everything, and E2 is the first result worth
reporting because it tests the paper's stance on variance (AGENTS.md
rule 5).

| ID | Question | Tests | Where | Needs (incl. from phase 1) | Status |
|----|----------|-------|-------|----------------------------|--------|
| E1 | Fit `S_prefill(L,K,B)`, `S_decode(B,KV)`, `T_transfer(bytes)` | calibration | T | profiling harness | **prefill fit done 2026-09-24** (paper §4.3, `tab:e1`): MiniMax-M2.7 fp8, DP4+EP, block 4096, sub-block prefix cache on, no LMCache (`scripts/exp/serve_m27.sh`, `research/testbed.md`); 45 probes pinned to one DP rank, `P(n,K)=c0+an+bn(K+n/2)` with a=0.194 ms/token, b=6.51 ns/token², K_c≈30k tokens, MAPE 3.4 % (held-out cold→append 3.7 %); generated by `make exp`. Decode probes subsequently recorded in §0; transfer and φ(n) validation remain open |
| E2 | How does per-turn Var[S] split between the append and the hit/miss mixture, and does the mixture's share grow under eviction from the trace baseline (Weka: 57 % at p = 0.96, linear cost; `research/trace-analysis.md`)? Does `W_q` track `(1+CV²)/2`? Does forced-miss ΔL fall in the `prop:price` bracket? | `prop:pk`, `eq:cv2`, `prop:price` | T, S | E1, replayed traces (Weka sequences), interarrival CV², miss injection | trace baseline done (2026-09-23); replayed in simulation 2026-09-24 (`tab:sim-trace`, `tab:sim-trace-price`); testbed runs completed 2026-09-24/26 (see §0 and `research/testbed.md`); original launch 2026-09-24 (`scripts/exp/run_e2.sh`: open-loop replay of fsw-415 cc_traj_50k with a live-session cap; `analyze_e2.py`) |
| E3 | Is priced offloading never below never-offload? When is always-offload below it? | option value (§3.3) | T, S | E1, tier bandwidth, fetch mode (sync/async) | not started |
| E4 | SF vs price per byte vs guarded vs exact optimum, offline and end-to-end; LRU vs hit-ratio vs price | guarded covering bound (prose), `prop:blind` | O, S | traces with resume events, spread of `p_i`, a regime with mean wait comparable to a miss | not started |
| (PD) | Does the PD inequality predict the winner? What is the latency cost at equal capacity? (follow-up paper, see §4.2b) | `prop:pd` | T | E1, measured `I, g_P, g_D` | not started |
| E5 | At what load does affinity lose? Does the inversion-load formula predict it? How does a shared KV store change the move cost? | placement result (prose), `eq:lookahead`, `eq:rhostar` | T, S | E1, migration/fetch cost | simulated 2026-09-24 (`tab:sim-inversion`: monotone in move cost; `ρ*` matches for cheap moves, link saturation for expensive ones); testbed not started |
| E6 | Decision-faithfulness scorecard (Kendall τ, argmin agreement, MAPE) | whole model | T, S | E1 to E5, phase 3 | not started |

The experimental design is in paper App. E. The table layouts below are the
contract: fill `\tbd` cells with measured values only, and do not change
what a table measures without updating this file.

### 4.2a Result-table layouts (moved out of the paper on 2026-09-23)

The paper keeps only the experiment-overview table and short hypotheses
(§4.3 / App. D). The layouts below are the contract for what each experiment
reports; fill them with measured values only. E numbering in the paper
is now E1–E6 (PD experiment removed with App. B; see §4.2b).

**Workload statistics** (reference column: vLLM AgentX medians)

| Statistic | Reference | Median | p90 |
|---|---|---|---|
| Turns per program | 43 | TBD | TBD |
| Input tokens per turn | 142K | TBD | TBD |
| Output tokens per turn | 444 | TBD | TBD |
| Tool time per turn (s) | – | TBD | TBD |
| Prefix hit rate | >96 % | TBD | |
| Resume probability p_i | – | TBD | TBD |
| Session interarrival CV² | – | TBD | |
| Resident KV (tokens) | – | TBD | TBD |
| Corr(session length, context) | – | TBD | |

**E1: fitted service and transfer models (held-out split)**

| Quantity | Fitted form | R² | MAPE |
|---|---|---|---|
| S_prefill(L, K, B) = eq:prefill | TBD | TBD | TBD |
| decode step time (n, ΣKV) = eq:decode (β, ω) | TBD | TBD | TBD |
| T_transfer (device–device) | TBD | TBD | TBD |
| T_transfer (device–tier) | TBD | TBD | TBD |
| Batch capacity φ(n) | TBD | TBD | TBD |
| Batch size under memory M (measured footprint law) | TBD | TBD | TBD |

**E2: variance decomposition, prefill scheduler, price of a miss**

| Quantity | Value |
|---|---|
| Per-turn prefill CV² | TBD |
| Share of Var[S]: hit/miss mixture (trace baseline, no eviction: 57 % at p = 0.96 linear, 35 % at K_c = 100K; `research/trace-analysis.md`) | TBD |
| Share: output-length spread | TBD |
| Share: context-length spread | TBD |
| Prefill wait measured / PK, ρ_P = 0.5 / 0.7 / 0.9 (blocking) | TBD |
| Prefill wait measured / PK, ρ_P = 0.7 (chunked) | TBD |
| Decode occupancy, low vs high prefill CV² | TBD |
| Step time vs batch KV: β, ω, R² | TBD |
| ΔL_P / (λ Σ q_i Φ_i), chunked, ρ_P = 0.5 / 0.9 (prop:price predicts [1, (1−ρ)/(1−ρ')]) | TBD |
| ΔL_P / (λ Σ q_i Φ_i), blocking, ρ_P = 0.5 / 0.9 | TBD |

**E3: throughput (turns/min) and hit rate by offloading policy and concurrency**

| Policy | 24 | 48 | 72 | 96 |
|---|---|---|---|---|
| Never offload | TBD | TBD | TBD | TBD |
| Always offload | TBD | TBD | TBD | TBD |
| Priced (keep θcτ / transfer / drop w) | TBD | TBD | TBD | TBD |
| Hit rate, priced | TBD | TBD | TBD | TBD |
| Fetch on critical path? (yes/no) | | | | |

**E4: eviction and admission.** Cost relative to the optimum of
eq:evict-priced (estimated p_i, Φ_i) on replayed eviction events, and
end-to-end p99 TTFT under both prefill schedulers; admission-cap sweep.

| Rule | Cost / OPT | p99 TTFT ρ_P=0.7 | p99 TTFT ρ_P=0.9 |
|---|---|---|---|
| Shortest-first | TBD | TBD | TBD |
| Price per byte v_i | TBD | TBD | TBD |
| Price per byte-second u_i (θ rule) | TBD | TBD | TBD |
| Guarded (program-level covering bound) | TBD | TBD | TBD |
| Block-prefix policy (partial-recompute price) | TBD | TBD | TBD |
| Exact optimum | 1.00 | TBD | TBD |
| LRU | TBD | TBD | TBD |
| Hit-ratio maximisation | TBD | TBD | TBD |

| Admission cap | Hit rate | Throughput | p99 TTFT | Thrash episodes |
|---|---|---|---|---|
| (sweep) | TBD | TBD | TBD | TBD |

**E5: routing.** p99 TTFT (ms) by router and load; predicted vs observed inversion load.

| Router | ρ = 0.5 | ρ = 0.7 | ρ = 0.9 |
|---|---|---|---|
| Myopic | TBD | TBD | TBD |
| KV-aware | TBD | TBD | TBD |
| Program-aware (priced M_j) | TBD | TBD | TBD |
| Strict affinity | TBD | TBD | TBD |
| Inversion load (pred. / obs.) | TBD / TBD | | |

**E6: decision-faithfulness scorecard** (τ = Kendall rank correlation of
policy orderings; Agree = fraction of states with the same argmin)

| Decision | Analytical τ | Analytical Agree | Simulator τ | Simulator Agree |
|---|---|---|---|---|
| Offloading | TBD | TBD | TBD | TBD |
| Eviction | TBD | TBD | TBD | TBD |
| Admission | TBD | TBD | TBD | TBD |
| Routing | TBD | TBD | TBD | TBD |
| TTFT MAPE | TBD | | TBD | |

### 4.2b PD disaggregation (removed from the paper)

App. B (static PD splits `prop:pd`, per-turn routing `eq:append`, the
planned PD experiment and the PD simulation paragraphs) was removed from
`paper/main.tex` on 2026-09-23 and saved verbatim in
`paper/pd-followup.tex` (not `\input`). `PDDisaggregation.lean`,
`validation/src/sim/pd.py` and the `tab-pd*` generators stay in the repository for
the follow-up paper. The PD experiment (formerly E5) is no longer in the
paper's numbering: E5 = routing, E6 = scorecard.

Issue #28 (2026-10-01) separates two questions the follow-up must keep
apart. `prop:pd` is about capacity (requests per second at fixed
device-seconds per request); the FIFO tandem's higher latency at equal
capacity (`tab:sim-pd`) is a pooling loss of a model without batching.
Neither says that a split cannot shorten the decode sojourn at equal
throughput: `DecodeScaling.lean` proves the PS identity (arrival rate and
capacity scaled together keep the occupancy and divide the sojourn), and
`validation/src/sim/pd_batching.py` runs serQ #208's step engines, where
the split keeps the output throughput, shortens the token-weighted TPOT
and lengthens the TTFT, with the ratio equal to the PS identity's
1/(1−p) only when the colocated decodes never drain (10 ms steps) and
different interruption patterns at the same prefill share giving
different TPOTs. The follow-up reports the pooling loss, the TPOT gain
and the TTFT/transfer cost separately, with the metrics defined in
`paper/pd-followup.tex` ("Metrics": client-visible TTFT, TPOT as
first-to-last over gaps, request- vs token-weighted, response = TTFT +
decode sojourn, request vs output throughput vs saturated capacity vs
SLO goodput). The multi-turn and closed-session comparison is in serQ's
`tools/pd_batching/sessions.md` (a faster answer brings the next turn
sooner; Little's law gives the throughput change) and is not rerun here.

### 4.3 Phase 3: calibrated simulation

Continuous batching, block-level KV, trace replay and the cost fit are
implemented (milestone M5). Ladder step 5 still needs to compare the calibrated
simulator with the testbed at the E6 held-out points. Its numbers may fill future "Simulator" columns of a scorecard, clearly
labelled as simulation. §4.1 contains workload measurements; current
simulation evidence is in §4.2 / App. B.

### Data needed from traces
- Per turn: arrival time, new tokens, cached tokens (hit length), output
  tokens, service time split into prefill and decode, tool time after
  the turn.
- Per program: turn count, whether it resumed after each pause. This
  gives empirical `p_i` for E4.
- Eviction events: which programs were resident, their `c_i`, and the
  memory target. This gives E4 instances.
- Added after phase 1: turn interarrival times per replica (for c_a²,
  E2); whether offloaded KV is fetched on the batch's critical path (E3);
  per-migration transfer time and bytes (E6).

### Decisions about the simulator
The simulator checks live in `validation/` (Python using pyserq); `research/simulation-design.md`
has its design, status and roadmap. It serves E2 (hit-rate sweeps), E3,
E4 (end-to-end), E5 and E6. E1 and the PD experiment are testbed-only; E4's cost/OPT
column is offline. Milestones M0 to M4 are built on synthetic workloads
(offline oracle, fair-share links and dynamic PD still open).
Synthetic checks are summarized in §4.2 and detailed in App. B. The trace
replay in §4.2 already uses the measured cost fit. All simulator numbers
enter through `make tables` into `paper/sim/`, never the measurement tables.
Held-out faithfulness scoring is still open.

## 5. Claims we must not make (until data exists)

- That agentic workloads are "high variance" or "long-tailed" (AGENTS.md
  rule 5). Say that variance comes from the hit/miss mixture and that E2
  measures it.
- That PD does or does not help agentic serving in general. Say which
  regime of `prop:pd`(iii) applies.
- That the PD throughput no-gain (`prop:pd`) is a latency no-gain, or that
  the FIFO tandem's higher latency at equal capacity is a property of step
  engines. The capacity theorem says nothing about the decode sojourn at
  a given throughput; the step-engine comparison (serQ #208,
  `pd_step_*` checks) shows a TPOT gain and a TTFT cost that must be
  reported together (§4.2b).
- That the mean prefill fraction of a colocated engine predicts the
  split's TPOT gain. It does only when the decodes never drain
  (`pd_step_long_step_matches_ps_share`); exclusive, mixed and chunked
  steps at the same share differ (`pd_step_interruption_pattern`).
- That footprint variance helps or hurts batch size in general
  (the §2.2 footprint examples show both signs).
- That hit/miss variance raises mean delay regardless of the prefill
  scheduler; under chunked prefill (PS) it does not.
- That shortest-first is a bad heuristic in practice. It is within 2× of
  optimal when resume behaviour is uniform. Whether it is bad depends on
  the spread of `p_i` (E4).
- Any number attributed to ThunderAgent, PPD or the vLLM blogs that was
  not read in the source. Mark bib entries `UNVERIFIED` otherwise.
- That a phase-1 simulation result holds for real systems or traces
  (AGENTS.md rule 7). In particular: that density and SF perform alike in
  practice, that the congestion-priced rule does or does not beat density
  end-to-end, that PS thrashes earlier than blocking prefill (an artefact
  of φ≡1 with no separate prefill rate), that the LPS error has the sign
  seen here for real workloads, that async offloading is always best, or that the mechanism
  behind ThunderAgent's collapse is the one the simulator reproduces.
  Phase 1 shows these are possible under the model; phase 2 decides.

## 6. Bibliography status

Verified against the source on 2026-09-23: kleinrock1975, pollaczek1930,
khinchine1932, schrage1968, lazowska1984, carnes2008, csirik1991,
thunderagent (v3), ppd, vllm-agentx, mooncake-vllm.

`UNVERIFIED` (bibliographic details from memory, statement standard):
little1961, kingman1962, dantzig1957, naor1969, mendelson1990,
infercept, bcmp1975, kelly1979, kingman1993, kvlearn2026 (README read, paper not).

Verified from the arXiv abstract page only (not the full text), added
2026-09-23 for §1 and §5 Related Work: sarathi2024 and the 25 entries
under the ``Queueing-theoretic and scheduling-theory work'' comment in
refs.bib (nie2026stability, dai2025workconserving, ao2025fluid,
ao2026congestion, lin2026pdcontention, yang2024mg1, bari2025optimal,
dong2026flowcontrol, mitzenmacher2025queueing, chen2026fleetsim,
ozbas2026reasoning, jaillet2025online, feng2026nonclairvoyant,
wang2025variable, dexter2025prefix, shahout2024trail, li2025continuum,
xia2026mori, bian2025tokencake, pan2025kvflow, zhang2026cachescout,
ni2026topas, hsieh2026flowprefill, liu2026chunkedfair,
lyu2025fairbatching). The Related Work paragraphs paraphrase their
abstracts only; read the full text before any stronger claim. Venue
notes in the bib say which venues were stated on arXiv and which came
from search hits (UNVERIFIED). Closest competitors: nie2026stability
(ICML 2026, stability with KV memory), ao2026congestion (eviction-free
equilibrium unstable = our thrashing), li2025continuum (TTL from reload
cost + queueing delay = heuristic price of a miss). Gap the survey
found: no paper prices a KV miss or models the hit/miss mixture as the
source of service variance. InferCept matters most: the paper says it scores
preserve/discard/swap by memory waste, which must be checked because it
is the closest prior system work. Before submission, read the
primary source, check that the statement in the paper matches, and remove
the note.

## 7. Open questions

- Is the target venue ICML 2026 (theory with placeholders) or a systems
  venue after E1 to E6 exist? This affects how much of §4.2 stays in the
  paper.
- Which agentic trace can be used and released (internal Rebellions
  traces, or public ones)?
- Which serving stack runs on the testbed, and does it expose per-turn
  hit length and eviction events?
- Does that stack load offloaded KV synchronously (on the critical path of
  the batch) or asynchronously? Phase 1 shows the offloading ranking flips
  on this.
