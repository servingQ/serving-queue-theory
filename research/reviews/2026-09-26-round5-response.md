# Response to review round 5 (2026-09-26)

Paper v0.13 → v0.14. Item numbers refer to the major issues and the
round-6 action list in `2026-09-26-round5.md`. Items 1–6 were done from
the data on disk; item 7(a), the second seed, was run on the testbed the
same night (`data/exp/e2b/s25_base_s1`, `s25_m10_s1`).

| # | Issue | Done | Where |
|---|-------|------|-------|
| 1 | Bracket counted forced misses only | yes | `analyze_price.py` classifies every follow-up of both arms (forced / unforced miss / partial / hit) and prices the forced misses plus the unforced ones net of the baseline's; Table 20 has an "unforced" column (baseline → forced arm). At 2.5 s the bracket becomes [1.80, 2.27] and contains the observed 2.05; at 3.5 s nothing changes ([0.74, 0.83] ∋ 0.75). Abstract, contribution 3 and §4.3 say "inside the bracket at both loads"; research plan and testbed.md no longer attribute the overshoot to the prefill-time inflation |
| 2 | Per-rank spread hidden | yes | Table 20 lists the four ranks and the sum per spacing and seed; §4.3 states the per-rank range of ΔL_P / lo (`\eTwobSpreadLo/Hi`, 0.86–1.22); the abstract states the bracket, not two ratios |
| 3 | Strongest findings missing | yes | §4.3: the head-of-line term is 55–64 % of the price (`\eTwobHolShareLo/Hi`, Table 20 column HOL), the queue's part of the rise is 1.4–2.9× the added service (`\eTwobQueueOverService*`), 49–58 % of the rise is borne by turns that did not miss (`\eTwobBystander*`, column byst.), the finite-source wait is 0.7–1.8× the server's queueing time per rank (`\eTwobFinOverWq*`) while its price understates the rise 1.9–2.5×; contribution 3 carries the first two |
| 4 | One wait denominator | yes | Table 19 prints the server's queueing time, its prefill time and the remainder of TTFT (client and frontend); §4.3 gives PK against both: 1.3–1.6× the engine's queueing time and 0.5–0.7× the residual TTFT − S (`\eTwobPkOverWobs*`, `\eTwobFront*`, `\eTwobPfOverEs*`) |
| 5 | 1.5 s arm attributed to the pool alone | yes | §4.3: "saturates the replica by two routes", the batch cap of eight in 25 % of samples (`\eTwobSatCapShare`, from `cap_share` in `metrics_summary`), ITL 1.6 s (`\eTwobSatItl`), 25 % of follow-ups miss after the 30 s gap; Table 19 has a "cap" column (0 % in the light arms) |
| 6 | Derived trace under-described; caption wrong | yes | Table 19 caption: nine copies of the 37 sessions, 2k first prompt, appends × 0.44 (mean ≈ 940), contexts 2k–9k at the median and up to 27k, outputs ≤ 4, think times capped at 30 s, per-session nonce, the sub-block hit rule; a "sessions" column (333 / 222) from params.json; §4.3 says "a trace derived from the same sessions" |
| 7 | E2 residuals | yes | "8 to 38 times" as macros (`\eTwoWqOverPk*`, `\eTwoWqOverFin*`); Table 18 caption explains finite > PK at the loose caps (ρ_N 0.90 / 0.75 against 0.38); Table 18 and §4.3 print three classes (hit / partial / miss), so the miss TTFT is 117–279 s and the ratio 46–107× (abstract updated) |
| consistency | W_q two definitions | yes | Table 1: W_q = W_q^P + W_q^M; §2.2 names W_q^M; Prop. 1 uses W = E[W_q^P]; §4.3 E2 names the block wait W_q^M |
| consistency | "at the same utilisation" | yes | contribution 1 and the remark after Prop. 2 |
| consistency | transient caveat | yes | "§4.2 and §4.3 test the stationary form" |
| consistency | abstract length | yes | 146 words |
| consistency | M / μ / n / p leftovers | yes | move cost is R_j (eq. 8 in R), "service rate μ for whole turns", proof of Prop. 3 in m and j, Table 3 prints h = 0.8, Algorithm 1 steps 3–4 "blocks of the programs with u_i ≤ θ" |
| consistency | φ "calibrated" | yes | "to be calibrated (E1, Appendix E)" |
| minor | Figure 1(d) ticks, Table 19 N̄ per rank, footnote E2b, §6 clause, unused macros | yes | ticks at 0.2/0.4/0.6; N̄ per rank; "E1, E2 and E2b are reported"; §6 names the derived trace, four ranks and two seeds as replicates; the E2b generator was rewritten and the E2 generator pruned (macros in use only, plus the Sat* set for the 1.5 s sentence) |
| minor | Figure 1(e) ratio axis, cap column, page 16–17 blanks | not | round 6 (page budget; the E2b tables are `table*`s and fill page 17) |
| 7(a) | second seed at 2.5 s | run | `s25_base_s1`, `s25_m10_s1` (nonces and the forced-turn draw re-drawn with seed 1); rows in Tables 19–20 once analysed (see research plan §0) |

Not done: 7(b) a 5 % forced share and 7(c) the real gaps (no 30 s cap);
both are one replay each and are the first entries of "next steps" in
`research/research-plan.md`.

Verdict trajectory: round 4 "major, for the right reason" → round 5
"minor revision": the requested experiment was run and reproduced from
the raw data; the accounting (every miss the change caused), the
per-rank spread and the three findings the data supports are now in
the paper.
