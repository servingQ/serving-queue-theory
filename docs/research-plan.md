# Research plan

Working reference for humans and coding agents. It records what the paper
claims, what is proved, what is pending, and in which order validation
should happen: simulation first, then empirical measurement (§4). Update it when the status of a result or experiment
changes. The paper (`paper/main.tex`) is the public statement. This file is
the internal plan and may be blunter.

Last updated: 2026-09-23.

## 1. Thesis

A queueing model of agentic LLM serving is useful if it is **decision
faithful**: it ranks policies (eviction, offloading, PD split, routing) the
same way the real system does. Exact latency reproduction is secondary.

The model is one causal chain (paper §2):

```
eviction policy → hit rate p → (E[S], E[S²]) → (ρ, E[W_q]) → control cost (Eq. mdp) → policy
```

Every analytical result is a statement about one link of this chain, or
about a one-step approximation of the control problem.

## 2. Paper structure (v0.3: PD moved to App. B for a follow-up paper)

| § | Content | Our results | Cited theorems |
|---|---------|-------------|----------------|
| 2 | Model: service centre, KV mixture, closed network, control problem | none | Little, PK, Kingman bound, interactive response-time law |
| 3 | Congestion and the hit/miss mixture | `prop:pk`, `prop:cache`, `eq:cv2` (prose numbers) | SRPT (prose) |
| 4.1 | Offloading (+ ThunderAgent App. A.2/A.4) | option value (prose, inline proof) | none |
| 4.2 | Eviction (+ ThunderAgent Def. 4.1, App. F.3, G.3) | `prop:evict` (not optimal; 2-approx, tight; unbounded with resume probs) | Dantzig LP greedy |
| 5 | Program-aware routing | `prop:routing`, `eq:lookahead` (prose) | none |
| 6 | Experiments E1 to E7 except E5, placeholder tables (`\tbd`) | none | none |
| 6.9 | Uncalibrated simulation (`paper/simulation.tex`, tables generated into `paper/sim/`) | none (checks of the props above) | none |
| App. A | Human-readable proofs (incl. App. B props) | | |
| App. B | PD disaggregation (+ ThunderAgent Fig. 7, PPD): statement, append-prefill rule, planned E5, PD simulation paragraphs | `prop:pd`, `eq:append` (prose) | none |

Conventions that follow from the user's review of v0.1:
- Do not call the model "layered" and do not use a "Layer 1..4" structure.
- Propositions live in the section whose decision they inform. Do not
  collect them in one section.
- Published claims are discussed in the section they bear on, under
  "The claim" and "Reading the claim" paragraphs. There is no separate
  claims section.
- Lean is not visible in the paper. `\provedby{\leanref{...}}` typesets
  nothing. The only mention is one sentence at the top of Appendix A.
- Appendix proofs are ordinary mathematical proofs, not transcripts of
  Lean proofs.
- No `example` blocks between propositions (removed in v0.2). The two
  numbers that carry an argument (10× latency in §1, CV² > 15 vs < 0.05
  around `eq:cv2`) are prose sentences with an inline `\provedby{}`. The
  other Lean `_example` theorems remain in Lean but are not cited.
- Established results are stated as `theorem`s with a citation; they are
  not proved. Our own results are `proposition`s. Both use the same plain
  amsthm format (no shading or boxes); only the name and the citation
  tell them apart.

## 3. Status of analytical results

All propositions and cited numbers compile in Lean with no `sorry` and
only standard axioms (`make lean` reports `OK: 38 theorems audited`).

| Result | Status | Notes |
|--------|--------|-------|
| `prop:pk`, `prop:cache` | proved | trivial parts dropped from the statements; M/M/1 unboundedness now lives in the `prop:routing` proof |
| `eq:cv2` numbers | proved | the core argument that variance comes from the miss penalty |
| option value (prose in §4.1) | proved | trivial math, so demoted from a proposition to a prose sentence; its value is in reading ThunderAgent A.2 correctly |
| `prop:evict` (i) | proved | refutes ThunderAgent App. F.3 |
| `prop:evict` (ii) 2-approx + tightness | proved | added in v0.2. v0.1 wrongly said the ratio is unbounded |
| `prop:evict` (iii) unbounded with resume probs | proved | |
| `prop:pd` | proved | capacity model only, no batching |
| `prop:routing`, `eq:lookahead`, `eq:append` | proved | the two rules are prose with inline proofs (trivial rearrangements) |

