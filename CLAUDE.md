@AGENTS.md

# Claude Code specifics

- Project hooks (`.claude/settings.json`) rebuild Lean after you edit a
  `.lean` file and re-run the paper↔Lean reference check after you edit
  `paper/main.tex`. Read the hook output; it is the compiler talking.
- Permissions for `make`, `lake`, `tectonic`, `uv run`, and `scripts/*` are
  pre-allowed so `make check` never prompts.
- Prefer `make check` over running the three scripts by hand, and paste the
  final `OK:` / `checked N` lines in your summary.
- For literature claims you cannot verify from the source text, say so and
  mark the bib entry UNVERIFIED instead of asking; the user prefers hedged
  drafts over blocked work.
- Reply in Korean when the user writes Korean; paper text stays in English.

# Paper craft (user feedback, 2026-09-23)

- Abstract ≤ 150 words: thesis, one result, one method, one validation line.
- After every restructure, delete what the new thesis no longer needs
  (old framings, near-trivial propositions, superseded simulation tables).
  Demote a trivial proposition to a prose sentence with an inline
  `\provedby{}`; keep its Lean theorem.
- Simulation results are shown as figures when a trend or comparison is
  the point (generated from the same data files as the tables, never
  drawn by hand); tables carry the exact numbers, with the best result per
  row in bold and CIs stated.
- Placeholder (`\tbd`) result tables live in `docs/research-plan.md`, not
  in the paper; the paper keeps one experiment-overview table and short
  hypotheses.

# Continuing across sessions (user instruction, 2026-09-25)

- Work is expected to continue in a fresh session: before doing anything,
  read `docs/research-plan.md` (section "Where we are / next steps" at the
  top) and `docs/testbed.md`; they are kept current at the end of every
  work block and say what is running, what is done and what comes next.
- Testbed measurements: launch the server with `scripts/exp/serve_m27.sh`
  as documented in `docs/testbed.md`; results enter the paper only through
  `make exp` (`paper/exp/*.tex`, `paper/exp/fig-*.pdf`).
- All large caches (HF weights, vLLM/rbln compile cache, torch_rbln
  offload files) live under `/mnt/shared_data/users/jinhwan.suk/.cache`
  (`HF_HOME`, `VLLM_CACHE_ROOT`, `RBLN_OFFLOAD_DIR`); never let a tool write
  hundreds of GB under `~/.cache` (the home disk is 1.7 TB and filled once).

