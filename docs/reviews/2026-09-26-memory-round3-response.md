# Response to the memory-model review, round 3 (2026-09-26)

Verdict received: accept, as a model of the replica conditional on the
measured decode durations.

| # | Item | Done | Where |
|---|------|------|-------|
| R3-1 | One definition of "arrived to a queue" | yes | model and observed both count "another request of the rank waiting" (`queue_at_send = len(queue) > 0`); model 70–99 % of misses, 0 % of hits against observed 92–100 % and 2–4 % |
| R3-2 | nocross over-read | yes | memory-model.md says it does not isolate the cross-rank share (0.033 s per token: 48 → 69 s); the paper sentence now states the facts side by side (decodes slower than idle; lockstep; some rank prefills 31–67 % of the time) without the causal "because" |
| R3-3 | Misquotes, docstring | yes | hit offset −0.9 to +0.7 s (model − observed); observed/model order everywhere; light-arm offset 0.08–0.13 s; docstring describes the copy semantics, prompt-only reuse, preemption upper bound and the decode variants |
| R3-4 | Real overtakes in s15 | noted | memory-model.md statement 1: some s15 inversions are real overtakes, mechanism not found |
| R3-5 | Note on the paper; abstract claim | yes | the abstract and introduction now say only what the measurements show ("the turns that miss are those that queued"); §4.3 "possibly its own" instead of "often"; the note lists the paper edits |
| R3-6 | Preemptions | yes | stated as an upper bound |
| R3-7 | Prefill stretch range | yes | 1.07–1.10× (long) and 1.09–1.29× (short) from `pf_over_es` in both docs; the 1.15 scaling recorded as an in-sample observation, not adopted |
| R3-8 | docs/testbed.md on s15 | yes | "49 % followed a gap of 29 s or more and 91 % arrived to a queue", from memory_model.py (new "≥29s" statistic) |
| provenance | 335/681; 67/58/31/31 % | yes | the gap share is printed by memory_model.py; the any-rank share is `analyze_e2.py` / `\eTwoAnyPf*` |
| rule 7 | memory_model.py output in the paper | open | decision for the user; nothing from the model is in the paper |
| decode step | probe, lockstep model, pre-registered validation | planned | refinements (b ∈ {1,2,3,4,5,8}, mixed contexts, unequal rank load, prefill stretch measured directly, preemption frees its victim, s10c8 and s15 held out, no parameter from E2/E2b) copied into docs/research-plan.md §0 |
