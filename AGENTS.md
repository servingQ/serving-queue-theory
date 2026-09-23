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
| `libqueuingsim/` | Rust discrete-event simulator; seeded checks of each proposition in and beyond its model |
| `scripts/` | CI checks that bind the two together |
| `.github/workflows/ci.yml` | Runs the checks on push/PR |

The organising principle is **decision faithfulness**: the model must rank
policies (routing, eviction, PD split) the way the real system does; exact
latency reproduction is secondary.

## Non-negotiable rules

1. **No unproved claims in the paper.** Every `\begin{proposition}` (and
   any `\begin{example}`, though we avoid them) ends with
   `\provedby{\leanref{...}}`; a derived number stated in prose carries an
   inline `\provedby{}` too,
   and every name must be a theorem that compiles. Established results from
   the literature may be stated as a `\begin{theorem}` with a
   citation and no Lean proof; they are not our claims and need no
   `\provedby`. Anything else you cannot prove is a conjecture or an
   empirical question, never a proposition.
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
   mixture and must be measured (see §3, Eq. `eq:cv2`).
6. **Keep statements close to the prose.** Lean statements should be
   readable next to the paper proposition so a human can check the
   correspondence, which CI cannot.
7. **Simulator results are not measurements.** `libqueuingsim` output
   comes from synthetic workloads. Do not put it in §6 `\tbd{}` cells or
   state it as a property of real systems. It goes in the paper only via
   `paper/simulation.tex`, whose numbers are generated into `paper/sim/`
   by `libqueuingsim/examples/paper_tables.rs`; never type them by hand.
8. **Do not commit or push unless asked.** Never commit `lean/.lake/`,
   `*.log`, or `paper/main.pdf` (all gitignored). Server-side branch
   protection is unavailable on this private Free-plan repo; the
   `.githooks/pre-push` hook (enable with `git config core.hooksPath
   .githooks`) refuses non-fast-forward pushes to `main` and runs
   `make check` first. Do not bypass it with `--no-verify`.

## Environment and commands

Toolchain is user-local (no sudo): `~/.elan` (Lean), `~/.local/bin/tectonic`
(LaTeX), `~/.local/bin/uv` (Python tooling), `~/.cargo` (Rust, pinned by
`libqueuingsim/rust-toolchain.toml`). `scripts/setup.sh` installs all of it
idempotently.

```bash
make setup     # install/refresh toolchain + Mathlib cache (first run ~2 min)
make lean      # lake build + sorry check + axiom audit   (scripts/check_lean.sh)
make refs      # paper \leanref{} ↔ Lean consistency       (scripts/check_lean_refs.sh)
make paper     # compile paper/main.pdf with tectonic
make sim       # simulator: Lean-name check, fmt, clippy, tests, report (scripts/check_sim.sh)
make report    # print the simulator validation report
make check     # all four; run before saying "done"
make preview   # render PDF pages to PNG in /tmp for visual inspection
```

`lake build` after a small edit takes 2–5 s (Mathlib oleans are cached).
A first `lake build` without the cache would take hours — always run
`lake exe cache get` (done by `make setup`).

## Repository layout