Candidate results, not yet in the paper. Each needs a Lean proof, or a
citation to an established theorem, before it becomes a proposition:
- **Density rule guarantee.** Greedy by `p_i c_i` plus the best single item
  is a 2-approximation for the probabilistic eviction problem. This is
  likely provable with the same LP argument as `prop:evict`(ii). Check
  the literature on min-knapsack first (Csirik et al. 1991).
- **Selective offloading threshold.** A closed-form keep/offload/recompute
  threshold in `(p_i, c_i, B_tier, ρ)` derived from Eq. (utility).
- **Closed-network throughput knee.** Asymptotic bounds
  `X(N) ≤ min(N/(D+Z), 1/D_max)` applied to ThunderAgent's concurrency
  sweep. Cite Lazowska et al.; the bound itself is standard. The simulator
  already checks it with ample KV
  (`closed_throughput_nondecreasing_fixed_demand`).
- **Heavy-traffic routing.** Load threshold at which affinity loses, as a
  function of `M`, `F`, `μ`. It currently exists only as an existence
  statement in `prop:routing`.

## 4. Validation plan: simulation first, then empirical

Validation runs in three phases. Each phase narrows what the next one
has to measure.

1. **Simulation (uncalibrated), done.** Check every proposition in its own
   model, then drop one assumption at a time and ask whether the decision
   survives. Synthetic workloads, fixed seeds. Reported in paper §6.9.
2. **Empirical (E1–E7), next.** Measure on the NPU testbed and on traces.
   The hypotheses and the quantities each experiment must record are
   those that phase 1 showed to decide the outcome.
3. **Calibrated simulation, after E1.** Plug the E1 fits into the
   simulator (M5 in `docs/simulation-design.md`) and score it with the
   analytical model against the testbed (E7).

Platform codes: T = NPU testbed, S = simulator (`libqueuingsim`,
`docs/simulation-design.md`), O = offline on traces.

### 4.1 Phase 1: simulation (uncalibrated)

Status: 22 of 22 checks pass (`make sim`; report via `make report`). What
each part established, and what it changes for phase 2:

| Question | Result under the synthetic model | Consequence for phase 2 |
|----------|----------------------------------|-------------------------|
| Do the closed forms hold in their own model? (M/M/1, `prop:pk`, `prop:cache`, `eq:cv2`, `prop:pd`, `prop:evict`(ii)) | yes, within CI or 2 % | the simulator is usable for the questions below |
| Does PK survive bursty arrivals? | no: it underestimates; Kingman's bound holds | E2 records interarrival CV² next to the PK ratio |
| Does throughput fall with N only through the hit rate? | yes: with finite KV it falls; with ample KV it follows `min(N/(D+Z),1/D)` | E3 records hit rate and resident KV per concurrency level |
| Is always-offload harmful? (option value, §4.1) | only with blocking fetches; with async fetches the tier queue acts as admission control and always-offload is best | E3 records whether the stack fetches synchronously; the policy ranking depends on it |
| Does the offline density advantage carry over? (`prop:evict`(iii)) | offline density ≫ SF when `p_i` vary; in the closed system the two are within seed noise, LRU is worse | E4 reports end-to-end TTFT and throughput next to cost/OPT, and measures the spread of `p_i` |
| Does the PD win condition pick the winner? (`prop:pd`(iii)) | 32/32 decisive grid cells agree | E5 tests the condition from measured parameters as planned |
| Does equal capacity mean equal latency? | no: PD latency is higher at the rate-matched split (pooling) | E5 reports latency as well as throughput |
| Does strict affinity fail at high load? (`prop:routing`) | yes once the hot replica saturates; lookahead with cheap migration stays flat | E6 measures migration cost, which sets the inversion load |

Phase 1 numbers are properties of the simulated model. They appear in the
paper only in §6.9, generated from the simulator, and never in a `\tbd`
cell.

### 4.2 Phase 2: empirical validation

Order matters: E1 gates everything, and E2 is the first result worth
reporting because it tests the paper's stance on variance (AGENTS.md
rule 5).

