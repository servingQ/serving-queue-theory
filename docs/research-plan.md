# Research plan

Working reference for humans and coding agents. It records what the paper
claims, what is proved, what is pending, and in which order the empirical
work should happen. Update it when the status of a result or experiment
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

## 2. Paper structure (v0.2)

| § | Content | Our results | Cited theorems |
|---|---------|-------------|----------------|
| 2 | Model: service centre, KV mixture, closed network, control problem | none | Little, PK, Kingman bound, interactive response-time law |
| 3 | Congestion and the hit/miss mixture | `prop:mm1`, `prop:pk`, `prop:cache`, `eq:cv2` (prose numbers) | SRPT (prose) |
| 4.1 | Offloading (+ ThunderAgent App. A.2/A.4) | `prop:option` | none |
| 4.2 | Eviction (+ ThunderAgent Def. 4.1, App. F.3, G.3) | `prop:evict` (not optimal; 2-approx, tight; unbounded with resume probs) | Dantzig LP greedy |
| 5 | PD disaggregation (+ ThunderAgent Fig. 7) | `prop:pd` | none |
| 6 | Program-aware routing (+ PPD) | `prop:routing`, `prop:append` | none |
| 7 | Experiments E1 to E7, placeholder tables (`\tbd`) | none | none |
| App. A | Human-readable proofs | | |

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
| `prop:mm1`, `prop:pk`, `prop:cache` | proved | textbook; kept because `prop:routing`(ii) uses unboundedness |
| `eq:cv2` numbers | proved | the core argument that variance comes from the miss penalty |
| `prop:option` | proved | trivial math; its value is in reading ThunderAgent A.2 correctly |
| `prop:evict` (i) | proved | refutes ThunderAgent App. F.3 |
| `prop:evict` (ii) 2-approx + tightness | proved | added in v0.2. v0.1 wrongly said the ratio is unbounded |
| `prop:evict` (iii) unbounded with resume probs | proved | |
| `prop:pd` | proved | capacity model only, no batching |
| `prop:routing`, `prop:append` | proved | |

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
  sweep. Cite Lazowska et al.; the bound itself is standard.
- **Heavy-traffic routing.** Load threshold at which affinity loses, as a
  function of `M`, `F`, `μ`. It currently exists only as an existence
  statement in `prop:routing`(ii).

## 4. Empirical plan

Order matters: E1 gates everything, and E2 is the first result worth
reporting because it tests the paper's stance on variance (AGENTS.md
rule 5). Platform codes: T = NPU testbed, S = simulator
(`docs/simulation-design.md`), O = offline on traces.

| ID | Question | Tests | Where | Needs | Status |
|----|----------|-------|-------|-------|--------|
| E1 | Fit `S_prefill(L,K,B)`, `S_decode(B,KV)`, `T_transfer(bytes)` | calibration | T | profiling harness | not started |
| E2 | Is per-turn CV² dominated by the hit/miss mixture? Does `W_q` track `(1+CV²)/2`? | `prop:pk`, `eq:cv2` | T, S | E1, replayed traces | not started |
| E3 | Is selective offloading never below never-offload? | `prop:option` | T, S | E1, tier bandwidth | not started |
| E4 | SF vs density `p_i c_i` vs exact optimum; LRU vs hit-ratio vs utility | `prop:evict`, Thm. Dantzig | O, S | traces with resume events | not started |
| E5 | Does the PD inequality predict the winner? | `prop:pd` | T | E1, measured `I, g_P, g_D` | not started |
| E6 | At what load does affinity lose? Does lookahead predict it? | `prop:routing`, `prop:append` | T, S | E1 | not started |
| E7 | Decision-faithfulness scorecard (Kendall τ, argmin agreement, MAPE) | whole model | T, S | E1 to E6 | not started |

Details per experiment are in paper §7. The table layouts there are the
contract: fill `\tbd` cells, do not change what a table measures without
updating this file.

### Data needed from traces
- Per turn: arrival time, new tokens, cached tokens (hit length), output
  tokens, service time split into prefill and decode, tool time after
  the turn.
- Per program: turn count, whether it resumed after each suspension. This
  gives empirical `p_i` for E4.
- Eviction events: which programs were resident, their `c_i`, and the
  memory target. This gives E4 instances.

### Decisions about the simulator
A simulator is needed, but only for E2 (hit-rate sweeps), E3, E4
(end-to-end), E6 and E7. E1 and E5 are testbed-only; E4's cost/OPT
column is offline. See `docs/simulation-design.md` for scope and the
validation ladder. Milestones M0 to M4 can be built on synthetic
workloads now. Calibrated runs (M5) and every simulator number in the
paper need E1, because the service curves come from E1.

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
  venue after E1 to E7 exist? This affects how much of §7 stays in the
  paper.
- Which agentic trace can be used and released (internal Rebellions
  traces, or public ones)?
- Which serving stack runs on the testbed, and does it expose per-turn
  hit length and eviction events?
