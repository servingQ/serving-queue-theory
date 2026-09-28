# Research plan

Working reference for humans and coding agents. It records what the paper
claims, what is proved, what is pending, and in which order validation
should happen: simulation first, then empirical measurement (§4). Update it when the status of a result or experiment
changes. The paper (`paper/main.tex`) is the public statement. This file is
the internal plan and may be blunter.

Last updated: 2026-09-28.

## 0. Where we are / next steps (read this first in a new session)

Experiment names (2026-09-26, user request; the paper never uses the
codes): **cost fit** (E1), **long-context replay** (E2), **short-context
replay** and **price test** (E2b), **offloading test** (E3), **eviction
replay** (E4), **placement test** (E5), **faithfulness scoring** (E6).
The codes survive in directory names (`data/exp/e1`, `e2`, `e2b`),
macros (`\eOne*`, `\eTwo*`, `\eTwob*`) and older review files.

State on 2026-09-26 (paper v0.14, committed at the end of the session). What is done, running and next, so a
fresh session can continue without the chat history. Keep this section
current at the end of every work block.

**Done.**
- **IR first (2026-09-27, seQ v0.1.0-dev2).** A seQ program is defined by
  its IR (seQ `docs/ir.md`): versioned JSON, validated on load, with the
  workload instance (explicit sessions) as data. The vLLM request program
  had three hand-kept copies (a Rust test string, the Lean `vllmRequest`,
  `vllm.seq`); now `programs/vllm_request.seq` compiles per scenario to
  `tools/oracle/*.ir.json`, the seQ test runs those files, and
  `SeqOracle.lean`'s program, deployments and request tables are
  translated from them (same six theorems). Experiment scripts pass traces
  with `--trace` and record `program.ir.json`. **Done (dev3):** sessions
  carry their turns in the IR (`--inline-trace`), the Lean executable
  semantics reads them (`Exec.Workload`, delays on every stage but the
  engine), and `vllmTurn` with the cache theorem is generated from
  `cache_trace.ir.json`; no oracle program is hand-written any more.
