# Response to the memory-model review, round 1 (2026-09-26)

The open-loop model (`slot_model.py`, `data/exp/slot/`) is deleted and
replaced by `scripts/exp/memory_model.py` (closed loop, block-level LRU pool,
growth during decode, B = 51). `docs/memory-model.md` is rewritten.

| # | Action | Done | Where / result |
|---|--------|------|----------------|
| 1 | Cite the scheduler that ran | yes | memory-model.md §"The serving system" (RBLNScheduler l. 198–205, 335–390, 535, 718–746; upstream single_type_kv_cache_manager l. 135–221, 503; block_pool l. 190); script docstring; docs/testbed.md l. 116–124 rewritten (the optimum_scheduler citation removed) |
| 2 | B = 51 | yes | default `--blocks 51` |
| 3 | Closed replay | yes | session i at t0 + i·spacing, FIFO gate of `cap`, next send = model done + trace gap; door waits 513/623/757 s against 498/636/770 observed |
| 4 | Endogenous class via LRU | yes | hit agreement 0.93–0.98; per-rank miss counts match; table in memory-model.md |
| 5 | Drop "self-reservation"; the facts | yes | removed; "What the data say about why a miss waits" gives the think times and the arrive-to-queue shares from this review; the paper sentence (main.tex 791–796) is flagged for the authors, not changed (the user asked this block to stay on modelling) |
| 6 | Growth holding; preemptions | yes | growth by block boundary; model preemptions 6/1/0/0 against logged 4/1/1/0; the full-reservation and prompt-only variants are gone |
| 7 | Conditional on measured decode; counterfactuals; the prefill statistic | yes | stated in the summary, results heading and caveats; idle-decode counterfactual (`e2_idle.txt`); "any rank prefilling 67/58/31/31 %" replaces the per-rank utilisation; the lockstep counterfactual is left to the probe (item 8) |
| 8 | Decode-stretch probe | planned | needs the NPU server; listed in caveats and research plan; not run |
| 9 | Per rank; better metrics; /metrics check | yes | per-rank TTFT and misses; per-class median relative error, within-class Spearman, log correlation; time series of waiting count and running blocks per rank |
| 10 | Sensitivity B = 49–55 | yes | table in memory-model.md |
| 11 | What enters the paper | open | after round 2 |

Two further changes found while doing this:

- **A bug in the time-series check.** Log entries at equal times were sorted
  by (time, waiting count), which put the pre-admission state last and showed
  0.3–0.45 phantom waiting requests on idle ranks. Now sorted by time only
  (stable); idle ranks read 0/0 and the congested ranks agree to within 0.2.
- **Forced misses in the short-context replay.** The flagged turns
  (derived traces `data/exp/traces/short_m10*.jsonl`) reuse no prefix; without
  this the model produced no misses in the forced arms.
- A performance bug (duplicate prefill wake-ups that cascaded) made the first
  runs take minutes and 40 GB; fixed, a full run takes 2 s.
