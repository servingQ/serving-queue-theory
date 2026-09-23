# AGENTS.md — shared instructions for coding agents (Claude Code, Codex, …)

This file is the single source of truth for how agents work in this repo.
`CLAUDE.md` imports it; Codex reads it directly. Keep agent-specific
details in the agent's own file, not here.

## What this project is

A research project on **queueing-theoretic models for agentic LLM serving**
(rack-scale NPU deployments: prefill/decode disaggregation, KV-cache reuse
and eviction, program-aware routing). The deliverables are:

| Path | Deliverable |
|------|-------------|
| `paper/main.tex` | ICML-2026-format paper draft (tectonic, two-column) |
| `lean/ServingQueueTheory/` | Lean 4 + Mathlib proofs of every proposition in the paper |
| `scripts/` | CI checks that bind the two together |
| `.github/workflows/ci.yml` | Runs the checks on push/PR |

The organising principle is **decision faithfulness**: the model must rank
policies (routing, eviction, PD split) the way the real system does; exact
latency reproduction is secondary.

## Non-negotiable rules

1. **No unproved claims in the paper.** Every `\begin{proposition}` carries
   `\leanref{...}` names, and every name must be a theorem that compiles.
   If you cannot prove something, state it as a conjecture or an empirical
   question, never as a proposition.
2. **No `sorry`, no new axioms.** `scripts/check_lean.sh` fails on either.
   Do not add `axiom` declarations or `set_option` escapes to silence errors.
3. **Do not claim a proof compiles unless you ran `lake build`.** Report
   compiler output verbatim if it fails.
4. **Cite primary sources.** A number or claim attributed to a paper or blog
   must have been read in that source. If it was not, mark the bib entry
   `note = {UNVERIFIED: ...}` and hedge the prose. Never invent arXiv IDs,
   authors, or figure numbers.
5. **Do not assert workload properties without data.** In particular, do not
   write that agentic workloads are "high variance" or "long-tailed" as a
   fact; the paper's stance is that variance comes from the hit/miss
   mixture and must be measured (see §2.1 and Example ex:cv2).
6. **Keep statements close to the prose.** Lean statements should be
   readable next to the paper proposition so a human can check the
   correspondence, which CI cannot.
7. **Do not commit or push unless asked.** Never commit `lean/.lake/`,
   `*.log`, or `paper/main.pdf` (all gitignored). Server-side branch
   protection is unavailable on this private Free-plan repo; the
   `.githooks/pre-push` hook (enable with `git config core.hooksPath
   .githooks`) refuses non-fast-forward pushes to `main` and runs
   `make check` first. Do not bypass it with `--no-verify`.

## Environment and commands

Toolchain is user-local (no sudo): `~/.elan` (Lean), `~/.local/bin/tectonic`
(LaTeX), `~/.local/bin/uv` (Python tooling). `scripts/setup.sh` installs
all of it idempotently.

```bash
make setup     # install/refresh toolchain + Mathlib cache (first run ~2 min)
make lean      # lake build + sorry check + axiom audit   (scripts/check_lean.sh)
make refs      # paper \leanref{} ↔ Lean consistency       (scripts/check_lean_refs.sh)
make paper     # compile paper/main.pdf with tectonic
make check     # all three — run before saying "done"
make preview   # render PDF pages to PNG in /tmp for visual inspection
```

`lake build` after a small edit takes 2–5 s (Mathlib oleans are cached).
A first `lake build` without the cache would take hours — always run
`lake exe cache get` (done by `make setup`).

## Repository layout

```
paper/main.tex          paper; propositions are tcolorbox-shaded amsthm envs
paper/refs.bib          bibliography (verified 2026-09-23; see notes in entries)
paper/icml2026.sty      ICML style; [preprint] option in use
lean/lakefile.toml      Mathlib pinned to v4.34.0 (lean-toolchain matches)
lean/ServingQueueTheory/{MM1,PollaczekKhinchine,CacheReuse,OptionValue,
                         PDDisaggregation,Eviction,Routing}.lean
lean/scripts/AxiomAudit.lean   `#print axioms` for every paper-facing theorem
scripts/check_lean.sh          build + sorry + axiom audit
scripts/check_lean_refs.sh     \leanref ↔ Lean name check
scripts/hooks/post-edit.sh     Claude Code hook: rebuild after edits
docs/add-proposition.md        step-by-step workflow for a new result
```

## How to add or change a result

Follow `docs/add-proposition.md`. Short version:

1. Write the theorem in the right Lean module (or a new one imported from
   `lean/ServingQueueTheory.lean`). Build it.
2. Add `#print axioms <name>` to `lean/scripts/AxiomAudit.lean`.
3. In the paper, state the proposition in a `proposition` box, put numeric
   instances in an `example`, end the box with
   `\begin{leanrefs}\leanref{name}, ...\end{leanrefs}`
   (underscores escaped as `\_`), and add a proof to Appendix A.
4. `make check`.

## Paper conventions

- ICML two-column; do not change fonts, margins, or the `.sty`.
- Propositions: formal statement only, enumerated with `(\roman*)`.
  Numeric instances go in `\begin{example}` with an `\exlean{...}` footer.
- Prose style: short sentences, no em-dashes, numbers in tables or examples
  rather than running text where possible.
- Section 4 discusses other papers' claims. Quote or paraphrase exactly what
  they say and cite the section/figure; say explicitly that we did not
  re-run their experiments.

## Lean conventions

- `autoImplicit = false`; name theorems `snake_case`, defs `camelCase`.
- Prefer `norm_num`, `decide`, `linarith`, `nlinarith`, `field_simp`,
  `positivity` over long term proofs. Real-number statements over `ℝ`;
  combinatorial counterexamples over `ℕ`/`ℚ` with `decide`.
- Each module starts with a doc comment mapping it to the paper
  proposition and listing its key theorems.
- If Mathlib lemma names are uncertain, grep `lean/.lake/packages/mathlib`
  rather than guessing.

## Research context worth knowing

- Claims re-examined in §4 come from ThunderAgent (arXiv:2602.13692 v3):
  Lemma 4.1 / Def. 4.1 / App. F.3 (shortest-first eviction theorem, refuted
  by our Prop. on eviction), App. A.2 + Fig. 7 (offloading and PD numbers),
  App. A.4 (v3 only: offloading is "orthogonal"). PPD is arXiv:2603.13358
  (ICML 2026). Agentic trace statistics are from the vLLM AgentX (2026-09-08)
  and vLLM×Mooncake (2026-05-06) blog posts.
- Next empirical steps are listed in paper §6; the first is measuring
  per-turn service-time CV² on replayed traces.
