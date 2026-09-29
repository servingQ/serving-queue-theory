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
| `lectures/{queueing-primer,queueing-pd}/notes.tex` | two lecture-note courses on the paper's theory (tectonic); the PDFs are built by CD, never committed |
| `docs/`, `mkdocs.yml`, `.github/workflows/publish.yml` | the **public** page https://vrvrv.github.io/serving-queue-theory/ with the paper and lecture-note PDFs (README, "What CD publishes") |
| `research/` | internal working notes: plan, testbed, seQ pin, design notes, review rounds; not published |
| `lean/ServingQueueTheory/` | Lean 4 + Mathlib proofs of every proposition in the paper |
| `validation/` | Python validation and report package; seeded checks of each proposition, every simulated system a seQ program run by the pinned seQ CLI |
| seQ (separate repo, pinned release) | the language in which a serving deployment is a program: interpreter and CLI `seq-lang`, example programs, the vLLM oracle and its A100 test vectors; https://github.com/vrvrv/seQ, used here as a Cargo git dependency and a checkout in `.seq/` (`research/seq.md`). Its Lean model is here: `lean/ServingQueueTheory/Seq{,Exec,Oracle,Serve}.lean` (syntax and pool semantics, executable semantics, the vLLM scenarios as theorems generated from seQ's vectors, serving order) and `Deployments.lean` (the paper's replicas as seQ programs) |
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
   the literature are stated in prose with a citation and no Lean proof;
   they are not our claims and need no `\provedby`. Anything else you cannot prove is a conjecture or an
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
   fact; the paper's stance is that prefill-work variance has two sources,
   the append (tool output, compaction; not the scheduler's) and the
   hit/miss mixture (the KV policy's lever), and that the split must be
   measured (§2.3, Eq. `eq:cv2`; trace baseline in §4.2 and
   `research/trace-analysis.md`); it is a property of prefill work and touches
   TTFT (the FIFO prefill queue, `prop:pk`), not the decode stage (PS,
   insensitive, `prop:decode`). Do not write "if every turn hit the work
   would be nearly deterministic": production traces give the append
   CV² ≈ 32.
   Do not describe whole-turn service times as differing by orders of
   magnitude between hit and miss; decode dominates a hit turn. Likewise do not claim that KV
   footprint variance helps or hurts batch size in general (the §2.2
   memory-pool paragraph shows both signs; `footprint_variance_*` in Lean).
6. **Keep statements close to the prose.** Lean statements should be
   readable next to the paper proposition so a human can check the
   correspondence, which CI cannot.
7. **Simulator results are not measurements.** The `validation` package's output
   comes from synthetic workloads or from replayed traces on a simulated
   replica (since 2026-09-25 the replay's cost model is calibrated on the
   testbed, E1/E2, `research/testbed.md`; the synthetic checks are not). Do
   not put it in §4.2 `\tbd{}` cells or state it as a property of real
   systems. It goes in the paper only via
   `paper/simulation.tex`, whose numbers are generated into `paper/sim/`
   by `make tables` (`validation/src/validation/paper_tables.py`); never type them by hand.
   Testbed measurements (`paper/exp/`, generated by `make exp` from
   `data/exp/`, see `research/testbed.md`) are the only measured numbers;
   they enter the paper only as macros, tables and figures from that
   directory.
   Trace statistics (`paper/traces/`, generated by
   `scripts/trace_stats_*.py`, see `research/trace-analysis.md`) are workload
   measurements, not serving measurements: they may describe the
   workload (§2, §4.2 "What the traces say") but never fill an E1–E6
   `\tbd{}` cell, and the proxy TTFT in them is observational.
8. **Do not commit or push unless asked.** Never commit `lean/.lake/`,
   `*.log`, or `paper/main.pdf` (all gitignored). Server-side branch
   protection is unavailable on this private Free-plan repo; the
   `.githooks/pre-push` hook (enable with `git config core.hooksPath
   .githooks`) refuses non-fast-forward pushes to `main` and runs
   `make check` first. Do not bypass it with `--no-verify`.

## Environment and commands

Toolchain is user-local (no sudo): `~/.elan` (Lean), `~/.local/bin/tectonic`
(LaTeX), `~/.local/bin/uv` (Python tooling; the validation package's
environment is `validation/uv.lock`), `~/.cargo` (Rust, only to build the
seQ CLI with seQ's own pinned toolchain). `scripts/setup.sh` installs all of
it idempotently.

```bash
make setup     # install/refresh toolchain + Mathlib cache (first run ~2 min)
make lean      # lake build + sorry check + axiom audit   (scripts/check_lean.sh)
make refs      # paper \leanref{} ↔ Lean consistency       (scripts/check_lean_refs.sh)
make paper     # compile paper/main.pdf with tectonic
make seq       # the seQ release pinned in validation/pyproject.toml: .seq/src + CLI .seq/bin/seq-lang (scripts/fetch_seq.sh)
make sim       # simulator: Lean-name check, ruff, pytest (incl. the seQ cross-checks), report (scripts/check_sim.sh)
make report    # print the simulator validation report
make tables    # regenerate paper/sim/ (tables, macros, figure data; ~7 min)
make check     # seq + the four checks; run before saying "done"
make preview   # render PDF pages to PNG in /tmp for visual inspection
```

`lake build` after a small edit takes 2–5 s (Mathlib oleans are cached).
A first `lake build` without the cache would take hours — always run
`lake exe cache get` (done by `make setup`).

## Repository layout

```
paper/main.tex          paper; propositions are ours; cited results appear in prose
paper/refs.bib          bibliography (verified 2026-09-23; see notes in entries)
paper/icml2026.sty      ICML style; [preprint] option in use
lean/lakefile.toml      Mathlib pinned to v4.34.0 (lean-toolchain matches)
lean/ServingQueueTheory/{MM1,PollaczekKhinchine,CacheReuse,OptionValue,
                         PDDisaggregation,Eviction,Routing}.lean
lean/scripts/AxiomAudit.lean   `#print axioms` for every paper-facing theorem
scripts/check_lean.sh          build + sorry + axiom audit
scripts/check_lean_refs.sh     \leanref ↔ Lean name check
scripts/check_sim.sh           simulator: cited Lean names exist + ruff + pytest + report
scripts/fetch_seq.sh           the pinned seQ release into .seq/ (research/seq.md: pin, upgrading, CI access)
programs/{price,open,replay}_vllm.seq  where a miss is paid (Poisson turns), the eviction/admission experiment (two-class open sessions) and §4.2's replica (the WEKA sessions) on vLLM v1's engine rules and the testbed's cost model (run by validation/src/validation/seq_{replay,open}.py for paper/sim/; replay ablations by scripts/exp/seq_replay42.py, research/seq-replay42*.md)
validation/src/validation/checks.py  one named check per proposition (tests + report)
validation/src/validation/seq_{price,open,replay}.py  where a miss is paid, the eviction/admission experiment and §4.2's replay on vLLM's rules (programs/*_vllm.seq via seQ); validation no longer simulates the §2.2 replica itself (`TwoStage` removed 2026-09-27)
scripts/hooks/post-edit.sh     Claude Code hook: rebuild after edits
research/add-proposition.md        step-by-step workflow for a new result
research/research-plan.md          status of every result and experiment; read before paper work
research/simulation-design.md      the validation package: design, validation-ladder status, roadmap to the calibrated simulator
lean/ServingQueueTheory/Seq{,Exec,Oracle,Serve}.lean   seQ formally: syntax `Route Env V` of the route block + pool invariant; executable semantics (ℕ, step clock); SeqOracle.lean is GENERATED by scripts/gen_seq_oracle.py from seQ's IR files tools/oracle/*.ir.json; serving order
lean/ServingQueueTheory/Deployments.lean   the paper's replicas as seQ programs
scripts/exp/diff_seq_vllm.sh, first_divergence.sh   seQ (.seq/bin/seq-lang) vs the real vLLM scheduler, request by request / first differing step
paper/simulation.tex           §4.1 uncalibrated simulation; numbers \input from paper/sim/ (generated)
paper/traces/                  trace statistics \input by the paper (generated by scripts/trace_stats_{weka,harbor}.py; `make traces`)
research/trace-analysis.md         what the real agent traces say; caveats; what went into the paper
```

## How to add or change a result

Follow `research/add-proposition.md`. Short version:

1. Write the theorem in the right Lean module (or a new one imported from
   `lean/ServingQueueTheory.lean`). Build it.
2. Add `#print axioms <name>` to `lean/scripts/AxiomAudit.lean`.
3. In the paper, state the proposition in a `proposition` box, end it with
   `\provedby{\leanref{name}, ...}` (underscores escaped as `\_`), and add
   a human-readable proof to Appendix A.
4. If the result can be simulated, add a check to
   `validation/src/validation/checks.py` (see `validation/README.md`).
5. `make check`.

## Paper conventions

- ICML two-column; do not change fonts, margins, or the `.sty`.
- Structure (v0.8, after the 2026-09-24 professor review): §1 intro
  states the thesis (the price of a miss) and three contributions; §2
  problem formulation, 2.5 pages incl. Table 1 "the model at a glance"
  (§2.1 sessions: Poisson session arrivals, closed turn/tool loop, BCMP
  in one sentence; §2.2 the replica as two resources plus a memory pool:
  prefill = FIFO queue served from the budget the decode batch leaves,
  decode = bandwidth PS, footprint examples as prose, units κ bytes/token
  for memory and β, ω seconds for decode; §2.3 prefill work under KV
  reuse with the trace-derived variance split `tab:cv2` (append vs
  hit/miss mixture); §2.4 = `sec:price`: the decision problem and
  `prop:price` (bracket only; term ratios, divergence, monotonicity in K
  and the load-flip example are prose with inline `\provedby`),
  `prop:finite` (M/M/1//N via mean value analysis: Q_n monotone in n and
  antitone in μZ, open wait ≥ finite-source wait; the cap ΔL_P ≤ N − L_P is
  a prose sentence with `closed_price_cap`; added rounds 3–4),
  `prop:decode`); §3 congestion-priced scheduling: Algorithm 1 up front
  (step 7 = admission cap from the resident-KV estimate), §3.1 eviction
  (threshold rule, block prefix, byte-second variant and guarded greedy
  as *cited known results* with inline `\provedby`; `prop:blind` is the
  one proposition; trace evidence on p_i, τ_i spread), §3.2 placement
  (`eq:rhostar` inversion load as prose), §3.3 admission and offloading
  (Campbell estimate lives here); §4 Results (renamed from "Evidence"
  2026-09-26 at the user's request; opens with a one-sentence map from
  the least to the most controlled source): §4.1 "Real-World Traces: the
  Workload", §4.2 "Simulation: Replayed Production Sessions"
  (`paper/simulation.tex`: the real sessions are the workload, the
  replica is simulated with the vLLM v1 engine's rules (the seQ program
  `programs/replay_vllm.seq`, run by `validation.seq_replay` inside
  `validation.paper_tables`; decided 2026-09-27, `research/seq-replay42.md`), the
  cost model is calibrated on the testbed;
  synthetic in-model/beyond-model checks are one summary paragraph, their
  tables and figures in App. B `simulation-appendix.tex`), §4.3 "Testbed
  Measurements" (cost fit; long-context replay as three short paragraphs
  with italic leads; short-context replay and the price test, `paper/exp/tab-e2b*.tex` in App. D,
  `macros-e2b.tex`, panels (d) and (e) of Figure 1 `fig-e2.pdf`, all
  generated by `make exp` from `data/exp/e2b/`); the
  real-system experimental design (six named experiments, one overview
  table, no `\tbd` cells) is App. E `app:design` since round 2 (page budget); §2 opens
  with a "Background" paragraph (prefill, decode, KV cache, prefix
  hit/miss, chunked prefill; added 2026-09-26 for readers outside serving
  systems); §5 related work (one page, with the novelty sentence); §6
  limitations incl. "what would falsify"; App. A proofs (price, decode,
  blind, finite), App. B simulation tables, App. C trace tables, App. D
  testbed tables (`app:exp`, E1/E2), App. E
  experimental design. Four propositions total; do not re-promote the demoted knapsack facts or the
  inversion load to propositions (review M3). Prefill/decode (PD)
  disaggregation is out of this paper (follow-up); its text is in
  paper/pd-followup.tex, not \input. Do not reintroduce it into the main
  text or an appendix. Do not reintroduce a "layered" framing, a section
  that collects all propositions, a separate section for other papers'
  claims, or a "special cases" section, and no "The claim" / "Reading
  the claim" paragraphs (removed 2026-09-23): §3 proposes our scheduler,
  and a published rule appears only as the special case of a step, in
  the sentence where the formulation meets it.
- Standard results from the literature are stated in prose with a
  citation, keeping their assumptions in a clause. Display a formula
  only when a proposition or proof refers to it (e.g. `eq:pk`); do not
  put textbook results in `theorem` boxes.
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
- Other papers' rules are mentioned where they bear on a result, in one
  or two sentences as the special case of a step of the scheduler, with a
  citation naming the section/figure. Paraphrase exactly what they say
  and do not imply we re-ran their experiments (the intro states once
  that we did not). No dedicated claim paragraphs.
- §4.2 (real-system evaluation) uses `\tbd` placeholders. Fill cells only
  with measured values; keep `research/research-plan.md` in sync with what
  each table measures. §4.1 (`sec:sim`, `paper/simulation.tex`) reports
  uncalibrated simulation and is the only main-text place simulator
  numbers appear.
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

## Experiment names (user request, 2026-09-26)

The paper and the docs name experiments, never number them. Map from the
old codes (still used in file names, macros and older review files):
cost fit (E1, `data/exp/e1`, `\eOne*`), long-context replay (E2,
`data/exp/e2`, `\eTwo*`), short-context replay and price test (E2b,
`data/exp/e2b`, `\eTwob*`), offloading test (E3), eviction replay (E4),
placement test (E5), faithfulness scoring (E6). Do not write "E1"…"E6"
in the paper.

## Research context worth knowing

- The paper's thesis is the price of a miss (`prop:price`, §2.5): the
  total TTFT one KV miss adds at the prefill queue, with a head-of-line
  term (∝ miss²) that chunked prefill does not remove because prefills
  are served in order. The decode stage (`prop:decode`) prices only work
  and is insensitive to the miss. The scheduler compares the price per
  byte-second `u_i = p_i Φ_i /(c_i τ_i)` with one memory shadow price θ
  (`prop:memory`) for eviction, offloading and admission. Do not write
  that chunking makes the eviction key load-independent (a v0.5 claim,
  withdrawn). §3 builds the
  scheduler on it; do not re-centre the paper on critiques of other work.
- Claims re-examined in §3 come from ThunderAgent (arXiv:2602.13692 v3):
  Lemma 4.1 / Def. 4.1 / App. F.3 (shortest-first eviction theorem,
  contradicted in one sentence after `prop:blind`), App. A.2 + Fig. 7 (offloading and PD numbers),
  App. A.4 (v3 only: offloading is "orthogonal"). PPD is arXiv:2603.13358
  (ICML 2026). Agentic trace statistics are from the vLLM AgentX (2026-09-08)
  and vLLM×Mooncake (2026-05-06) blog posts.
- The research plan, result status and experiment order are in
  `research/research-plan.md`. Validation runs in three phases: uncalibrated
  simulation (done, paper §4.1; thrashing dominates, admission matters), empirical E1–E6 (paper §4.2; E1
  calibration gates everything, E2 per-turn CV² is the first result to
  report), then the calibrated simulator scored in E6. Result-table layouts live in research/research-plan.md §4.2a, not in the paper; PD material is in paper/pd-followup.tex (not \input).
