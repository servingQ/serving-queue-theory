# Research plan

Working reference for humans and coding agents. It records what the paper
claims, what is proved, what is pending, and in which order validation
should happen: simulation first, then empirical measurement (§4). Update it when the status of a result or experiment
changes. The paper (`paper/main.tex`) is the public statement. This file is
the internal plan and may be blunter.

Last updated: 2026-09-23.

## 1. Thesis

**Central claim (v0.6).** Every KV decision in agentic serving asks what
it costs to lose a suspended program's state. That cost is the *price of
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
- memory: `β K` bytes while resident; shared by suspended states and the
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
| 2.1 | Sessions, turns and tools (`sec:sessions` = `sec:closed`): Poisson sessions, closed loop inside, memory pressure | none | BCMP, closed-network monotonicity, Campbell (M/G/∞) |
| 2.2 | A replica: two resources and a memory pool (`sec:batch` = `sec:queue`): `eq:prefill`, `eq:decode`; prefill FIFO, decode PS; Table 1 (the model at a glance) | footprint examples (prose, `footprint_variance_*`) | Sarathi-Serve (chunked prefill), BCMP/Kelly insensitivity, PK (`eq:pk`), Kingman |
| 2.3 | Prefill work under KV reuse (`sec:congestion`) | `prop:pk`, `prop:cache`, `eq:cv2` (prefill times) | SRPT |
| 2.4 | The KV-state problem (`eq:mdp`, `eq:numsys` = L_P + L_D, shadow price θ) | none | Little |
| 2.5 | **The price of a miss** (`eq:price`, `eq:utility` = `w_i, v_i, u_i`) | `prop:price` (prefill queue: bracket; term ratios; unbounded), `prop:decode` (PS: monotone ⇒ ranking by work; closed form; unbounded) | none |
| 3 | Congestion-priced scheduling (`sec:sched`) | | |
| 3 (intro) | Algorithm 1: observe, price, set θ, evict, keep/offload/drop, place, admit; inputs and how θ is set | none (design) | none |
| 3.1 | Eviction; "Fixed keys" paragraph (SF, LRU, idle, TTL as price-blind keys; ThunderAgent Def. 4.1 / App. F.3 contradicted in one sentence) | `prop:memory` (θ threshold; blocks: optimal up to one block), `prop:guarded` (program-level 2-approx), `prop:blind` ((i) price-blind keys unbounded, (ii) SF as the `w=c²` price-per-byte order, tight 2-approx) | covering knapsack, Dantzig greedy |
| 3.2 | Placement (with or without a shared KV store: `M_j` = `Φ_i` or the priced fetch) | `prop:routing` (i) inversion load `λ* = μ − 1/(1/μ+M+F)`, `ρ* = μ(M+F)/(1+μ(M+F))`, (ii) monotone in `M`, `F`; `eq:lookahead` | none |
| 3.3 | Admission and offloading (thrashing; θ as the admission unit; keep/offload/drop; option-value sentence with ThunderAgent A.2 as a clause); closing paragraph "Fixed rules as special cases" | none (design) | none |
| 4.1 | Uncalibrated simulation (`paper/simulation.tex`, tables generated into `paper/sim/`) | none (checks of the props above) | none |
| 4.2 | Evaluation on a real system: overview table + hypotheses E1–E6; table layouts in §4.2a below | none | none |
| App. A | Human-readable proofs | | |
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
| E1 | Fit `S_prefill(L,K,B)`, `S_decode(B,KV)`, `T_transfer(bytes)` | calibration | T | profiling harness | not started |
| E2 | How does per-turn Var[S] split between the append and the hit/miss mixture, and does the mixture's share grow under eviction from the trace baseline (Weka: 57 % at p = 0.96, linear cost; `docs/trace-analysis.md`)? Does `W_q` track `(1+CV²)/2`? Does forced-miss ΔL fall in the `prop:price` bracket? | `prop:pk`, `eq:cv2`, `prop:price` | T, S | E1, replayed traces (Weka sequences), interarrival CV², miss injection | trace baseline done (2026-09-23); replayed in simulation 2026-09-24 (`tab:sim-trace`: mixture 38–75 % of Var[S] at a tight cap, 0 with no eviction; PK overstates the wait 4–20× for 2–24 live sessions); testbed not started |
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
- Per program: turn count, whether it resumed after each suspension. This
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
