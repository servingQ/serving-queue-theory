# Review: "Memory as a queue" (research/memory-model.md, scripts/exp/slot_model.py), round 1

Reviewer role: queueing theory / systems, ICML/SIGMETRICS area chair.
Date 2026-09-26. Read: AGENTS.md, the round-5 review, research/memory-model.md,
scripts/exp/slot_model.py (line by line), research/testbed.md, paper §4.3
(main.tex 780–815), data/exp/e2/*/{rounds,metrics}.jsonl, params.json,
meta.json, data/exp/e1/fit.json, data/exp/slot/*, the server log
data/exp/serve_m27_v7_hosttensor.log, the replayer
(~/icp-serving-workload-analysis/replayer/replay_text_trace.py), and the
engine code in ~/vllm-rbln-dynkv: v1/core/optimum_scheduler.py,
optimum_kv_cache_manager.py, prefix_cache_manager/*, **rbln_scheduler.py**,
rbln_kv_cache_manager.py, and upstream vllm/v1/core/{kv_cache_manager,
single_type_kv_cache_manager,block_pool}.py in the venv.
Re-analysis: I re-ran `slot_model.py` (it reproduces data/exp/slot/e2.txt
exactly) and wrote throw-away scripts in my scratchpad. The main one is a
time-stepped, closed-loop replica model with options for loop (open with
observed sends / closed with think times and the client's session gate),
cache (observed cached tokens / block-level LRU prefix cache), decode
(observed / idle ITL / DP-lockstep stall) and holding (prompt / prompt+output
from admission / growth during decode). Numbers below marked "recomputed"
come from these. No repository file was changed except this report, and
nothing touched the server or the NPUs.

## Verdict: major revision

The core observation survives, and my re-analysis makes it stronger: a
per-rank FCFS queue for KV blocks, with the pool size from the server log
and the E1 cost model, reproduces the long-context waits and the time series
of each rank's waiting queue. Recomputed against /metrics, the model's mean
number waiting per rank is 1.84/1.64, 5.90/6.12, 3.26/3.83 (obs/model) on the
congested ranks, with sample correlation 0.76–0.97. Once the model is closed
and the prefix cache is simulated, it even predicts which turns hit (91–98 %
agreement). That result is worth having.

But the model as written cannot go into the paper, for four reasons:
- it cites a scheduler that did not run;
- the pool size is off by one;
- it is open-loop over a closed-loop replay, so 8–25 % of the turns
  overlap their own predecessor;
- it takes the three endogenous quantities (send times, hit/miss class,
  decode durations) from the measurement it claims to explain.

The mechanism the document gives for why hits do not wait ("self-reservation",
"a miss is a turn after a long gap") is contradicted by the data. The data
also contradict the paper's §4.3 reading "a turn whose prefix is gone waits
46–107× longer". "Explains the waits with no fitted parameter" has to become
"reproduces the waits given the measured decode holding times", and the
decode stretch has to be named as the part it does not explain.

## Major issues

### M1. The model follows the wrong scheduler; the cited lines did not run

memory-model.md §"The serving system", the docstring of slot_model.py and
research/testbed.md l. 118–119 all cite `vllm_rbln/v1/core/optimum_scheduler.py`
(l. 341–347, 376–378, 419–435, "Allocation -> Caching"). The measurement
server logged, on every engine:

```
serve_m27_v7_hosttensor.log:2237  Using custom scheduler class vllm_rbln.v1.core.rbln_scheduler.RBLNScheduler
serve_m27_v7_hosttensor.log:2238  [rbln_scheduler.py:105] Sub-block prefix caching enabled: block_size=4096, sub_block_size=512
```

This is the server that ran every replay. It started 09-24 13:08, s20c0
started 09-24 16:14, the other runs followed on 09-25/26, and there was no
restart in the log. So the engine was `RBLNScheduler` with the sub-block
`RBLNKVCacheManager` on top of upstream `allocate_slots`. The optimum path,
with its outer/inner blocks and FIFO outer-block eviction, never ran. What
actually ran:

- **FCFS head-of-line blocking: correct, via a different line.**
  rbln_scheduler.py 718–747 (`allocate_slots(..., full_sequence_must_fit=True)`;
  `if new_blocks is None: break`). The data agree: on every rank of every
  run, no request sent later got its first token more than 0.5 s before an
  earlier one (recomputed over 68–915 overlapping pairs per run).
- **"Allocation before lookup, so a hit needs as many blocks as a miss":
  wrong mechanism, right count.** RBLNScheduler looks up first
  (`get_computed_blocks`, l. 535). Upstream `get_num_blocks_to_allocate`
  (single_type_kv_cache_manager.py 201–220) then asks for the new blocks
  plus the hit's own cached blocks that sit in the free queue with
  ref_cnt 0 (`num_evictable_blocks`). Between turns a session's blocks are
  all ref 0, so the free-block requirement equals a miss's. But the hit's
  cached blocks are themselves part of the free count, so the condition is
  the same while the *consequence* differs: admitting a hit evicts nobody
  for its prefix, while a miss evicts other sessions' cached prefixes.
- **Prefill exclusive with priority: correct, via different guards.**
  Guards (A)–(D), l. 198–205 and 861–884: the running loop runs first, a
  trailing prefill is scheduled alone, and an admitted waiting prefill
  evicts the decode batch for the step. "Waiting before running" (l. 341–347
  of the optimum file) is not what this scheduler does.
- **Decode growth that does not fit preempts the last running request**
  (l. 335–390). The model does not have this.

Resolution: rewrite §"The serving system" and the docstring against
rbln_scheduler.py and upstream allocate_slots, with the correct line
numbers. Fix research/testbed.md l. 118–119 too. Its claim about the scheduler
may still be true, but the citation is wrong.

### M2. The pool is 51 allocatable blocks, not 52; with 51 the reported model over-predicts by ~45 %

"GPU KV cache size: 212,992 tokens" is `num_blocks × block_size` with
num_blocks = 52 (the log also says "the block pool stays at the estimated
52 blocks", l. 2223). Upstream `BlockPool.__init__` pops one block as the
null block (block_pool.py 190), and `get_usage` divides by
`num_gpu_blocks − 1` (l. 812–813). At most 51 blocks can be allocated.

The document's own sensitivity table shows that the waits move 3–5× for ±4
blocks. With B = 51, the published model (slot_model.py, `--blocks 51`)
gives, recomputed:

| run | obs all | M1, B=52 | M1, B=51 |
|-----|---------|----------|----------|
| s20 no cap | 134.5 | 145.2 | 193.9 |
| s20 cap 16 | 67.1 | 75.7 | 98.9 |
| s20 cap 8 | 11.5 | 13.7 | 13.7 |
| s10 cap 8 | 11.1 | 20.9 | 21.0 |

The sentence "the measured B = 52 is the best of the five" therefore does
not help the model: the correct B makes the published model worse on the
two uncapped-ish runs. The good fit at 52 is partly two errors cancelling:
the off-by-one pool, and the reservation of prompt plus output blocks at
admission (M4).

### M3. Open-loop replay of a closed-loop experiment: sessions overlap themselves

The replayer is closed within a session. Recomputed:
`sent_{k+1} − (done_k + think_{k+1})` is 0.001–0.04 s for every turn of
every run. So the observed send times are an output of the system, and they
already contain the observed waits and decode times. slot_model.py feeds
them in as exogenous arrivals and lets the predicted completion of turn k
fall after the send of turn k+1.

Recomputed from `replay()` with the document's settings, the predecessor is
still running in the model when the successor is sent for 44/332 follow-ups
(s20c0; median overlap 118 s), 84/332 (s20c16), 25/332 (s20c8) and 35/332
(s10c8). For those turns the model has the same session holding two sets of
blocks. That is physically impossible, and it contradicts the document's own
explanation, which relies on the predecessor's release. With the cap, the
first-turn send times are endogenous too: the client gate admits a session
when another session ends, and the door wait is 500–770 s on average.

Resolution: make the model closed. Session i arrives at
`t0 + i · spacing`, passes the client's FIFO gate (cap), and sends turn k+1
at the *model's* done_k + think_{k+1}. I did this. With everything else as
in the document (observed classes, observed D, full reservation, B = 52), the
closed model gives mean TTFT 140.9 / 68.7 / 12.0 / 11.6 s (obs 134.5 / 67.1 /
11.5 / 11.1). That fits at least as well as the open version. The
closed model also predicts the door wait: 498 / 636 / 770 s observed
against 498 / 638 / 757 s for s20c16 / s20c8 / s10c8, recomputed with the
M4c variant. This check is weak, though, because session lengths come from
the measured D. The closed version is both correct and no worse, so
there is no reason to keep the open one.

### M4. The class is an input, and the stated mechanism for it is false

slot_model.py computes P from the *observed* `cached_tokens`, and it reports
results by the *observed* class. The class is not exogenous:

- **Misses are not turns after long gaps.** Mean think time before a
  follow-up, recomputed: hit 5.9–6.6 s, miss 5.0–7.2 s, partial 8.6–13.6 s.
  The gap before a miss is no longer than the gap before a hit. (Gaps are
  capped at 30 s in this trace in any case.)
- **Misses are turns that arrive to a queue.** The share of follow-ups that
  found another request of their rank waiting when they were sent is 92 %,
  100 %, 99 % and 100 % for misses in s10c8, s20c0, s20c16 and s20c8, against
  2–4 % for hits. Of the follow-ups that arrived to an empty rank, 88–94 %
  hit; of those that arrived to a queue, 3–34 % did.
- **Mechanism.** Under strict FCFS and a nearly full pool, every admission
  ahead of a turn evicts least-recently-freed cached blocks, and on a
  congested rank that reaches the prefixes of sessions that are thinking or
  queued. In my LRU model (below), about a quarter to a third of the
  non-hits (48/172, 40/129, 11/48, 4/49 in the four runs) had their full
  prefix resident when they were sent and lost it while waiting. The rest
  lost it during the think time to admissions on a congested rank.
- **What "self-reservation" should say.** The data do not support it as
  written. A hit does not wait because its rank had no queue when it
  arrived, which is also why its prefix survived.

Consequences:

(a) "The model reproduces the class split without being told about it" is
not true of slot_model.py. The split enters through P and through the
grouping.

(b) The paper's §4.3 sentence "a turn whose prefix is gone waits
46–107× longer than a hit" (main.tex 791–796) compares groups selected on
congestion. Most of a miss's 117–279 s is queueing that caused (or
coincided with) the eviction. It is not the price of the miss. This bears
on the paper's thesis and has to be reworded before the memory model goes
anywhere near it.

(c) The positive finding. The class can be made endogenous with a small,
parameter-free addition: a block-level LRU free queue per rank. A request
releases its blocks tail first (upstream frees in reverse order). An
admission takes empty blocks first and then evicts from the LRU end. A hit
touches its own leading cached blocks. Closed loop, observed D, growth
holding (M5), B = 51, recomputed:

| run | obs hit / partial / miss / all | model hit / partial / miss / all | hit agreement |
|-----|------|------|------|
| s20 no cap | 2.6 (154) / 80 (14) / 279 (164) / 134.5 | 1.5 (160) / 48 (10) / 269 (162) / 126.2 | 0.98 |
| s20 cap 16 | 2.6 (196) / 17 (13) / 184 (123) / 67.1 | 1.8 (203) / 17 (7) / 190 (122) / 68.1 | 0.97 |
| s20 cap 8 | 2.6 (277) / 25 (39) / 117 (16) / 11.5 | 1.4 (284) / 29 (29) / 106 (19) / 10.9 | 0.92 |
| s10 cap 8 | 2.0 (278) / 26 (41) / 142 (13) / 11.1 | 1.4 (283) / 28 (35) / 132 (14) / 10.4 | 0.98 |

Counts in parentheses are the model's own classes. With this version the
model predicts which turns miss and how long they wait, and the only inputs
beyond the trace are B, the block size, the cap and E1. That is the result
worth reporting, but it still takes decode from the measurement (M5).

### M5. Decode holding times are measured, and they carry most of the memory pressure

The document says in a caveat that D is observed. It does not say how much
of the result that input is.

- **Outputs are small; D is stretched.** Mean output is 1,103 tokens
  (median 349). Observed D is 53–118 s mean (median 19–35 s). The median ITL
  is 0.117 s uncapped, 0.093 at cap 16 and 0.043–0.048 at cap 8, against
  about 0.016 s idle. So D is inflated 3–7×, and by different amounts in
  different runs.
- **The pool binds only because of the stretch.** The time-average block
  load of running requests per rank, Σ blocks·(P+D)/T/4, is 18.6–31.7 blocks
  with observed D and 7.0–7.2 with idle decode. The prefill part is only
  1.1–2.7 blocks.
- **Replacing measured D removes most of the miss wait.** Closed model,
  observed classes, B = 52: with D = output × 0.016 s, the miss TTFT falls to
  106 / 111 / 47 / 41 s (obs 279 / 184 / 117 / 142). With a first-cut DP
  lockstep stall model (a rank does not decode while it prefills; while any
  other rank prefills, a decode token takes one 512-token chunk time), it is
  222 / 144 / 57 / 41 s, and the makespan is 25–35 % short (3968 against
  5253 s uncapped).
- **"The binding resource is the pool, not the prefill server (per-rank
  prefill utilisation 0.03–0.39)" uses the wrong statistic.** The DP ranks
  step in lockstep (research/testbed.md), so what stalls decode is *any* rank
  prefilling. Recomputed from the replays, some rank is prefilling 67 %,
  58 %, 31 % and 31 % of the time. The causal chain the data support is:
  prefill on any rank stretches every rank's decode; stretched decodes hold
  blocks; the pool binds; the FCFS head blocks; queued and thinking turns
  lose their prefixes; misses add prefill. The memory model covers links 3–5.
  Links 1–2 are data.

Resolution: state the result as conditional on the measured decode
durations everywhere (summary, "What the model explains", any paper
sentence). Then build and validate a decode-stretch model from probes, not
from the replays: ITL as a function of own-rank and peer-rank prefill
activity, measured on an idle server like E1. Report the closed model with
modelled D next to the one with observed D. Until the decode side is
modelled, "explains the waits" and "no fitted parameter" overstate what was
shown. The per-request D is an input carrying 369 numbers per run.

### M6. Holding rule: the chosen variant is not the engine's, and the rejected one is not the faithful alternative

The engine admits on the prompt's blocks (`full_sequence_must_fit` uses
`request.num_tokens`, which is the prompt for a new request) and grows by one
block when decode crosses a 4096-token boundary. M1 instead reserves
⌈(prompt+output)/4096⌉ from admission. The rejected `--prompt-only` never
grows at all. So neither variant is the engine, and the reported contrast
("prompt-only under-predicts 2–5×, so the blocks decode adds matter") is
between two wrong models.

A growth variant is the faithful one. Blocks follow the tokens generated,
linear over D; preemption is not modelled; the engine logged 0–4
preemptions per run. That variant is what the table in M4 uses. With the
open loop it also works about as well as the full reservation. Only 66 of
the 369 requests cross a block boundary during decode in any case.

Report the growth variant, and model or count preemptions: they are
logged, so check that the model produces a similar number.

### M7. The agreement statistics flatter the model; rank imbalance is the real story

- **Pearson correlation on raw TTFT is dominated by a few hundred-second
  values.** It measures whether the model finds the rank-3 misses. The
  median |error| is dominated by the 75 % of turns that are hits.
- **The doc's correlation list is in the wrong order.** memory-model.md
  prints "0.73, 0.93, 0.98, 0.94" as if in table order (no cap, cap 16,
  cap 8, s10). The file order is s10c8, s20c0, s20c16, s20c8, so the
  uncapped run is 0.93 and s10 is 0.73. The script also computes it for M2,
  not M1 (equal in E2, but label it).
- **Per rank** (crc32 pinning gives 6/11/8/12 sessions), recomputed with the
  published model:
  - rank 0 never waits (obs 2.6–3.1 s);
  - in both cap-8 runs **every miss is on rank 3** (16 and 13 requests);
  - in s10c8 the model puts 10.7 s on rank 2 against 3.0 s observed;
  - in s20c0 it puts 116.5 s on rank 2 against 66.5 s.
- **The effective sample is small.** "Four runs" means one or two congested
  ranks per run.

Report per rank. Use error metrics that do not let hits or the tail
dominate: per-class median relative error (recomputed: 0.11 / 0.12 / 0.19 /
0.26 for misses), Spearman within class (0.80–0.94), and the log-scale
correlation. Add the time-series validation against /metrics that I ran
(waiting count and blocks per rank). It is the most convincing evidence
available, and it tests the model's state, not just its output.

## Minor issues

1. **slot_model.py event loop.** Apart from M3 I found no bug. Releases are
   applied before admissions at equal times (right: the engine frees in
   update_from_output before the next schedule). The prefill server is
   checked before blocks. The `pf_free` event is added only when there is a
   head. The `blocks > pool` branch is dead code on these data. The closed
   version should replace it anyway.
2. **Predicted TTFT is start − sent + P and excludes frontend time.** For
   50k-token prompts the tokenizer and HTTP time is not negligible: observed
   hit TTFT is 2.0–2.6 s against 1.5–1.8 s for M0. State the offset (it was
   measured in E2b) instead of letting it sit inside the "hit" comparison.
   In the published model the hit prediction (3.3–4.9 s) is above the
   observation only because of the self-overlap in M3.
3. **Sub-block hits.** Sub-block hits copy from a source block that stays
   referenced until the copy runs (rbln_kv_cache_manager, `pending_copy_ops`).
   This is transient; say it is ignored.
4. **The sensitivity table varies B in the open model only.** In the closed
   LRU model the response is flatter below 51 and has a cliff above it: the
   cap-8 misses go from 19 at B = 51 to 0 at B = 56. Show B = 50–54 in
   single steps.
5. **E2b.** "M1 = M0 in every run (blocks never bind)" is true of running
   holdings. But research/testbed.md attributes the s15 thrash to the pool
   evicting cached prefixes. The document should say that in E2b the pool
   acts through the cache, which the model takes as data. The LRU extension
   of M4 is the test for that run.
6. **The server was not restarted between replays of the same trace.** The
   first turns show 0–1/37 cached, so no carry-over was found. Say it was
   checked.
7. The doc says "the closed loop reserves a returning session's memory for
   it". The engine has no reservation. Delete the sentence (see M4).

## Action list for the authors

1. Replace every optimum_scheduler.py citation (memory-model.md,
   slot_model.py docstring, research/testbed.md 118–119) with the
   RBLNScheduler / upstream allocate_slots lines that ran (M1).
2. Set B = 51 allocatable blocks (the null block) and re-run everything
   (M2).
3. Make the replay closed. Use session arrivals from params.json, the
   client's FIFO session gate, and next send = model done + think. Delete
   the open-loop results (M3).
4. Make the class endogenous with a block-level LRU prefix cache (tail
   evicted first, touched prefixes removed from the free queue). Report
   predicted against observed hit/partial/miss counts and per-class TTFT
   (M4c).
5. Remove the "self-reservation" / "long gap" explanation. Replace it with
   the measured facts: misses arrive to a queue (92–100 %) and their think
   time is the same as hits'. Reword main.tex 791–796 so that the hit/miss
   TTFT ratio is not read as the price of a miss (M4a, M4b).
6. Use growth-during-decode holding, and model or count preemptions
   against the logged 0–4. Drop the full-reservation and prompt-only
   variants, or show them as bounds (M6).
7. State the result as conditional on the measured decode durations.
   Report the idle-decode and lockstep-decode counterfactuals. Replace
   "per-rank prefill utilisation" with the fraction of time any rank
   prefills (M5).
8. Plan a decode-stretch probe on an idle server: ITL with 0/1/2/3 peer
   ranks prefilling and with the own rank prefilling. Put it in the model;
   only then claim "no fitted parameter" for the whole chain (M5).
9. Report per rank. Replace the Pearson/median-|err| pair with per-class
   median relative error, within-class Spearman and log-scale correlation.
   Fix the order of the correlation list. Add the /metrics time-series
   check of waiting count and blocks per rank (M7).
10. Sensitivity: B = 49–55 in single steps for the final (closed, LRU,
    growth) model (minor 4).
11. Only after 1–9: decide what enters the paper. My recommendation is one
    paragraph in §4.3 with the closed-loop LRU model's class and TTFT
    table, plainly labelled "given measured decode times", and the time
    series in App. D.