```
paper/main.tex          paper; propositions (ours) and theorems (cited) share the plain amsthm style
paper/refs.bib          bibliography (verified 2026-09-23; see notes in entries)
paper/icml2026.sty      ICML style; [preprint] option in use
lean/lakefile.toml      Mathlib pinned to v4.34.0 (lean-toolchain matches)
lean/ServingQueueTheory/{MM1,PollaczekKhinchine,CacheReuse,OptionValue,
                         PDDisaggregation,Eviction,Routing}.lean
lean/scripts/AxiomAudit.lean   `#print axioms` for every paper-facing theorem
scripts/check_lean.sh          build + sorry + axiom audit
scripts/check_lean_refs.sh     \leanref ↔ Lean name check
scripts/check_sim.sh           simulator: cited Lean names exist + cargo fmt/clippy/test
libqueuingsim/src/validation.rs  one named check per proposition (tests + report)
scripts/hooks/post-edit.sh     Claude Code hook: rebuild after edits
docs/add-proposition.md        step-by-step workflow for a new result
docs/research-plan.md          status of every result and experiment; read before paper work
docs/simulation-design.md      libqueuingsim: design, validation-ladder status, roadmap to the calibrated simulator
paper/simulation.tex           §6.9 uncalibrated simulation; numbers \input from paper/sim/ (generated)
```

## How to add or change a result

Follow `docs/add-proposition.md`. Short version:

1. Write the theorem in the right Lean module (or a new one imported from
   `lean/ServingQueueTheory.lean`). Build it.
2. Add `#print axioms <name>` to `lean/scripts/AxiomAudit.lean`.
3. In the paper, state the proposition in a `proposition` box, end it with
   `\provedby{\leanref{name}, ...}` (underscores escaped as `\_`), and add
   a human-readable proof to Appendix A.
4. If the result can be simulated, add a check to
   `libqueuingsim/src/validation.rs` (see `libqueuingsim/README.md`).
5. `make check`.

## Paper conventions

- ICML two-column; do not change fonts, margins, or the `.sty`.
- Structure: §2 model (with cited standard theorems), §§3–5 one section
  per decision (congestion, KV state, routing), §6 experiments, App. A
  proofs, App. B prefill/decode (PD) disaggregation. PD results are
  deferred to a follow-up paper: keep them, their E5 plan and their
  simulation paragraphs in App. B, not in the main text. Do not reintroduce a "layered" framing, a section that collects
  all propositions, or a separate section for other papers' claims.
- Propositions sit in the section whose decision they inform. Formal
  statement only, enumerated with `(\roman*)`. Do not interleave
  `example` blocks; if a concrete number carries the argument, state it
  in one prose sentence with an inline `\provedby{}` (the Lean `_example`
  theorem stays).
- **Lean stays out of the rendered paper.** `\provedby{}` typesets nothing.
  The only mention of Lean is one sentence at the start of Appendix A. Do
  not name Lean theorems, tactics or CI in the prose.
- Appendix A proofs are ordinary mathematical proofs written for a human
  reader, not transcripts of the Lean proofs.
- Other papers' claims are discussed where they bear on a result, in "The
  claim" / "Reading the claim" paragraphs. Quote or paraphrase exactly what
  they say, cite the section/figure, and do not imply we re-ran their
  experiments (the intro states once that we did not).
- §6 Experiments uses `\tbd` placeholders. Fill cells only with measured
  values; keep `docs/research-plan.md` in sync with what each table
  measures. The last subsection of §6 (`sec:sim`, `paper/simulation.tex`)
  reports uncalibrated simulation and is the only main-text place
  simulator numbers appear (App. B.4 holds the PD ones, also generated).
- Prose style: short sentences, no em-dashes, numbers in tables or examples
  rather than running text where possible.

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

- Claims re-examined in §§4–5 come from ThunderAgent (arXiv:2602.13692 v3):
  Lemma 4.1 / Def. 4.1 / App. F.3 (shortest-first eviction theorem, refuted
  by our Prop. on eviction), App. A.2 + Fig. 7 (offloading and PD numbers),
  App. A.4 (v3 only: offloading is "orthogonal"). PPD is arXiv:2603.13358
  (ICML 2026). Agentic trace statistics are from the vLLM AgentX (2026-09-08)
  and vLLM×Mooncake (2026-05-06) blog posts.
- The research plan, result status and experiment order are in
  `docs/research-plan.md`. Validation runs in three phases: uncalibrated
  simulation (done, paper §6.9), empirical E1–E7 (paper §6; E1
  calibration gates everything, E2 per-turn CV² is the first result to
  report), then the calibrated simulator scored in E7.
