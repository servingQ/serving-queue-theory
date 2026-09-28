# Response to the memory-model review, round 2 (2026-09-26)

| # | Action | Done | Where / result |
|---|--------|------|----------------|
| 1 | Sub-block copy semantics (N1) | yes | memory_model.py `try_admit`: a sub-block hit needs `need` free blocks besides its touched tail, gets a new tail, and the source returns ownerless to the MRU end (also on a failed match); memory-model.md statement 2 rewritten with the lines you gave. s15: 631/681 misses, κ 0.80, mean TTFT 5.4/6.7 s (was 235, 0.83 agreement, 3.9 s); unforced misses in the light arms 25/29, 26/29 (were 0) |
| 2 | Only the previous prompt reusable (N2) | yes | reusable blocks = the prompt's blocks (the tail only with a sub-block hash); generated-token blocks cached but ownerless. Hit MRE 0.21–0.23 (was 0.36–0.54). The class rule's mislabelling of prompt-reused turns as partial is stated where the classes are quoted |
| 3 | Re-run; E2b paragraph | yes | "decode stalls hold the batch cap" deleted; the saturated arm is reproduced in its classes, with the under-predicted waiting on ranks 1–3 stated |
| 4 | Cap-8 instability; "smooth"; κ | yes | cap-8 bullet ("only aggregates are stable"); sensitivity sentence rewritten; κ reported |
| 5 | Idle reading; no-cross-rank counterfactual | yes | `--decode nocross` (own-rank prefill pauses computed in the model, decodes shifted by each admitted prefill); table of three decode variants; the closed-loop "more misses at cap 8" stated |
| 6 | Running blocks as consistency check; partial class | yes | results bullets |
| 7 | Causal chain, FCFS tolerance, eviction order, provenance, assertions | yes | links 3–5; inversions counted with no tolerance (0–1 per long-context run, 9–65 per short-context run); hashless tail to the front; the think times, arrive-to-queue shares and resident-at-send share are now computed by memory_model.py (observed and model); assertions on contiguous session and round indices (they caught 2–9 short-context turns without a recorded first token, now simulated and excluded from the TTFT comparison) |
| 8 | Paper corrections; research/testbed.md | testbed yes; paper pending | research/testbed.md: 30 s gap sentence (335/681 = 49 % in s15), 51 allocatable, the ITL source ("read off the replays"). The paper edits (ratio sentence, 51 blocks, any-rank prefill share) are listed in memory-model.md "Note on the paper" for the authors' decision |
| 9 | make exp integration | not yet | only needed before a number enters the paper |
| 10 | Decode probe and lockstep model | planned | needs the NPU server |
| 11 | Model-based price at 50k | after 10 | |
| 12 | Merge into libqueuingsim | planned | |

New finding from the reuse fix: 88–96 % of the long-context non-hits had
their whole prefix resident when sent and lost it while waiting (your
round-1 estimate of a quarter to a third came from a model that reused the
generated tokens and the tail in place).
