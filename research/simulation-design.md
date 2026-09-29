# Simulator design (`libqueuingsim`)

Design and status of the discrete-event simulator. Read
`research/research-plan.md` first: the simulator is the first validation
phase, and the empirical programme (E1–E6) follows it.

Status (2026-09-29, draft): the queue, PD, routing, agentic and sampled-work
batch checks all execute seQ programs. `libqueuingsim` retains the paper's
configuration, analytic checks, statistics and table generation; its own
event scheduler and agentic/batch event loops have been removed. The old
batch token-work and blocking-prefill variants were used only by internal
tests and are no longer part of the Rust configuration API. The detailed
vLLM scenarios continue to run through the seQ programs below.

Status (2026-09-27, later): libqueuingsim's `TwoStage` server (the §2.2
replica with its own memory model: whole-turn KV reservation,
whole-session eviction, no preemption) is removed. The paper's evidence
on where a miss is paid, on eviction and admission, and the trace replay
runs vLLM v1's engine rules as seQ programs
(`programs/{price,open,replay}_vllm.seq`, `libqueuingsim::seq_{price,open,replay}`)
with the testbed's cost model; the propositions' in-model checks use
their own closed-form queues (M/G/1, PS).

Status (2026-09-27): since this date the scenarios can be written as
seQ programs (seQ, a pinned release: `research/seq.md`; spec seQ
`docs/language.md`); `libqueuingsim` depends on seQ's crate `seq-lang` and `make sim` runs the programs next to
the hand-written models (`libqueuingsim/tests/seq_*.rs`). The vLLM
engine (seQ `programs/vllm.seq`) and its A100 replay
(`vllm_replay.seq`) are the calibrated-simulator items of §6 below
that seQ now covers: continuous batching with a token budget, chunked
prefill, block-level KV with LRU, preemption, trace replay, the E1 fits
per chunk. Status (2026-09-23): the **uncalibrated** simulator exists in
`libqueuingsim/` (Rust). It covers validation-ladder steps 1–4 and reports
in paper §4.1 (`sec:sim`). The **calibrated** simulator of paper §4.2
(continuous batching, block-level KV, trace replay, E1 service fits) is
the roadmap in §6 below and is not built.

## 1. Why a simulator

The closed-form model (paper §§2–6) ignores correlated turn arrivals,
emergent hit rates, tandem pools, bandwidth sharing and continuous
batching. The testbed has all of these but is slow to sweep and cannot
compute counterfactuals. For example, it cannot run the exact eviction
optimum on the same arrival sequence. The simulator sits between the
two, in two roles:

1. **Before the testbed (now).** Check each proposition in its own model,
   then drop one assumption at a time and ask whether the decision it
   implies survives. The results shape which hypotheses E2–E6 test and
   what they must record (§5 of the research plan).
2. **After E1.** With measured service curves, be the second model scored
   in E6 against the testbed.

| Experiment | Simulator role | Reason |
|------------|----------------|--------|
| E1 calibration | none | testbed profiling only; the simulator *consumes* E1 |
| E2 variance | hit-rate sweep | the testbed measures CV² at its natural hit rate; the simulator sweeps `p` on identical arrivals |
| E3 offloading | grid | concurrency × policy × tier bandwidth × fetch mode is too large for the testbed; it checks 2–3 points |
| E4 eviction | end-to-end TTFT | cost/OPT is offline; end-to-end needs replay of identical arrivals |
| E5 PD | latency at equal capacity | the win condition is closed form; latency is not |
| E6 routing | inversion load | needs a fine load sweep |
| E7 scorecard | second model | the calibrated simulator is scored against the testbed |

## 2. What exists

Rust 2024, toolchain pinned by `libqueuingsim/rust-toolchain.toml`, one
dependency (`rand`). Single-threaded event loop; everything is seeded,
and a seed gives bit-identical output on the same libm (CI runs on
`ubuntu-22.04` for that reason).

| Module | Contents |
|--------|----------|
| `engine` | future-event list (`BinaryHeap`, ties broken by insertion order), clock, `Model` trait, `run` |
| `dist` | Deterministic, Exponential, Erlang, balanced H2, Uniform, Discrete, HitMiss; exact mean and second moment for each |
| `stats` | Welford moments, time averages, batch means (20 batches), replication CIs, quantiles |
| `analytic` | one function per Lean definition (`mm1Wait`, `pkWait`, `mixtureCV2`, `pdFullCapacity`, `lookaheadCost`, …) |
| `models::queue` | open G/G/c FIFO; separate RNG streams for arrivals and service; Lindley cross-check |
| `models::agentic` | closed or open agent programs on one replica with a finite KV pool; eviction, offload and fetch-mode policies |
| `models::eviction` | offline instances; SF (and the literal Lean `shortestFirst`), density, exact DP optimum |
| `models::pd` | aggregated pool vs prefill → KV link → decode tandem; saturated (capacity) or Poisson (latency) load |
| `models::routing` | replicas with per-program KV locality; affinity, least-loaded, least-loaded with fetch (always-move over a shared store), KV-aware myopic, lookahead with migration |
| `workload` | replayed real sessions (`TraceCorpus`, bundled `data/weka-sessions.csv` from the cc-traces-weka corpus); `batch` plays them turn by turn |
| `validation` | named checks, one or more per proposition; shared by tests, report and paper tables |