- **The language is seQ, a separate project (2026-09-27).** The serving-
  deployment language, its interpreter and CLI
  (`seq-lang`), the example programs and the vLLM oracle with its test
  vectors are https://github.com/vrvrv/seQ (release v0.1.0-dev3); this
  repository uses the pinned release as a Cargo git dependency and through
  `.seq/` (`docs/seq.md`). The Lean model of the language stays here
  (`lean/ServingQueueTheory/Seq{,Exec,Oracle,Serve}.lean`, the oracle
  theorems generated from seQ's IR files by `scripts/gen_seq_oracle.py`),
  as do the paper's replica programs (`Deployments.lean`). CI reads seQ
  with a read-only deploy key (secret `SEQ_DEPLOY_KEY`, `docs/seq.md`).
- **seQ, second pass (2026-09-27).** The vLLM program now reproduces
  the real scheduler request for request on the full short-context trace
  (3 321/3 321; six semantic gaps found by differential replay and fixed in
  the language: admission served by the engine, whole-prompt gate, partial
  reuse with dead blocks, `end` keeps the cache, admission order, release
  order); the six scenarios are Lean theorems (`SeqOracle.lean`,
  `decide +kernel`) and hold on the real A100 engine; the paper's "prefill
  from what decode leaves" equals vLLM's admission order unless a
  per-request chunk cap is set (`SeqServe.lean`, cited in §2.2). The A100
  miss under-prediction (117 vs 426) was these semantic gaps; with them fixed
  the model's remaining error is the time model (two overhead constants),
  `seQ `docs/language.md`` §8. Review round with seQ:
  `docs/reviews/2026-09-27-seq-round1*.md`.
- **seQ v0.1.0-rc0 pinned (2026-09-28).** The first release candidate:
  the per-session block is `session { … }` (IR v3, field `session`), the
  serving vocabulary (`admit … keep`, `prefill`, `decode`, `tool`,
  `transfer`) and `branch with (p)` are sugar over the kernel, the vLLM
  programs' request pool is `reqs`, and `seq-lang draw` exists. Here:
  `programs/*_vllm.seq` and the inline test programs say `session`,
  `scripts/gen_seq_oracle.py` reads IR v3, `SeqOracle.lean` regenerated
  (only its doc comments changed: pool `reqs`); the paper's replicas in
  `Deployments.lean` still use the kernel forms, and the Lean type and
  quotation keep the name `Route`/`[route| … ]`.
  **Hypothesis H-pin (new):** pinning a queued turn's cached prefix (the
  vLLM rule leaves it evictable until the turn is scheduled) removes the
  wait channel of Lecture 5 and moves the cliff; in simulation of the A100
  trace at 3.0 s spacing the full-hit rate is 0.24 under the vLLM rule and
  0.80 with pinning. Test: patch vLLM to touch a waiting request's cached
  blocks at `add_request` (and untouch on abort), replay 3.0 s and 2.5 s
  (`scripts/exp/lambda/steptrace/pinpatch.py`). **Result (A100, served,
  2026-09-27, one run per point):** at 2.5 s the vLLM rule collapses (TTFT
  34.6 s, full-hit 0.22) and the pinned engine does not (0.88 s, 0.78;
  seQ pre-registered 0.89 s, 0.75); at 3.0 s both are off the cliff
  (0.44 → 0.41 s). Data `data/exp/gpu_seq/trace/`, table in
  `seQ `docs/language.md`` §8. The Lambda instance was terminated after
  the runs. Candidate for the paper's §3.3 admission step (needs a same-day
  unpinned 2.5 s rerun with the tracer and seeds before it goes in).
  **§4.2 replay in seQ (done 2026-09-27, `docs/seq-replay42.md`,
  `programs/replay_{twostage,vllm}.seq`, `scripts/exp/seq_replay42.py`):**
  the qualitative conclusions stay (open replica all hits; the admission
  cap decides thrashing under every rule set; priced ≤ LRU in TTFT); the
  quoted numbers move under vLLM's rules (block tail eviction makes misses
  partial: TTFT 1.3–3.7× lower, mixture share of variance much lower; a
  priced key that keeps finished sessions' blocks loses hit rate, so the
  §3 scheduler needs the program's end). **User decision: (b), done the
  same day:** §4.2 runs `programs/replay_vllm.seq` through
  `libqueuingsim::seq_replay` in `paper_tables.rs` (tables, Reuse column,
  macros, prose of `simulation.tex` and the intro sentence regenerated;
  `replay_twostage.seq` removed). Open for the paper: §3 could state that
  the price key needs the program's end under vLLM (the `keep=0`
  ablation), and the LRU-vs-priced margin on the trace is small (up to
  1.65× in TTFT) next to the synthetic `tab:sim-evict-dyn`.
  **Follow-up the same day (items 1–4, user request):** (1) the
  eviction/admission experiment (`tab:sim-evict-dyn`, `tab:sim-admission`,
  `fig:sim-admission`) runs `programs/open_vllm.seq` (vLLM rules, testbed
  cost, rates 0.03/0.05) through `libqueuingsim::seq_open`: priced orders
  ≈ shortest-first, LRU 1.7–3.0× TTFT, the cap decides thrashing, and with
  the end unknown the byte-second price loses its lead (text of §4.2 and
  §3.1); thrashing is now "reuse below half" (partial misses); seQ dev4
  made the interpreter 5–15× faster (identical results). (2) §3.1: the
  block problem is not a fractional knapsack (tail recompute concave,
  `tailRecompute_marginal_antitone`, `tailRecompute_subadditive`); the
  threshold results are stated with programs as units; `prop:blind` (i)
  holds for tail blocks (`price_blind_rule_unbounded_cost`), (ii) is about
  whole programs. (3) `TwoStage` documented as the §2.2 model. (4) The old
  libqueuingsim replay and open-session evidence paths and their examples
  are gone; the check `trace_replay_variance_sources` runs the vLLM-rule
  replay and expects a positive mixture share (it was > 0.3 under
  whole-session eviction; 0.06–0.23 now).
  **Then `TwoStage` removed (user request):** it was used by no in-model
  check (`miss_price_bracket` runs on a plain M/G/1); its one check,
  where a miss is paid, runs `programs/price_vllm.seq` through
  `libqueuingsim::seq_price` (check `prefill_pays_the_miss`, `tab:sim-ps`
  rows 8–9): ΔL_P inside the bracket at its upper end; the decode batch
  changes by 0.3 % (not 0: a miss's prefill lengthens shared iterations),
  so the check bounds it by 1 % and §4.2 says so. Gone with it: the
  `open_session_cfg` scenario, the seQ-vs-TwoStage cross-check, the
  `trace_html` example and the TwoStage unit tests.
  **Next for seQ** (in order): (1) keep a growing hold's position integral
  (fractional chunks lose a block when rounded, found in the replay port);
  (2) identify the served overhead constants
  from a served step trace with synchronous against asynchronous
  scheduling at light load; (3) Kani harnesses, then Aeneas, on a pure pool
  core of `seQ src/sim.rs` against `SeqLang.Step` and
  `Exec.makeRoom_room`.
- **seQ (2026-09-27): the serving-deployment language of Lecture 1
  rebuilt as a programming language for the formal verification and
  simulation of serving systems.** seQ (Rust parser, interpreter,
  CLI), `lean/ServingQueueTheory/Seq.lean` (syntax, pool semantics,
  memory invariant `SeqLang.Step.invariant`, the two replicas as
  programs, the surface syntax `[route| … ]` inside Lean),
  `seQ programs/*.seq` (M/G/1, PS, M/M/1//N, the agentic replica,
  the paper's two-resource replica, PD tandem, routing, vLLM v1, vLLM
  on the A100 replaying the short trace). Validated against the closed
  forms, the hand-written `libqueuingsim` models (now run under `make
  sim`, `libqueuingsim/tests/seq_*.rs`), the real upstream vLLM
  scheduler on six deterministic scenarios (6/6 step-exact,
  `seQ tests/vllm_oracle.rs`) and the ten measured A100 runs (one
  calibrated parameter; mean TTFT within 10–30 % below the cliff, the
  cliff at 2.5 s reproduced; `data/exp/seq/gpu.txt`). Spec
  `seQ `docs/language.md``; review of the lecture's version against
  vLLM, design, self-review and the verification-tooling survey
  `seQ `docs/review.md``. Next for seQ: an executable Lean semantics
  (`#eval`) fed by the oracle scenarios, Aeneas/Kani on the pool core,
  cross-session prefix sharing, a fluid option for the step stage, and
  the eviction under-prediction on the A100 (117 vs 426 misses at
  3.5 s).
- Paper v0.13 (2026-09-26, after the user's feedback and a clarity
  review `docs/reviews/2026-09-26-clarity.md`): §4 renamed "Results"
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
  launch, what failed and why: `docs/testbed.md`.
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
  Two failures worth knowing (details in `docs/testbed.md`): with
  `out ≤ 32` the decode batch cap bound (ITL 0.02 s idle → 0.3 s
  loaded, running = 8); at 1.5 s spacing the pool's 4096-token blocks
  filled at ~20 live sessions per rank, LRU evicted the prefixes with
  the longest gap (every miss followed a 30 s gap) and the replica
  thrashed (TTFT 0.6 → 3.6 s over the run). On this stack a prefill
  step is exclusive and has priority over decode, and the DP+EP ranks
  step in lockstep, so ITL rises 100× under prefill load (0.017 s idle,
  0.10 s when a peer rank prefills, 0.17–0.25 s when the own rank does;
  `docs/testbed.md`). The paper's "prefill from the budget decode
  leaves" is reversed here; §6 says so.
- Review round 5 (2026-09-26, `docs/reviews/2026-09-26-round5.md`,
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
  `scripts/exp/memory_model.py`, `docs/memory-model.md`,
  `docs/reviews/2026-09-26-memory-round{1,2,3}*.md`, outputs
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
  `docs/analytic-memory.md`, Lean `MissFeedback.lean` (Tarski extremal
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
   charged c0 as engine time; see docs/memory-model.md "Deviations and
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
   `make exp` tables labelled model output (AGENTS.md rule 7 now admits
   simulator numbers only via `paper/simulation.tex`)? (b) Decode probe
   on an idle server, E1-style: decode step time vs batch b ∈
   {1,2,3,4,5,8} (compiled buckets 1,4,8) and context, mixed contexts,
   equal and unequal load across ranks, decode rate while a peer or the
   own rank prefills, and the prefill stretch measured directly.
   (c) A step-level lockstep model on one clock for all ranks, a
   preemption frees its victim. (d) Pre-register the validation in
   docs/memory-model.md (date, git hash) before the first run: s10c8 and
   s15_base held out, s15 reproduced without a prefill-stretch factor, no
   parameter from E2/E2b. (e) Then the model-based price of a miss at
   50k contexts (force single turns to miss, measure the added summed
   TTFT) against the bracket of `prop:price`; later port the pool
   mechanics into libqueuingsim so §4.2's replica is the validated one.
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
   simulator (needs a `TraceCorpus` loader for that JSONL) and compare
   with `tab:e2`/`tab:e2b` per rank (Kendall τ, TTFT MAPE).
4. Remaining review-3 leftovers: UNVERIFIED venue notes in
   `paper/refs.bib`.
5. If more server time: E2b at a 5 % forced share (round-5 item 7b),
   a short-context baseline with the real gaps (7c; the 30 s cap is the
   atom LRU evicts), and the real gaps for the 50k trace.

**Do not.** Attribute a bracket overshoot to the prefill-time
inflation (scaling every service time by it over-corrects; round 5
issue 1). Type measured numbers into the paper; run two replays at
once on the server; leave caches under `~/.cache` (see CLAUDE.md);
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
- memory: `β K` bytes while resident; shared by paused states and the
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
- `prop:memory`: θ-threshold rule is optimal for the relaxed problem;
  block-level density order is optimal up to one block.
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

## 2. Paper structure (v0.7: sessions + two-resource replica + memory price; §3 proposes the scheduler)

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
| 4.2 | Uncalibrated simulation (`paper/simulation.tex`: summaries + `tab:sim-inmodel`, `fig:sim-admission`, `tab:sim-trace`; other tables in App. B) | none (checks of the props above) | none |
| App. D | Experimental design for a real system (`app:design` = `sec:exp-real`): overview table + one paragraph E1–E6; result-table layouts in §4.2a below | none | none |
| App. A | Human-readable proofs (price, decode, blind) | | |
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
only standard axioms (`make lean` reports `OK: 57 theorems audited`).

| Result | Status | Notes |
|--------|--------|-------|
| `prop:price` (prefill queue, FIFO) (i) bracket, (ii) term ratios, (iii) unbounded | proved | central result. M/G/1 with PK used as an approximation (session feedback, fluctuating budget) |
| `prop:decode` (PS) (i) monotone ⇒ ranking by work, (ii) closed-form exact change for constant capacity, (iii) unbounded | proved | (i) is proved in Lean for finite truncations; the untruncated case is the limit (App. A proof). Insensitivity itself is cited (BCMP/Kelly) |
| `prop:memory` (i) θ-threshold optimal, (ii) blocks: density optimal up to one block | proved | both are the exchange lemma `threshold_prefix_le` read two ways |
| footprint examples (§2.2 prose; was `prop:footprint`) | proved | the review's two examples; `decide +kernel` on ℚ; demoted to one sentence in v0.7 |
| `prop:guarded` (i) plain density unbounded, (ii) guarded 2-approx | proved | (ii) is proved as a certificate lemma (`guardedGreedy_two_approx`): hypotheses encode the greedy's sorted-prefix property; the algorithm itself is not formalised |
| `prop:pk`, `prop:cache` | proved | trivial parts dropped from the statements; M/M/1 unboundedness now lives in the `prop:routing` proof |
| `eq:cv2` numbers | proved | the core argument that variance comes from the miss penalty |
| option value (prose in §3.3) | proved | trivial math, so demoted from a proposition to a prose sentence; its value is in reading ThunderAgent A.2 correctly |
| `prop:blind` (i) any price-blind rule unbounded | proved | `price_blind_rule_unbounded`; the rule is an arbitrary function of any observation type except `p` |
| `prop:blind` (ii) SF = `w=c²` price-per-byte order, feasible, 2-approx + tightness | proved | formerly `prop:evict` (ii); v0.1 wrongly said the ratio is unbounded |
| SF not optimal on `{4,5,6}`, ΔC=6 | proved | prose sentence after `prop:blind` with inline `\provedby`; contradicts ThunderAgent App. F.3 |
| `prop:pd` | proved | capacity model only, no batching |
| `prop:routing` (i) inversion load closed form, (ii) monotone in move cost; `eq:lookahead`, `eq:append` | proved | v0.7: the existence statement became the closed form `λ*`; a shared KV store (Mooncake, LMCache) enters as a smaller `M_j` (priced fetch instead of `Φ_i`) |

Candidate results, not yet in the paper. Each needs a Lean proof, or a
citation to an established theorem, before it becomes a proposition:
- ~~Finite-source price~~ done round 3 as `prop:finite` (Lean `FiniteSource.lean`:
  MVA recursion, `mvaQ_mono`, `finite_source_wait_le_open`,
  `closed_price_cap`). Still open: the M/G/1//N inequality for general
  work laws (the replay supports it for a few misses and refutes it for
  many: `tab:sim-trace-price`).
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
   survives. Synthetic workloads, fixed seeds. Reported in paper §4.1.
2. **Empirical (E1–E6), next.** Measure on the NPU testbed and on traces.
   The hypotheses and the quantities each experiment must record are
   those that phase 1 showed to decide the outcome.
3. **Calibrated simulation, after E1.** Plug the E1 fits into the
   simulator (M5 in `docs/simulation-design.md`) and score it with the
   analytical model against the testbed (E6).

Platform codes: T = NPU testbed, S = simulator (`libqueuingsim`,
`docs/simulation-design.md`), O = offline on traces.

### 4.1 Phase 1: simulation (uncalibrated)

Status: 31 of 31 checks pass (`make sim`; report via `make report`). What
each part established, and what it changes for phase 2:

| Question | Result under the synthetic model | Consequence for phase 2 |
|----------|----------------------------------|-------------------------|
| Do the closed forms hold in their own model? (M/M/1, `prop:pk`, `prop:cache`, `eq:cv2`, `prop:pd`, `prop:blind`(ii)) | yes, within CI or 2 % | the simulator is usable for the questions below |
| Does PK survive bursty arrivals? | no: it underestimates; Kingman's bound holds | E2 records interarrival CV² next to the PK ratio |
| Does throughput fall with N only through the hit rate? | yes: with finite KV it falls; with ample KV it follows `min(N/(D+Z),1/D)` | E3 records hit rate and resident KV per concurrency level |
| Is always-offload harmful? (option value, now one sentence in §3.3 scheduler paragraph; tab-offload generated but not shown) | only with blocking fetches; with async fetches the tier queue acts as admission control and always-offload is best | E3 records whether the stack fetches synchronously; the policy ranking depends on it |
| Does the PK bracket of `prop:price`(i) hold in simulation? | yes: ΔL inside the bracket, near its upper end (δ=0.01, 0.05) | E2 forces misses on a controlled fraction and compares ΔL with the bracket |
| Is the guard of `prop:guarded` needed, and does it help? | offline guarded ≤ 1.87×OPT everywhere and best mean in every row; plain density reaches 6.7× on random arbitrary-weight instances (unbounded only on the witness family) | E4 reports guarded next to plain density |
| Does the offline density advantage carry over? (`prop:blind`(i)) | offline density ≫ SF when `p_i` vary; in the closed system the two are within seed noise, LRU is worse | E4 reports end-to-end TTFT and throughput next to cost/OPT, and measures the spread of `p_i` |
| Does PS insensitivity hold, and does the product form survive session feedback? | yes: deterministic vs hit/miss work give the same L under PS (FIFO separates them as PK says); Poisson sessions + closed loop + H2 tools match the isolated PS formula at λ=Λ/(1−p) for constant and saturating φ | E2 tests insensitivity by comparing chunked vs blocking prefill at equal load |
| Does the PS price bracket (`prop:price`(ii)) hold? | yes; the simulated ΔL sits at the upper end, which the proposition says is exact | E2 forced-miss test uses both brackets |
| Is "φ flattened at B" a good model of a real batch cap (LPS)? | at half load yes (≤1 %); at u=0.8–0.9 the error follows the service CV²: −10/−22 % for deterministic work, +29/+51 % for CV²=4. A capped batch is not insensitive, and hit/miss work (CV²>1) makes the model underestimate congestion near saturation | E1/E2 must report the batch-cap regime; theory needs an LPS correction or an explicit statement of this error |
| Do the footprint examples (§2.2) hold in Monte Carlo? | yes (2 / 1.75 / 1 / 1.4844) | E1 measures batch size under the measured footprint law |
| Two-resource replica (v0.6): is the price paid in the prefill queue and is decode insensitive? | yes: forced misses raise L_P inside the `prop:price` bracket (availability 0.96) and leave L_D unchanged to 4 decimals; in the open scenario p99 TTFT is 10–17× its mean (HoL behind document misses) while R − TTFT is a constant decode time | E2 measures TTFT and decode occupancy separately |
| Does the byte-second key (`prop:memory`, τ-aware) beat density/SF end-to-end? | best or tied in most cells (cap 24, Λ=0.28: TTFT 2.64±0.41 vs Density 3.58±0.65; X 2.67 vs 2.48) but never separated beyond seed noise; block-level ≈ τ-key; LRU worst by ≥2× throughput | E4 needs many seeds or a paired design; the effect is second-order next to admission |
| Does the admission cap move the thrash window? | strongly: cap 16 → hit 0.99, TTFT < 0.4 s at both loads, no thrash; cap 24 → hit degrades to 0.77 at Λ=0.28; cap 32 → 15–20/20 seeds thrash, X −40 %, TTFT 15 s. Cost of a tight cap = entry-queue wait. At Λ=0.28 offered load exceeds capacity (~2.6 turns/s) under any cap | E4 sweeps the cap; admission is a first-class policy dimension |
| Does eviction policy matter with open sessions on a batching replica? (v0.5 single-PS replica, superseded) | only in a narrow load window (Λ≈0.23–0.3 in the scenario). Below it no evictions; above it both PS and blocking replicas thrash whatever the policy. Inside it: LRU worst; SF, Density and Priced within seed noise; Priced ≡ Density under PS (as `prop:price`(i) requires) and indistinguishable under blocking. **Thrashing (bistable hit rate) dominates**: misses pin KV in the batch, which evicts more, which causes more misses. PS with φ≡1 thrashes earlier than blocking because turns stay in the batch longer | E4 must include admission/memory control as a policy dimension, report per-seed hit-rate trajectories, and define the load window; the price of a state may be dominated by the thrash it can trigger, a transient effect outside both price propositions |
| Do the congestion terms of `Φ` change eviction end-to-end? | not in the closed two-class scenario: Priced = Density at N=24,32, within CI at 12,16. Consistent with `prop:price`(ii): waits of tens of s make the load term dominate, so `v_i` ∝ density key; throughput scoring also ignores delay | E4 must include a regime where the mean wait is comparable to a miss (open arrivals below saturation, p99 TTFT); this is where the price can differ from density. Open populations in the current simulator thrash (metastable) and need admission control first |
| Does priced offloading beat selective? | no: ≤ selective in every cell (blocking fetches reduce both tests to transfer < ΔS) | E3 keeps selective as a baseline |
| Does the PD win condition pick the winner? (`prop:pd`(iii)) | 32/32 decisive grid cells agree | E5 tests the condition from measured parameters as planned |
| Does equal capacity mean equal latency? | no: PD latency is higher at the rate-matched split (pooling) | E5 reports latency as well as throughput |
| Does strict affinity fail at high load? (`prop:routing`) | yes once the hot replica saturates; lookahead with cheap migration stays flat | E6 measures migration cost, which sets the inversion load |

Phase 1 numbers are properties of the simulated model. They appear in the
paper only in §4.1, generated from the simulator, and never in a `\tbd`
cell.

### 4.2 Phase 2: empirical validation

Order matters: E1 gates everything, and E2 is the first result worth
reporting because it tests the paper's stance on variance (AGENTS.md
rule 5).

| ID | Question | Tests | Where | Needs (incl. from phase 1) | Status |
|----|----------|-------|-------|----------------------------|--------|
| E1 | Fit `S_prefill(L,K,B)`, `S_decode(B,KV)`, `T_transfer(bytes)` | calibration | T | profiling harness | **prefill fit done 2026-09-24** (paper §4.3, `tab:e1`): MiniMax-M2.7 fp8, DP4+EP, block 4096, sub-block prefix cache on, no LMCache (`scripts/exp/serve_m27.sh`, `docs/testbed.md`); 45 probes pinned to one DP rank, `P(n,K)=c0+an+bn(K+n/2)` with a=0.194 ms/token, b=6.51 ns/token², K_c≈30k tokens, MAPE 3.4 % (held-out cold→append 3.7 %); generated by `make exp`. Decode step time, transfer and φ(n) not yet measured |
| E2 | How does per-turn Var[S] split between the append and the hit/miss mixture, and does the mixture's share grow under eviction from the trace baseline (Weka: 57 % at p = 0.96, linear cost; `docs/trace-analysis.md`)? Does `W_q` track `(1+CV²)/2`? Does forced-miss ΔL fall in the `prop:price` bracket? | `prop:pk`, `eq:cv2`, `prop:price` | T, S | E1, replayed traces (Weka sequences), interarrival CV², miss injection | trace baseline done (2026-09-23); replayed in simulation 2026-09-24 (`tab:sim-trace`, `tab:sim-trace-price`); testbed run in progress 2026-09-24 (`scripts/exp/run_e2.sh`: open-loop replay of fsw-415 cc_traj_50k with a live-session cap; `analyze_e2.py`) |
| E3 | Is priced offloading never below never-offload? When is always-offload below it? | option value (§3.3) | T, S | E1, tier bandwidth, fetch mode (sync/async) | not started |
| E4 | SF vs price per byte vs guarded vs exact optimum, offline and end-to-end; LRU vs hit-ratio vs price | `prop:guarded`, `prop:blind` | O, S | traces with resume events, spread of `p_i`, a regime with mean wait comparable to a miss | not started |
| (PD) | Does the PD inequality predict the winner? What is the latency cost at equal capacity? (follow-up paper, see §4.2b) | `prop:pd` | T | E1, measured `I, g_P, g_D` | not started |
| E5 | At what load does affinity lose? Is it `ρ*` of `prop:routing`(i)? Does a shared KV store (fetch instead of recompute) move it as (ii) says? | `prop:routing`, `eq:lookahead`, `eq:append` | T, S | E1, migration/fetch cost | simulated 2026-09-24 (`tab:sim-inversion`: monotone in move cost; `ρ*` matches for cheap moves, link saturation for expensive ones); testbed not started |
| E6 | Decision-faithfulness scorecard (Kendall τ, argmin agreement, MAPE) | whole model | T, S | E1 to E5, phase 3 | not started |

Details per experiment are in paper §4.2. The table layouts there are the
contract: fill `\tbd` cells with measured values only, and do not change
what a table measures without updating this file.

### 4.2a Result-table layouts (moved out of the paper on 2026-09-23)

The paper keeps only the experiment-overview table and short hypotheses
(§4.2). The layouts below are the contract for what each experiment
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
| Share of Var[S]: hit/miss mixture (trace baseline, no eviction: 57 % at p = 0.96 linear, 35 % at K_c = 100K; `docs/trace-analysis.md`) | TBD |
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
| Guarded (program-level, prop:guarded) | TBD | TBD | TBD |
| Block-level density (prop:memory) | TBD | TBD | TBD |
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
`models/pd.rs` and the `tab-pd*` generators stay in the repository for
the follow-up paper. The PD experiment (formerly E5) is no longer in the
paper's numbering: E5 = routing, E6 = scorecard.

### 4.3 Phase 3: calibrated simulation

After E1: continuous batching, block-level KV, trace replay and the E1
service fits (milestone M5). Ladder step 5 then compares the calibrated
simulator with the testbed at the E6 held-out points. Its numbers may
fill the "Simulator" columns of `tab:scorecard`; they replace nothing in
§4.1, which stays the uncalibrated baseline.

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
The simulator is `libqueuingsim` (Rust); `docs/simulation-design.md`
has its design, status and roadmap. It serves E2 (hit-rate sweeps), E3,
E4 (end-to-end), E5 and E6. E1 and the PD experiment are testbed-only; E4's cost/OPT
column is offline. Milestones M0 to M4 are built on synthetic workloads
(offline oracle, fair-share links and dynamic PD still open).
Uncalibrated numbers go in the paper only in §4.1, labelled as
simulation of the model. Any simulator number in §4.2 or in
`tab:scorecard` needs the calibrated simulator (M5), which needs E1.

## 5. Claims we must not make (until data exists)

- That agentic workloads are "high variance" or "long-tailed" (AGENTS.md
  rule 5). Say that variance comes from the hit/miss mixture and that E2
  measures it.
- That PD does or does not help agentic serving in general. Say which
  regime of `prop:pd`(iii) applies.
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
