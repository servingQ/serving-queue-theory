# Response to the miss-feedback review, round 2 (2026-09-27)

Verdict received: accept (as a docs-level analysis) after R1–R6.

| # | Item | Done | Where |
|---|------|------|-------|
| R1 | Bistability is about two equilibria, not attraction | yes | `unit_feedback_bistable` docstring and result 3 reworded; new `pkFeedback_absorbing` (an overloaded hit rate reaches 0 in one step and stays) |
| R2 | "closed ⇒ H(0) > 0" wrong | yes | result 3: a bounded wait removes only the overload route; with the pool channel or a step-shaped G, H(0) = 0 remains possible |
| R3 | k band; threshold test; research-plan wording | yes | `analyze_feedback.py`: 95 % bands with both arms' variance ([0.12, 0.23], [0.13, 0.24]; 3.5 s: 0 induced, k ≤ 0.024); in-sample check (6/29, 9/29 above C); the 2.5 s threshold at 3.5 s (12 absences above C, 0 missed); note and research plan: wait channel excluded, pool channel inferred by elimination and association, block-level free-queue reasons |
| R4 | hi_forced | yes | `analyze_price.py` now reports `hi_forced`; with forced misses alone the bracket is [1.56, 1.88] and [1.71, 2.13] at 2.5 s, below the observed 2.05 and 2.15; with induced misses [1.80, 2.27], [1.89, 2.44]. The note says so (the round-1 claim is withdrawn). `make exp` regenerated; no paper number changed |
| R5 | Test redesign | yes | "Next" item 1: r·T > C, arms (a) block-matched insertion with registered TTFT side effect, (b′) stretched gaps 30 → 42 s, (b) as a paired control; numeric decision rules against the noise floor; proxy validation or KV events first |
| R6 | Paper §3.3 wording; Lean docstrings | yes | §3.3 now: "the two feed each other: a miss stays longer and re-inserts its context … The loop amplifies misses at moderate load (§4.3) and thrashes the replica at high load (§4.2), as Ao et al. find without reuse." Main text still ends on page 8; `make check` passes. Module header and `feedback_comparative_statics` docstring updated |
