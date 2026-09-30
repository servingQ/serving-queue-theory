# Simulation validation design (the `validation` package)

Design and status of the simulation checks. Read
`research/research-plan.md` first: the simulator is the first validation
phase, and the empirical programme (E1–E6) follows it.

Status (2026-09-29, later): `validation` is a Python package (it was a
Rust crate). Every simulation is a serQ program run by the CLI of the release
pinned in `validation/pyproject.toml`; the package keeps the configurations,
the analytic references, the offline eviction instances, the statistics
and the table generation. It reproduces the crate bit for bit (rand 0.9's
`StdRng` and Rust's number formatting are ported in `rng` and
`fmt`): the report and every file of `paper/sim/` came out
unchanged. Rust remains only to build the serQ CLI.

Status (2026-09-29, draft): the queue, PD, routing, agentic and sampled-work
batch checks all execute serQ programs. `validation` retains the paper's
configuration, analytic checks, statistics and table generation; its own
event scheduler and agentic/batch event loops have been removed. The old
batch token-work and blocking-prefill variants were used only by internal
tests and are no longer part of the Rust configuration API. The detailed
vLLM scenarios continue to run through the serQ programs below.

Status (2026-09-27, later): the validation crate's `TwoStage` server (the §2.2
replica with its own memory model: whole-turn KV reservation,
whole-session eviction, no preemption) is removed. The paper's evidence
on where a miss is paid, on eviction and admission, and the trace replay
runs vLLM v1's engine rules as serQ programs
(`programs/{price,open,replay}_vllm.sq`, `serq_{price,open,replay}`)
with the testbed's cost model; the propositions' in-model checks use
their own closed-form queues (M/G/1, PS).

Status (2026-09-27): since this date the scenarios can be written as
serQ programs (serQ, a pinned release: `research/seq.md`; spec serQ
`docs/language.md`); `validation` depends on serQ's crate `serq` and `make sim` runs the programs next to
the hand-written models (`validation/tests/seq_*.rs`). The vLLM
engine (serQ `programs/vllm.sq`) and its A100 replay
(`vllm_replay.sq`) are the calibrated-simulator items of §6 below
that serQ now covers: continuous batching with a token budget, chunked
prefill, block-level KV with LRU, preemption, trace replay, the E1 fits
per chunk. Status (2026-09-23): the **uncalibrated** simulator exists in
`validation/` (Rust). It covers validation-ladder steps 1–4 and reports
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

Python (`validation/pyproject.toml`, `uv.lock`; numpy), with serQ as the
engine: each model renders its configuration into a serQ program and reads
the observations back from the CLI's JSON summary and per-sample dump.
Everything is seeded, and a seed gives bit-identical output on the same libm
(CI runs on `ubuntu-22.04` for that reason).

The modules are layers (`validation/README.md`, enforced by
`tests/test_layers.py`): `theory` never imports serQ, `sim` never imports
`checks`, nothing imports `report`.

| Module | Contents |
|--------|----------|
| `theory.dist` | Deterministic, Exponential, Erlang, balanced H2, Uniform, Discrete, HitMiss, Bernoulli; exact moments and seeded sampling |
| `theory.analytic` | one function per Lean definition (`mm1Wait`, `pkWait`, `mixtureCV2`, `pdFullCapacity`, `lookaheadCost`, …) |
| `theory.queue` | Lindley's recursion on the streams of `mg1.sq` (the cross-check of the event engine) |
| `theory.batch`, `theory.pd` | the PS capacity `φ(n)` and its mean number; FIFO admission by footprint; the capacity of an integer PD split |
| `theory.eviction` | offline instances; SF (and the literal Lean `shortestFirst`), density, guarded density, exact DP optimum |
| `sim.serq` | runs a serQ program in process with pyserq and reads its report |
| `sim.laws` | a law as an expression in serQ's sampler |
| `sim.stats` | Welford moments, batch means (20 batches), replication CIs, quantiles, paired differences |
| `sim.queue` | serQ's `mg1.sq` as an open G/G/c FIFO queue; separate streams for arrivals and service |
| `sim.agentic` | `programs/agentic_model.sq`: closed or open agent programs on one replica with a finite KV pool; eviction, offload and fetch-mode policies |
| `sim.pd` | serQ's `pd_tandem.sq`, `pd_open.sq`: aggregated pool vs prefill → KV link → decode tandem |
| `sim.routing` | serQ's `routing.sq`: affinity, least-loaded, least-loaded with fetch, KV-aware myopic, lookahead with migration |
| `sim.workload` | replayed real sessions (`TraceCorpus`, bundled `validation/data/weka-sessions.csv` from the cc-traces-weka corpus) |
| `sim.price_vllm`, `sim.open_vllm`, `sim.replay_vllm` | the vLLM-rule replica: `programs/{price,open,replay}_vllm.sq` |
| `checks` | named checks, one or more per proposition; shared by tests, report and paper tables |
| `report.validation`, `report.paper_tables` | the Markdown report and the paper's tables |

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

- `src/checks.py`: 35 checks. *In-model* checks keep a proposition's
  assumptions, so a failure means a bug. *Beyond-model* checks drop one
  assumption and test the decision. `observations()` prints results with
  no asserted prediction.
- `tests/test_propositions.py`: one test per check (marker `checks`).
  `tests/test_lean_examples.py`: `theory.analytic` at every numeric instance
  proved in Lean.
- `report.validation`: Markdown report (CI job summary and artifact).
- `report.paper_tables` (`make tables`): writes `paper/sim/*.tex`, which
  `paper/simulation.tex` inputs. No simulator number is typed by hand.
- `scripts/check_sim.sh` (`make sim`): cited Lean names exist, `ruff`,
  `pytest` and the report. Paper tables and figures are regenerated
  manually with `make tables` and `make figs`.

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
DP optimum vs brute force, `shortest_first` vs the Lean definition.

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

Each item is a serQ program (or a serQ extension) with an adapter here.
Every new model gets in-model checks in `checks.py` before it is used for a
beyond-model question.

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
