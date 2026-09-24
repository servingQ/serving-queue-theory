# Response to review round 2 (2026-09-24)

Paper v0.8 → v0.9. Item numbers refer to the round-3 action list in
`2026-09-24-round2.md`.

| # | Action | Done | Where |
|---|--------|------|-------|
| 1 | Forced-miss replay table generated, `\input` in App. B; §4.2, abstract and contribution 3 rewritten from it, no hand-typed ratios | yes | `paper/sim/tab-trace-price.tex` (+ `data/trace-price.csv`), macros `\simPriceSmallRatioMin/Max` (0.15–0.75 at δ ≤ 3 %), `\simPriceLargeRatioMin/Max` (1.2–3.4 at δ = 10 %), `\simPriceLiveMin/Max`; abstract: "overstates the cost of a few misses several-fold and understates that of many" |
| 2 | `\input{sim/tab-finite}` in App. B, cited in §2.2 and Limitations | yes | macros `\simFiniteRatioMax/Min`, `\simFiniteNMin/Max`, `\simFiniteRho` |
| 3 | Finite-source proposition (M/M/1//N via MVA) | **yes** | `prop:finite` in §2.4 with App. A proof; Lean `FiniteSource.lean`: `mvaQ_mono`, `mvaQ_le_card`, `mvaQ_gt_sub` → `finite_source_rho_lt_one`, `finite_source_wait_le_open` (reduces to Q_{n−1} ≤ Q_n exactly as the review said), `closed_price_cap`, `finite_source_two_sessions_example` (4.5×). Statement follows the review's wording; the M/G/1//N case is stated as a conjecture that the replay supports for a few misses and refutes for many |
| 4 | §4.3 + Table 6 to an appendix; cuts | partly | now App. D `app:design`; main text still ends on p. 9 (Related Work starts p. 9): the new proposition and its prose cost ~0.4 page; further cuts deferred to round 4 |
| 5 | §2.3 range statement; caption "All hit"; "linear cost model" in abstract | yes | macros `\wkMixLinMin/Max` (47–58), `\wkMixAttMin/Max` (23–35), `\wkAppendShareMin` (42); caption says K_c = ∞ is the linear model |
| 6 | Citations | partly | mendelson1990 now cited for M/M/1 priority pricing only; the size-squared term attributed to the PK second moment, not to a paper; dewan1990 removed; "approximable within a constant factor"; guess-and-greedy to Csirik et al. alone. dantzig1957 / standard references still UNVERIFIED (need the sources) |
| 7 | Algorithm 1 step 3 vs byte-second theorem; Prop. 2 proof; w ∝ c²; "at equal append" + cost model | yes | §3.1 states the byte target as a heuristic mapping of the byte-second rule that the simulation tests; App. A decode proof: (iii) removed, added demand A = Σ q_i ΔD_i; `prop:blind`(ii) w_i ∝ c_i²; §2.4 two-facts paragraph says "at equal append" and "under the cost model of the replay" |
| 8 | Split-rule sensitivity; N̄ and X in the replay table; inversion rows "≤ 0.20" | yes | `tab-trace-split.tex` (10 vs 30 min: open-pool row within seed noise), `weka-sessions-1800.csv` bundled; `tab-trace` has N̄ and X columns; inversion rows at the lowest swept rate print "≤ 0.20" |
| 9 | Reorder contribution 2; Prop. 3(i) with the τ finding; abstract "decides throughput" | yes | contribution 2 leads with the shared price and the head-of-line term; abstract and contribution 3 say "decides the regime / whether the replica thrashes" |
| 10 | Testbed time | no | none available |

Minor issues addressed: §1 quotes the corpus medians (58 turns, 207k) via
macros; "as ThunderAgent's Lemma 4.1 also assumes"; "square of the miss
less the square of the hit"; flip example cited at "rank can change";
"does not depend on p_i"; "in the simulated configurations"; Campbell
sentence gives the SWE-bench Pro values (0.98×, 0.23); think time quoted
as median 3.8 s / p90 88 s; "of follow-up turns" in the replay text;
Table 4 caption points to the 9000 instances of Table 9; Table 11
caption cross-references Figure 1 by number; finite-source falsifier in
Limitations. Not yet: Figure 1 annotation overlap; byte-second(s)
wording sweep; Table 14 caption note on τ as an estimate of the
remaining suspension (added in this round? no: pending).

Simulator: 36 checks pass (`finite_source_wait_below_open` added).
