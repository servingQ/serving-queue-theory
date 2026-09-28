# Response to review round 4 (2026-09-26)

Paper v0.11 → v0.12. Item numbers refer to the major issues and the
round-5 action list in `2026-09-26-round4.md`. Everything below was done
from the data on disk; no server time was used.

| # | Issue | Done | Where |
|---|-------|------|-------|
| 1 | Hit classification was `cached > 0` | yes | `analyze_e2.py`: a follow-up hit is a cached length ≥ 90 % of the previous prompt plus completion. Full-hit rates 46/59/83/84 %, hit TTFT 2.0–2.6 s at every cap, miss 51–263 s, ratio 20–101×. Abstract, contribution 3, §4.3 rewritten; mixture-share macros regenerated (58–81 %) |
| 2 | Finite-source Z omitted decode | yes | Z = time from a turn's first token to the session's next arrival (decode + think), per rank; finite-source wait 0.5–14.5 s, now below the observation in every row and stated as such ("both compute-only predictions sit one to two orders below the observation, because neither prices memory") |
| 3 | "Wait is for KV space" asserted | yes | From `metrics.jsonl`: running never exceeds 4 per rank (batch cap never binds), pool = 52 blocks × 4096, a 50k miss needs 13 blocks, pooled occupancy in the samples with a request waiting 78–80 %, server prefill time 1.07–1.10 × E[S] of the cost model. All in §4.3 as macros |
| 4 | Door wait hidden | yes | `door`, `sojourn`, `λ` columns in `tab:e2` and in the prose: door wait up to 772 s at cap 8; sojourn incl. door 2583 → 1344 s; throughput 0.070 → 0.092 turns/s; "the cap moves the wait rather than removing it" |
| 5 | ω = 0.125 s is the loaded ITL | yes | `CAL_DECODE_STEP = 0.057` (cap-8 ITL); the range 0.057–0.122 s is a macro (`\eTwoItlLo/Hi`); §4.2 says so; tables regenerated (`make sim` OK) |
| 6 | TTFT ratio called "the price of a miss" | yes | abstract: "waits X to Y times longer for its first token ... almost all for KV blocks"; contribution 3 and §6: "the price Φ_i itself is not yet measured, only the wait a miss incurs" |
| 7 | Stale K_c after recalibration | yes | §2.4 refers to the synthetic cost model (App. B, K_c = 50k); the replay caption prints K_c from the calibrated constants (≈30k) |
| 8 | Fourth-reviewer attacks | partly | think-time cap and the CRC imbalance are stated in §4.3/§6 (single stack and workload, single seeds); trace provenance: "a coding-agent trace" (not "production") in §4.3 and the abstract; host-tensor mode and sub-block rounding are in `research/testbed.md`, not the paper (page budget) |
| minor | Table 18 caption, resume-table `\\,s`, legends, appendix naming | yes | caption rewritten by the generator; `trace_stats_weka.py` label fixed and traces regenerated; E2 figure legends placed in free space; AGENTS.md: App. D testbed tables, App. E design |
| minor | Figure 4 annotations, App. B overfull, empty pages 16–17, unused macros, Table 11 ρ'=0.83 next to "ρ' ≥ 1" | not yet | round 5 |

Not done (needs testbed time): action item 7, the short-context run
(≤ 12k tokens, cap 32, real gaps, ρ ≈ 0.5–0.7, optional 5 % forced
misses) that would reach the PK regime and measure Φ_i. It is the first
entry of "next steps" in `research/research-plan.md`.

Verdict trajectory: round 3 "minor, border of major" → round 4 "major,
for the right reason" (analysis errors in the new section). Items 1–7
are addressed in v0.12; the reviewer expected "minor revision" after
items 1–5.