### Modelling choices in the agentic model

- **Service time** per turn: `s0 + a·new + b·new·(cached + new/2) + d·out`.
  A miss re-prefills the whole context, so its cost is quadratic in
  context length (ThunderAgent Lemma 4.1). The replica serves one turn at
  a time; per-turn costs are amortised, not batched.
- **Resume uncertainty.** Whether a program issues another turn is drawn
  when its tool call returns. A paused program therefore holds KV that
  may never be reused; this is what gives `p_i` a role in eviction.
- **Eviction scope.** Programs in a tool call are evicted first, queued
  programs only if that is not enough. Policies: shortest-first,
  longest-first, LRU, random, density `p_i ΔS_i / c_i`.
- **Offload.** Never, always, or selective (per-program argmin of
  transfer time vs recompute, with the congestion factor of Eq. utility).
  Reads and writes share one FIFO tier link.
- **Fetch mode.** `Async`: the fetch completes before the turn queues.
  `Blocking`: the replica waits for the tier. The two give opposite
  answers to "is always-offload harmful?" (paper Table `tab:sim-offload`),
  so E3 must record which one the real stack does.

### Checks, reports and paper tables

- `src/validation.rs`: 22 checks. *In-model* checks keep a proposition's
  assumptions, so a failure means a bug. *Beyond-model* checks drop one
  assumption and test the decision. `observations()` prints results with
  no asserted prediction.
- `tests/propositions.rs`: one test per check (a guard test fails if a
  check has no test). `tests/lean_examples.rs`: `analytic` at every
  numeric instance proved in Lean.
- `examples/validate.rs`: Markdown report (CI job summary and artifact).
- `examples/paper_tables.rs`: writes `paper/sim/*.tex`, which
  `paper/simulation.tex` inputs. No simulator number is typed by hand.
- `scripts/check_sim.sh` (`make sim`): cited Lean names exist, `cargo fmt`,
  `clippy -D warnings`, tests and report. Paper tables and figures are
  regenerated manually with `paper_tables` and `make figs`.

## 3. Validation ladder

The simulator is trusted for a use only after the steps below it pass.

| Step | Check(s) | Status |
|------|----------|--------|
| 1. M/M/1: `W = 1/(μ−λ)` at λ ∈ {5, 8, 9}, μ = 10 (M/M/1 closed form) | `mm1_response_time`, `mm1_blowup` | pass |
| 2. M/G/1: PK for D, E4, H2, two-point service; ratio `(1+CV²)/2` (`eq:pk`, `eq:cv2`) | `pk_formula`, `variance_orders_delay`, `cache_reuse_lowers_delay`, `cv2_ratio` | pass |
| 3. Closed network: `R = N/X − Z`; throughput non-decreasing in N with fixed demand, below `min(N/(D+Z), 1/D)` | `interactive_response_time_law`, `closed_throughput_nondecreasing_fixed_demand` | pass |
| 4. PD capacity: saturated tandem matches `min(N_P g_P/s_P, N_D g_D/s_D, B/E[K])` (`prop:pd`) | `pd_capacity_matches`, `pd_no_gain` | pass |
| 4b. Finite-source prefill queue: M/M/1//N exact wait vs simulation at ρ = 0.6, N ∈ {2,…,64}; open M/M/1 wait is above it, ratio 4.5 → 1.09 | `finite_source_wait_below_open` (`paper/sim/tab-finite.tex`) | pass |
| 4c. Inversion load: M/M/1 node crosses the move cost at ρ* (in model); always-move vs affinity over 4 replicas and a shared link (beyond) | `inversion_load_closed_form`, `inversion_load_rises_with_move_cost` | pass |
| 4d. Replayed production sessions: variance sources and PK overstatement | `trace_replay_variance_sources`; observation `trace_replay_miss_price` | pass |
| 5. Calibrated vs testbed: with E1 fits, TTFT and throughput at the E6 held-out points; report MAPE (`tab:scorecard`) | none yet | needs E1 and M5 |

Also covered, outside the ladder: Little's law, Lindley vs DES (bit-level),
DP optimum vs brute force, Rust `shortest_first` vs the Lean definition.