| ID | Question | Tests | Where | Needs (incl. from phase 1) | Status |
|----|----------|-------|-------|----------------------------|--------|
| E1 | Fit `S_prefill(L,K,B)`, `S_decode(B,KV)`, `T_transfer(bytes)` | calibration | T | profiling harness | not started |
| E2 | Is per-turn CV² dominated by the hit/miss mixture? Does `W_q` track `(1+CV²)/2`? | `prop:pk`, `eq:cv2` | T, S | E1, replayed traces, interarrival CV² | not started |
| E3 | Is selective offloading never below never-offload? When is always-offload below it? | option value (§4.1) | T, S | E1, tier bandwidth, fetch mode (sync/async) | not started |
| E4 | SF vs density `p_i c_i` vs exact optimum, offline and end-to-end; LRU vs hit-ratio vs utility | `prop:evict`, Thm. Dantzig | O, S | traces with resume events, spread of `p_i` | not started |
| E5 | Does the PD inequality predict the winner? What is the latency cost at equal capacity? | `prop:pd` | T | E1, measured `I, g_P, g_D` | not started |
| E6 | At what load does affinity lose? Does lookahead predict it? | `prop:routing`, `eq:lookahead`, `eq:append` | T, S | E1, migration cost | not started |
| E7 | Decision-faithfulness scorecard (Kendall τ, argmin agreement, MAPE) | whole model | T, S | E1 to E6, phase 3 | not started |

Details per experiment are in paper §6. The table layouts there are the
contract: fill `\tbd` cells with measured values only, and do not change
what a table measures without updating this file.

### 4.3 Phase 3: calibrated simulation

After E1: continuous batching, block-level KV, trace replay and the E1
service fits (milestone M5). Ladder step 5 then compares the calibrated
simulator with the testbed at the E7 held-out points. Its numbers may
fill the "Simulator" columns of `tab:scorecard`; they replace nothing in
§6.9, which stays the uncalibrated baseline.

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
E4 (end-to-end), E6 and E7. E1 and E5 are testbed-only; E4's cost/OPT
column is offline. Milestones M0 to M4 are built on synthetic workloads
(offline oracle, fair-share links and dynamic PD still open).
Uncalibrated numbers go in the paper only in §6.9, labelled as
simulation of the model. Any simulator number in §§6.1–6.8 or in
`tab:scorecard` needs the calibrated simulator (M5), which needs E1.

## 5. Claims we must not make (until data exists)

- That agentic workloads are "high variance" or "long-tailed" (AGENTS.md
  rule 5). Say that variance comes from the hit/miss mixture and that E2
  measures it.
- That PD does or does not help agentic serving in general. Say which
  regime of `prop:pd`(iii) applies.
- That shortest-first is a bad heuristic in practice. It is within 2× of
  optimal when resume behaviour is uniform. Whether it is bad depends on
  the spread of `p_i` (E4).
- Any number attributed to ThunderAgent, PPD or the vLLM blogs that was
  not read in the source. Mark bib entries `UNVERIFIED` otherwise.
- That a phase-1 simulation result holds for real systems or traces
  (AGENTS.md rule 7). In particular: that density and SF perform alike in
  practice, that async offloading is always best, or that the mechanism
  behind ThunderAgent's collapse is the one the simulator reproduces.
  Phase 1 shows these are possible under the model; phase 2 decides.

## 6. Bibliography status

Verified against the source on 2026-09-23: kleinrock1975, pollaczek1930,
khinchine1932, schrage1968, lazowska1984, carnes2008, csirik1991,
thunderagent (v3), ppd, vllm-agentx, mooncake-vllm.

`UNVERIFIED` (bibliographic details from memory, statement standard):
little1961, kingman1962, dantzig1957. Before submission, read the
primary source, check that the statement in the paper matches, and remove
the note.

## 7. Open questions

- Is the target venue ICML 2026 (theory with placeholders) or a systems
  venue after E1 to E7 exist? This affects how much of §6 stays in the
  paper.
- Which agentic trace can be used and released (internal Rebellions
  traces, or public ones)?
- Which serving stack runs on the testbed, and does it expose per-turn
  hit length and eviction events?
- Does that stack load offloaded KV synchronously (on the critical path of
  the batch) or asynchronously? Phase 1 shows the offloading ranking flips
  on this.
