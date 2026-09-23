# Adding a proposition (Lean + paper + CI)

Use this checklist for every new analytical result. It is the same for
Claude Code and Codex.

## 1. Decide what is actually provable
Write the informal statement first. Ask: is this a theorem about the
*model* (provable) or a claim about *workloads* (empirical)? Only the
former becomes a `proposition`; the latter goes to §6 (empirical plan) or
is hedged in prose.

## 2. Lean
- Pick the module (`lean/ServingQueueTheory/*.lean`) or create one and
  import it from `lean/ServingQueueTheory.lean`.
- Define the objects with `def`/`noncomputable def` mirroring the paper's
  symbols (e.g. `pdCapacity NP ND sP sD`).
- State the theorem so it reads like the paper sentence. Split (i)/(ii)/(iii)
  into separate theorems named `<topic>_<claim>`.
- Numeric instances: separate theorems ending in `_example`, proved by
  `norm_num` or `decide`.
- Build: `cd lean && lake build`. Fix until clean. Never use `sorry`.
- Add `#print axioms <name>` for each new theorem to
  `lean/scripts/AxiomAudit.lean`.

## 3. Paper
```latex
\begin{proposition}[Short name]\label{prop:key}
Formal statement, items with \begin{enumerate}[nosep,leftmargin=1.6em,label=(\roman*)].
\begin{leanrefs}\leanref{thm\_one}, \leanref{thm\_two}\end{leanrefs}
\end{proposition}

\begin{example}\label{ex:key}
Concrete numbers. \exlean{\leanref{thm\_example}}
\end{example}
```
- Escape underscores in `\leanref{}` as `\_`.
- Add a `\begin{proof}[Proof of Proposition~\ref{prop:key}]` to Appendix A,
  transcribing the Lean proof and naming each theorem.
- If the result bears on a published claim, discuss it in §4 with the
  exact section/figure of the source.

## 4. Verify
```bash
make check
```
Expected tail: `OK: N theorems audited; only standard axioms used.`,
`checked M \leanref citations`, and a tectonic run with no `error`.
Optionally `make preview` and look at the rendered pages.

## 5. Report
State what was proved, what was merely conjectured, and paste the `OK:`
and `checked` lines. Do not commit unless asked.