## 4. Results that feed the empirical plan

From `make report` (synthetic workloads; not measurements):

- Bursty arrivals make PK underestimate the wait; Kingman's bound holds.
  E2 should report the interarrival CV² next to the PK ratio.
- With finite KV the hit rate, and with it throughput, falls with N; with
  ample KV throughput follows the asymptotic bound. The collapse needs
  memory pressure, not agentic service times per se.
- Always-offload is harmful only with blocking fetches. With async
  fetches the tier queue acts as admission control.
- Offline, density beats SF by a wide margin when `p_i` vary. In the
  closed system the two are within seed noise and LRU is worse. E4 must
  report end-to-end metrics, not only cost/OPT.
- PD at the rate-matched split has equal capacity but higher latency
  than aggregation (pooling). E5 should report latency too.
- Strict affinity collapses when the hot replica saturates; lookahead with
  cheap migration stays flat. E6 must measure migration cost, which moves
  the inversion load.
- Inversion load (`tab:sim-inversion`, 2026-09-24): always-move over a
  shared link beats affinity at a load that rises as the link slows, as
  `prop:routing`(ii) says; the affinity node's utilisation at the inversion
  follows `ρ*` for cheap moves and exceeds it for a link slower than a
  recompute, because the shared link saturates. Lookahead is below both at
  every load.
- Replayed production sessions (761 Claude Code sessions, contexts ~400k):
  with no eviction the follow-up prefill work has CV² 35–43 from the
  appends alone; with a finite pool the admission cap decides between a
  regime where the mixture is 38–75 % of Var[S] (tight cap) and thrash
  (loose cap). PK from measured moments overstates the prefill wait 4–20×:
  the live sessions are a finite population (2–24) and arrivals are
  self-limiting. E2 must report live sessions next to load, and a closed
  (finite-population) correction of `prop:price` is a candidate result.

## 5. Out of scope

Collective contention inside a model-parallel group, kernel-launch
jitter, allocator behaviour beyond block counts, network head-of-line
blocking. Where the E7 error decomposition blames these, report the gap
rather than model them.

## 6. Roadmap to the calibrated simulator

Each item is a new module or an extension, in Rust, behind the existing
`Model`/`Scheduler` engine. Every new model gets in-model checks in
`validation.rs` before it is used for a beyond-model question.

| Item | Where | Needed for |
|------|-------|------------|
| Continuous batching with a token budget per iteration, chunked prefill; `IterationStart`/`IterationEnd` events | new `models::engine_batched` (or `replica`) | E2, E3, E6, E7 |
| Service model from E1 fits `S_prefill(L,K,B)`, `S_decode(B,KV)` evaluated per iteration, optional residual noise | new `service` module; fit files under `data/` | M5 |
| Block-level KV pool per device and tier; residency map program → location | extend `agentic` | E3, E4 |
| Links with fair-share bandwidth (replace FIFO tier and migration links) | new `transfer` module | E3, E6 |
| ~~Trace replay (per-turn arrivals, tokens, tool time, resume events)~~ done 2026-09-24: `workload::TraceCorpus` + `BatchConfig::trace`; scenario `validation::trace_replay_scenario` → `paper/sim/tab-trace.tex` | `workload` | E2, E4, E7 |
| Oracle eviction using realised future resumes (DP over blocks) | extend `eviction` + `agentic` | E4 lower bound |
| Dynamic PD with per-turn append-prefill routing (`eq:append`) | extend `pd` / `routing` | E5, E6 |
| Per-turn records (program, turn, arrival, first token, finish, hit length, replica, bytes, decisions) to CSV or Parquet; runs keyed by (config hash, seed); ≥ 5 seeds per point | new `records` module + CLI example | all |

If E1 shows that service curves are simple (for example, linear in new
and cached tokens with a batch term), try a semi-analytical model (MVA
with load-dependent servers) for E3 and E6 before building batching.

## 7. Milestones

| M | Deliverable | Depends on | Status |
|---|-------------|------------|--------|
| M0 | engine, distributions, statistics, open queue; ladder steps 1–2 | none | done |
| M1 | closed agent programs with tool time and finite KV; ladder step 3 | M0 | done |
| M2 | eviction policies, offline exact optimum; oracle with realised resumes | M1, trace format | offline done; oracle open |
| M3 | offload tier, fetch modes, selective policy | M2 | done (FIFO link); fair-share links open |
| M4 | PD pools and routers; ladder step 4 | M3 | done (static PD); dynamic PD open |
| M5 | continuous batching, block KV, trace replay, E1 fits; ladder step 5; E7 | E1 data | not started |

M0–M4 run on synthetic workloads and feed paper §4.1. M5 cannot start
before E1.
