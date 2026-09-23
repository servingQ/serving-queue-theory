# serving-queue-theory

Decision-faithful queueing models for agentic LLM serving — a draft paper
whose analytical propositions are **machine-checked in Lean 4 / Mathlib** and
whose paper ↔ proof correspondence is enforced by CI.

```
paper/   ICML-2026-format LaTeX draft (main.tex, refs.bib, icml2026.sty); proofs in Appendix A
lean/    Lean 4 project `ServingQueueTheory` (Mathlib v4.34.0)
scripts/ CI checks (see below)
```

## Propositions (all proved, no `sorry`, standard axioms only)

| # | Proposition | Lean module | Key theorems |
|---|-------------|-------------|--------------|
| 1 | M/M/1 latency blow-up: `W = 1/(μ−λ)` strictly increasing and unbounded on `[0, μ)` | `MM1` | `mm1Wait_strictMono`, `mm1Wait_unbounded` |
| 2 | Pollaczek–Khinchine: `E[S²] = Var + mean²`; equal-mean/higher-variance workload waits longer (`3.43×` example) | `PollaczekKhinchine` | `secondMoment_eq_variance_add_sq`, `pkWait_lt_of_variance_lt` |
| 3 | KV reuse lowers `E[S]`, `ρ`, and PK delay monotonically in hit rate (`ρ: 0.9 → 0.252`) | `CacheReuse` | `pkWait_mixture_antitone` |
| 4 | Option value: enabling offloading never hurts an optimal controller; *always* offloading can | `OptionValue` | `optimal_cost_antitone_in_actions`, `always_offload_can_be_worse` |
| 5 | PD disaggregation: `min(N_P/s_P, N_D/s_D) ≤ N/(s_P+s_D)`, equality at rate matching; exact 4-bottleneck win condition; both regimes realisable | `PDDisaggregation` | `pd_le_agg`, `pd_beats_agg_iff`, `pd_wins_example`, `pd_loses_example` |
| 6 | Shortest-context-first eviction is **not** optimal (`{4,5,6}, ΔC=6`: 41 vs 36); breaks further with resume probabilities | `Eviction` | `shortestFirst_optimality_claim_false` |
| 7 | Program-aware routing: myopic vs lookahead disagreement condition; affinity is never unconditionally optimal; PPD append-prefill rule | `Routing` | `lookahead_prefers_iff`, `affinity_not_always_optimal`, `append_prefill_rule` |

## Working with coding agents

`AGENTS.md` is the shared instruction file (Codex reads it directly, `CLAUDE.md`
imports it). `docs/add-proposition.md` is the step-by-step workflow for a new
result. `make check` is the one command every agent runs before reporting.

## Local build

```bash
make setup   # one-time: elan + tectonic + uv + Mathlib cache
make check   # lean + refs + paper
```

Or by hand:

```bash
# Lean (installs nothing globally; elan puts toolchains under ~/.elan)
curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain none
cd lean && lake exe cache get && cd ..
scripts/check_lean.sh          # build + sorry check + axiom audit

# Paper (tectonic downloads TeX packages on demand)
cd paper && tectonic -X compile main.tex

# Paper ↔ Lean consistency
scripts/check_lean_refs.sh
```

## What CI verifies (`.github/workflows/ci.yml`)

1. **lean** — `lake build`; fails on any `declaration uses 'sorry'` or literal
   `sorry`; runs `lean/scripts/AxiomAudit.lean` (`#print axioms` on every
   paper-facing theorem) and fails if anything other than `propext`,
   `Classical.choice`, `Quot.sound` appears.
2. **refs** — every `\leanref{Name}` in `paper/main.tex` names an existing
   Lean declaration, and every referenced theorem is in the axiom audit.
3. **paper** — the ICML PDF compiles; uploaded as an artifact.

CI does **not** check that a Lean statement faithfully formalises the informal
proposition. That step is a human review; statements are kept deliberately
close to the prose to make it tractable.

## Status / TODO

- [x] Bibliography verified against primary sources (ThunderAgent
      arXiv:2602.13692 v3 incl. Lemma 4.1 / Def. 4.1 / App. F.3 / A.2 / A.4 /
      Fig. 7; PPD arXiv:2603.13358; vLLM AgentX and Mooncake posts).
- [ ] Empirical programme (§6 of the paper): service-time profiling on the NPU
      rack, PD win-condition measurement, eviction gap on replayed traces.
- [ ] Extend Lean development: general covering-knapsack formulation of
      eviction; SRPT / class-separation result; closed-network think-time model.
