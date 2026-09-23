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
