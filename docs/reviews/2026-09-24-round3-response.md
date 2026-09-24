# Response to review round 3 (2026-09-24)

Paper v0.9 → v0.10. Item numbers refer to the round-4 action list in
`2026-09-24-round3.md`.

| # | Action | Done | Where |
|---|--------|------|-------|
| 1 | Rerun the forced-miss table with the cap the caption claims; add N̄′ and ρ′; print hi = ∞ as ρ′ ≥ 1; rewrite abstract, contribution 3, §4.2 and §6 from the table; delete the two speculative clauses | yes | `trace_price_row` now uses `TRACE_CAP_OPEN` (24), the open-pool configuration of `tab:sim-trace`; columns Λ, δ, N̄, N̄′, ρ, ρ′, L_P, ΔL_P, lo, hi, Fin., cap. Result with the cap: the open lower end overstates the rise 1–8× in every cell (macros `\simPriceOverMin/Max`); the cap N̄′ − L_P holds in every cell (`\simPriceCapHolds`). "Saturates gracefully" and "misses lengthen the sessions" removed |
| 2 | Cut to page 8 | yes | §4.2 re-centred on the replay (user request: the real data is the workload; the replica is what is simulated); in-model and synthetic beyond-model material summarised in one paragraph, Table 4 and Figure 1 moved to App. B; §3.2, §5, §6, §2.2, §2.3 cuts per the list. Limitations ends on p. 8; References start p. 9 |
| 3 | Prop. 2 wording | yes | part (iii) demoted to the prose sentence after the proposition with `closed_price_cap` ("raises … by at most N − L_P, whatever the work law"); "the wait W that enters the price"; usable-price sentence replaced by "raises L_P by at most min(hi, N − L_P) and the price a scheduler should use inside that range is open" (§6); mean value analysis cited (Lazowska et al. §6); "the think-time law enters only through Z"; App. A preamble says the recursion is taken as the model; new part (i) clause: Q_n nonincreasing in μZ (Lean `mvaQ_anti_c`), which defines the finite-source price of longer work |
| 4 | Residuals | yes | Prop. 3 proof (ΔD_i, "demand"); §3.3 w ∝ c²; §2.3 "rivals or exceeds"; split-table sentence (W_q, PK, TTFT within noise while N̄ doubles); abstract attributes the eviction-order finding to synthetic sessions and the price finding to the replay; footnote v0.10; Table 16 gap labels (thin-space replacement no longer hits the label); Table 4 caption continuation; Figure 1 annotations staggered; "bytes to free now" |
| 5 | Verify references | mostly | Crossref-verified with DOIs: naor1969, dantzig1957, little1961, kingman1962 (Biometrika 49(3/4):315–324), bcmp1975, mendelson1990; kelly1979 (Wiley 1979, 230 pp.) and kingman1993 (OUP, ISBN 9780198536932, Campbell = ch. 3) confirmed via Crossref records; infercept title/authors confirmed on arXiv 2402.01869 (venue not stated there; ICML 2024 kept, note retained). Remaining UNVERIFIED: three venue notes on arXiv papers and the InferCept policy description |
| 6 | Finite-source price column | yes (partial) | `analytic::finite_source_price` (MVA rise for longer mean work, N = N̄ rounded, Z = corpus mean think) as column "Fin." of `tab:sim-trace-price`; Lean `mvaQ_anti_c` gives its sign. Finding: it understates the observed rise 4–10× (exponential work ignores the CV² ≈ 40 of the appends), while the open bracket overstates 1–8×; the paper now says the real rise lies between the two and that a finite-source price with the work's second moment is the open problem. Algorithm 1 does not yet use W_N |
| 7 | Testbed | in progress | the user asked for a real replay on the RBLN stack (MiniMax M2.7 fp8, dp4ep, 4k blocks, subblock prefix cache, LMCache-RBLN); environment discovery running |
| 8 | Contribution 3 half-sentence; §3 order-of-u_i sentence | yes | contribution 3: "the priced order beats shortest-first only within seed noise"; §6: "it uses the order of u_i, so the level of Φ_i matters only against θ" |

Verdict trajectory: round 1 "not acceptable" → round 2 "major
revision" → round 3 "minor revision, border of major". The reviewer
recommends no fifth text-only round; the next gain is a measured row
(item 7), which is now being set up.
