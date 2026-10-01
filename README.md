# serving-queue-theory

Decision-faithful queueing models for agentic LLM serving — a draft paper
whose analytical propositions are **machine-checked in Lean 4 / Mathlib** and
whose paper ↔ proof correspondence is enforced by CI.

```
paper/   ICML-2026-format LaTeX draft (main.tex, refs.bib, icml2026.sty); proofs in Appendix A
lean/    Lean 4 project `ServingQueueTheory` (Mathlib v4.34.0); requires serQ's Lean package `Serq`
validation/  Python validation and report generation; serQ runs every simulation
scripts/ CI checks (see below)
```

## Propositions (all proved, no `sorry`, standard axioms only)

| # | Proposition | Lean module | Key theorems |
|---|-------------|-------------|--------------|
| 1 | M/M/1 latency blow-up: `W = 1/(μ−λ)` strictly increasing and unbounded on `[0, μ)` | `MM1` | `mm1Wait_strictMono`, `mm1Wait_unbounded` |
| 2 | Pollaczek–Khinchine: `E[S²] = Var + mean²`; equal-mean/higher-variance workload waits longer (`3.43×` example) | `PollaczekKhinchine` | `secondMoment_eq_variance_add_sq`, `pkWait_lt_of_variance_lt` |
| 3 | KV reuse lowers `E[S]`, `ρ`, and PK delay monotonically in hit rate (`ρ: 0.9 → 0.252`) | `CacheReuse` | `pkWait_mixture_antitone` |
| 4 | Option value: enabling offloading never hurts an optimal controller; *always* offloading can | `OptionValue` | `optimal_cost_antitone_in_actions`, `always_offload_can_be_worse` |
| 5 | PD disaggregation (capacity only): `min(N_P/s_P, N_D/s_D) ≤ N/(s_P+s_D)`, equality at rate matching; exact 4-bottleneck win condition; both regimes realisable | `PDDisaggregation` | `pd_le_agg`, `pd_beats_agg_iff`, `pd_wins_example`, `pd_loses_example` |
| 5b | Decode sojourn at equal throughput (PD follow-up, issue #28): scaling arrival rate and PS capacity together keeps the occupancy law and divides the sojourn; with `f ∈ (0, 1]` the decode share of a colocated engine, a dedicated decode engine `(λ/f, φ)` has the colocated engine's `(λ, fφ)` occupancy and `f` times its sojourn; a smaller share of the capacity at the same demand leaves more turns in the batch | `DecodeScaling` | `psMeanNumber_scale`, `dedicated_sojourn`, `psMeanNumber_anti_share`, `request_weighted_tpot_not_from_means` |
| 6 | Shortest-context-first eviction is **not** optimal (`{4,5,6}, ΔC=6`: 41 vs 36); breaks further with resume probabilities | `Eviction` | `shortestFirst_optimality_claim_false` |
| 7 | Program-aware routing: myopic vs lookahead disagreement condition; affinity is never unconditionally optimal; PPD append-prefill rule | `Routing` | `lookahead_prefers_iff`, `affinity_not_always_optimal`, `append_prefill_rule` |

## Branch policy

The repository is public (organization `servingQ`, since 2026-10-02); no
server-side branch protection is configured. Enable the local guard once per
clone:

```bash
git config core.hooksPath .githooks   # pre-push: fast-forward only + make check
```

## Working with coding agents

`AGENTS.md` is the single instruction file for every agent (`CLAUDE.md` is a
symlink to it, so Codex and Claude Code read the same text). `research/add-proposition.md` is the step-by-step workflow for a new
result. `make check` is the one command every agent runs before reporting.

## Local build

```bash
make setup   # one-time: elan + rustup + tectonic + uv + Mathlib cache
make check   # lean + refs + paper + unified lectures + sim + lecture checks
make site    # the public page with the PDFs, into site/ (see "What CD publishes")
```

Or by hand:

```bash
# Lean (installs nothing globally; elan puts toolchains under ~/.elan)
curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain none
cd lean && lake exe cache get && cd ..
scripts/check_lean.sh          # build + sorry check + axiom audit

# Paper and lecture notes (tectonic downloads TeX packages on demand)
cd paper && tectonic -X compile main.tex
cd lectures/queueing-serving && tectonic -X compile notes.tex

# Paper ↔ Lean consistency
scripts/check_lean_refs.sh
```

## What CI verifies (`.github/workflows/ci.yml`)

1. **lean** — `lake build`; fails on any `declaration uses 'sorry'` or literal
   `sorry`; runs `lean/scripts/AxiomAudit.lean` (`#print axioms` on every
   paper-facing theorem) and fails if anything other than `propext`,
   `Classical.choice`, `Quot.sound` appears; then every `\leanref{Name}` in
   `paper/main.tex` names an existing Lean declaration (here or in serQ's
   package), and every referenced theorem is in the axiom audit.
2. **paper** — the ICML PDF compiles; uploaded as an artifact.
3. **sim** — `scripts/check_sim.sh`: every Lean theorem cited by a simulation
   check exists; `ruff format --check`, `ruff check`, `pytest`, and the
   validation report, which runs every named check;
   the validation report (`validation/validation-report.md`) is uploaded
   and posted to the job summary. See `validation/README.md`. This job
   builds the pinned serQ release and pyserq (cached by the pin) and regenerates the report
   by simulation (about 5 minutes),
   so it runs only when a path it reads changed (`validation/`,
   `programs/`, `paper/sim/`, `lean/`, its scripts, the workflow); a manual
   `workflow_dispatch` runs it regardless.

CI does **not** check that a Lean statement faithfully formalises the informal
proposition. That step is a human review; statements are kept deliberately
close to the prose to make it tractable.

## Unified lecture course

[Queueing Theory for LLM Serving](lectures/queueing-serving/notes.tex) combines
the former primer and PD course. Chapters 1–4 develop the shared foundations;
chapters 5–6 apply them to colocated and disaggregated serving. Executable
examples use **serQ v0.1.4 (IR v12)**, using the repository’s existing release pin.

```bash
make lectures         # compile the unified notes
make lecture-results  # fetch/build serQ v0.1.4 and check the course's results
```

The [verification record](research/lecture-integration.md) explains the changed
PD decode result and how to reproduce the old/new comparison.

## What CD publishes (`.github/workflows/publish.yml`)

The paper and the unified lecture notes are compiled from their sources and
served from the **public** page <https://servingq.github.io/serving-queue-theory/>,
built with mkdocs from `docs/` (`mkdocs.yml`). Anyone can read the page and
download the PDFs, and search engines index them; the repository is public
too, so treat everything in it as published.

Every push to `main` that touches `paper/`, `lectures/`, `docs/` or
`mkdocs.yml` (and `workflow_dispatch`) runs:

1. **pdfs**: tectonic compiles `paper/main.tex` and every
   `lectures/*/notes.tex`; the PDFs are uploaded as the workflow artifacts
   `paper-pdf` and `lecture-notes` (kept 90 days).
2. **site**: the PDFs land in `docs/pdf/` (gitignored) and
   `mkdocs build --strict` builds the page, which links them relatively, so
   a missing PDF fails the build; the site is uploaded as the artifact `site`.
3. **deploy**: on `main` only, `actions/deploy-pages` publishes the site.

A pull request touching the same paths runs steps 1 and 2 and stops, so a
reviewer downloads the artifacts from the run. No PDF is committed:
`paper/main.pdf`, `lectures/*/notes.pdf` and `docs/pdf/` are gitignored
(the figures under `paper/sim/` and `paper/exp/` are generated data the
paper `\input`s, and stay tracked). Locally, `make site` builds the same
page into `site/`. To unpublish:
`gh api -X DELETE repos/servingQ/serving-queue-theory/pages` (caches and search
results keep what they have for a while).

The internal working notes live in `research/` (plan, testbed, the serQ pin,
design notes, review rounds) and are not part of the site.

## Status / TODO

- [x] Bibliography verified against primary sources (ThunderAgent
      arXiv:2602.13692 v3 incl. Lemma 4.1 / Def. 4.1 / App. F.3 / A.2 / A.4 /
      Fig. 7; PPD arXiv:2603.13358; vLLM AgentX and Mooncake posts).
- [ ] Empirical programme (§6 of the paper): service-time profiling on the NPU
      rack, PD win-condition measurement, eviction gap on replayed traces.
- [ ] Extend Lean development: general covering-knapsack formulation of
      eviction; SRPT / class-separation result; closed-network think-time model.
