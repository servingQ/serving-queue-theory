# Response to review round 1 (2026-09-24)

Paper v0.7 → v0.8. Item numbers refer to the prioritized action list in
`2026-09-24-round1.md`; M-numbers to its major issues.

| # | Action | Done | Where |
|---|--------|------|-------|
| 1 | Rewrite abstract and §1 to what the evidence shows; drop "no fixed rule ranks states correctly at every load" | yes | abstract, §1 contributions (one price for four decisions; congestion terms set scale; admission decides; thrashing attributed to Ao et al.) |
| 2 | Cut toward 8 pages: §4.2 compressed, simulation tables to App. B, §5 halved, §2 compressed | mostly | main text now ends on p. 9 (was 12.3); §4.3 keeps one overview table + one paragraph (user convention: E1–E6 stay in the paper); Tables ps/lps/evict/evict-dyn/inversion + two figures → App. B; TTFT table → App. C |
| 3 | Lean: Φ monotone in K; two-program order flips with load | yes | `missPrice_mono_context`, `prefillWork_miss_delta`, `price_order_flips_with_load` (MissPrice.lean); cited inline in §2.4 |
| 4 | Demote Props. 3, 4, 5(ii)-style facts and 6 to prose with citations; keep two propositions | yes (three kept) | §3.1: threshold rule, block prefix, guarded greedy as cited results (Dantzig; Csirik et al.; Carnes–Shmoys) with inline `\provedby`; §3.2: ρ* as `eq:rhostar` prose; `prop:price` = bracket only; kept `prop:price`, `prop:decode`, `prop:blind`; novelty sentence in §1 and §5 |
| 5 | Table 9: N and ρ columns, closed-system labelling, drop duplicate Λ rows, first-turn context and split rule | yes | `tab:sim-trace` regenerated: Pool / Regime (open Λ or closed N) / Hit / Mix / CV² / ρ / W_q / PK / TTFT; finite pools run once; §4.2 text states the split rule, median first prompt of split continuations (`\wkFirstCtxSplit`k) vs new sessions, share of split sessions |
| 6 | Finite-source price (M/M/1//N) as a proposition | **not done** | stated as the open theoretical question in §4.2 and §6; `prop:price` framed as the stationary marginal price and an upper bound for small populations; forced-miss observation `trace_replay_miss_price` quantifies looseness (ΔL_P is 1/7–1/4 of the bracket's lower end at δ ≤ 3 %) |
| 7 | §2.3: replace toy example by the trace decomposition table; hypothesis in terms of λE[S²]/(2(1−ρ)) | yes | `tab:cv2` (generated `tab-weka-cv2.tex`); toy 50 ms / 5 s numbers removed (Lean `_example` theorems kept, uncited); E2 metric "PK wait" |
| 8 | Estimate p_i and τ_i by turn index and preceding gap from the corpus | yes | `scripts/trace_stats_weka.py` → `tab-weka-resume.tex` (App. C `tab:resume`), macros `\wkPmin…\wkTauMax`; §3.1 reports p ∈ [0.85, 0.99], τ ∈ [4, 65] s and draws the honest conclusion (τ, not p, separates programs in these traces) |
| 9 | §4.2 trace paragraph: remove "at a hit rate near one … presumably the queue" | yes | rewritten per M8: never-evicting counterfactual stated as such; TTFT R² as a prediction of the all-hit regime that E2 tests |
| 10 | Inversion sweep: finer grid, link utilisation; oracle labels | yes | rates in steps of 0.05; `RoutingReport::link_utilization`, column ρ_L; at B = 125k the inversion comes with ρ_0 = 1.00 and ρ_L = 0.97, so the "link saturates" sentence is now supported by the table; Priced rules labelled oracle in the evict-dyn caption |
| 11 | Definitional mismatches (M4) | yes | L_P = number in the prefill stage (queue + server); TTFT = W_q + S in Table 1; byte-second threshold proved (`threshold_rule_optimal_byte_seconds`) and cited; stability condition ρ_D < sup φ in `prop:decode`; (ii) reworded as added demand; units κ / β / ω; per-event use of Φ stated as an approximation |
| 12 | Verify UNVERIFIED bib entries | **not done** | added `dewan1990` (UNVERIFIED); verification of mendelson1990, infercept, bcmp1975, kelly1979, kingman1962, li2025continuum needs the sources |

Other changes prompted by the review: Table 5 caption explains the SF
ratio in the arbitrary-w row (M7d); Fig. 3 caption says log scale;
`q_i` → `p_i` in captions; "Fixed rules as special cases" paragraph
folded into one sentence (M10); Kingman kept in §6 only; ThunderAgent
A.2 reading kept to one clause.

Disagreements / deferred:
- §4.3 (E1–E6) stays in the main text by the user's standing convention
  (one overview table, short hypotheses, no `\tbd` cells now); for
  submission it moves to the appendix in one cut.
- The finite-source price (item 6) is the next theoretical task; the
  M/M/1//N closed form is tractable in Lean, the M/G/1//N case is not.

Harness comparison added to the workload evidence (research/trace-analysis.md):
append CV² Claude Code production 32, Claude Code SWE-bench Pro 6.8,
terminus-2 2.3, mini-swe-agent 1.9; reuse 97–99 % for all.
