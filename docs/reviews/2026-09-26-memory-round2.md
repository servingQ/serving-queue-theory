# Review: "Memory as a queue" (docs/memory-model.md, scripts/exp/memory_model.py), round 2

Reviewer role: queueing theory / systems, ICML/SIGMETRICS area chair.
Date 2026-09-26. Read: my round-1 report, the authors' response
(docs/reviews/2026-09-26-memory-round1-response.md), the rewritten
docs/memory-model.md, scripts/exp/memory_model.py (line by line),
docs/testbed.md (the rewritten l. 116-135), paper/main.tex (abstract,
intro, §2.2 l. 336-346, §4.3 l. 785-815), paper/simulation.tex, the replayer
(~/icp-serving-workload-analysis/replayer/replay_text_trace.py), and the engine:
vllm_rbln/v1/core/rbln_scheduler.py, rbln_kv_cache_manager.py, and upstream
vllm/v1/core/{kv_cache_manager,single_type_kv_cache_manager,block_pool}.py
in ~/vllm-rbln-dynkv/.venv (vLLM 0.26.0, the version in the server log).

Re-runs: `memory_model.py` on data/exp/e2/s*/rounds.jsonl (B = 51, default),
`--decode idle`, `--blocks 49..55`, and on data/exp/e2b/s*/rounds.jsonl. Every
output file in data/exp/memory/ is reproduced byte for byte (2 s per run).
Throw-away scripts in my scratchpad: a copy of the model with two
engine-faithful switches (below: "CoW" and "prompt-only reuse"), a Cohen's κ
computation, and a decode-stretch regression. No repository file was changed
except this report; the server and the NPUs were not touched.

## Verdict: minor revision for the long-context result; major for the short-context claims and for anything that goes into the paper

The authors did what round 1 asked. The model is now closed, uses the
scheduler that ran, the right pool (51), an endogenous class via a
block-level LRU, growth holding, per-rank and per-class metrics, and the
/metrics time series. It is stated as conditional on the measured decode
durations. I reproduced every number in memory-model.md. The long-context
result is real and robust: with observed decode, strict FCFS on blocks plus
an LRU prefix cache reproduces which turns miss (κ = 0.92 / 0.95 / 0.92 /
0.76 against majority-class baselines of 0.84 / 0.54 / 0.59 / 0.83) and the
mean TTFT per class, and it keeps doing so under the engine corrections
below.

Reading the engine a second time I found one mechanism the model gets wrong,
and it is the one that matters at short contexts: **a sub-block hit does not
reuse the old tail block. It copies it into a new block and leaves the old
one cached at the MRU end of the free queue** (major N1). With that single
change the model reproduces the saturated short-context arm it currently
"does not reproduce" (680 observed misses; 235 in the model now, 676 with the
change) and the unforced misses of the light arms. The document's
explanation for that failure ("decode stalls hold the batch cap") is
therefore wrong. A second, smaller mismatch is that the model treats the
previous turn's generated tokens as reusable, but the replayer sends the
trace's text, so only the previous prompt is reusable (N2). Most of what the
document calls a "frontend offset" on hits is this.

The paper still carries the round-1 misreadings (abstract, intro, §4.3:
"46-107× longer than a hit", "52 blocks", per-rank utilisation). The model now
provides the evidence to correct them, and those corrections come before any
model text enters the paper (N6).

## Status of round-1 items

| # | Item | Status | Note |
|---|------|--------|------|
| M1 / A1 | Cite the scheduler that ran | **Resolved**, one mechanism wrong | RBLNScheduler lines are right (FCFS break l. 739-746, guards l. 198-205, preemption l. 335-390, lookup l. 535). Statement 2 ("a hit needs as many free blocks as a miss") is wrong by one block for sub-block hits (N1). Statement 3 (eviction order) is incomplete (minor 3). |
| M2 / A2 | B = 51 | **Resolved** | Default `--blocks 51`; get_usage and the null block checked again (block_pool.py l. 805-816). |
| M3 / A3 | Closed replay | **Resolved** | Session i at t0 + i·spacing, FIFO gate matching `SessionAdmissionGate` (replayer l. 345-373), next send = model done + observed gap. Door waits 513 / 623 / 757 s against 498 / 636 / 770 s. Latent indexing assumptions, see minor 5. |
| M4 / A4 | Endogenous class via LRU | **Resolved** | Hit agreement 0.93-0.98 reproduced; κ added above. |
| M4a,b / A5 | Drop "self-reservation"; reword the paper | **Resolved in the doc, not in the paper** | The doc's section "What the data say about why a miss waits" is right for E2. It should add that E2b misses do follow long gaps (N6, minor 9). Paper unchanged (N6). |
| M5 / A7 | Conditional on decode; counterfactuals; statistic | **Mostly resolved** | Stated in the summary, headings and caveats. The idle counterfactual is misread at cap 8 (N4). The causal-chain sentence is inconsistent (minor 1). The lockstep counterfactual was not run. |
| M6 / A6 | Growth holding; preemptions | **Resolved** | Model 6 / 1 / 0 / 0 against logged 4 / 1 / 1 / 0 (I re-derived the logged numbers from `vllm:num_preemptions` in metrics.jsonl). |
| M7 / A9 | Per rank, better metrics, time series | **Resolved**, with a caveat | The running-block series is nearly guaranteed by the observed D (N5). Partial-class errors are omitted (minor 7). |
| A8 | Decode-stretch probe | **Not done** (needs the server) | See "Next modelling step". |
| A10 | Sensitivity B = 49-55 | **Resolved**, misdescribed | Table reproduced; "smooth below 51" is not what it shows (N3). |
| minor 2 | Frontend offset | **Partially** | Mostly not frontend: N2. |
| minor 3 | Sub-block copies | **Not resolved; was under-rated by me in round 1** | This is N1. |
| minor 5 | E2b: the pool acts through the cache | **Partially** | The doc says the saturated arm is not reproduced and blames decode; the cause is N1. |
| minor 6 | Carry-over between replays checked | **Resolved** | |
| minor 7 | Delete "reservation" | **Resolved** | |

## New major issues

### N1. Sub-block hits copy the tail into a new block and leave the old tail cached at the MRU end; the model reuses it in place

What the engine does for a hit whose prefix ends inside a block. This is
nearly every hit: the long-context prefixes are 12k-90k tokens, and the
short-context ones are 2k-9k.

1. `get_computed_blocks` returns only the full-block hits (rbln_scheduler.py
   l. 525-535). `_try_sub_block_match` → `get_computed_blocks_sub_block`
   (rbln_kv_cache_manager.py l. 386-474) finds the old tail block by its
   sub-block hashes and **touches it** (l. 453-455). Touching removes it from
   the free queue (block_pool.py l. 702-715).
2. `allocate_slots(..., full_sequence_must_fit=True)` then asks for
   `cdiv(prompt, 4096) − full_hits + evictable(full_hits)` free blocks
   (single_type_kv_cache_manager.py l. 170-221). The sub-block tokens are
   passed as tokens to compute (rbln_scheduler.py l. 718-724), so the tail
   slot is a **new** block. The free count excludes the touched source. So
   the hit needs `need` free blocks *plus* its own old tail, one block more
   than a miss of the same length. A miss needs only `need`.
3. After allocation the source is handed to a copy op (l. 476-505). After the
   step, `release_copy_ops` → `free_blocks([src])` (rbln_scheduler.py
   l. 1090-1097) appends it, with its synthetic hash (l. 722-776), **to the
   tail (MRU end)** of the free queue (block_pool.py l. 719-740). It is now a
   stale duplicate: the new tail supersedes it for every later match, but it
   sits behind other sessions' useful prefixes in eviction order. On a failed
   admission the match is released the same way (l. 886-890), so a head that
   is blocked moves its own tail to MRU at every step.

The model (memory_model.py l. 159-185) instead counts the old tail as a free
"own" block (l. 163), touches it, and reuses it as the new tail. It needs
`need` free blocks and leaves no orphan.

Effect, recomputed with a copy of the model in which a sub-block hit needs
`need` free blocks besides its source, gets a new tail block, and returns the
source to the MRU end with no owner (about 15 lines of change):

| run | observed misses / mean TTFT | model now | model with CoW |
|-----|------|------|------|
| s15_base (saturated) | 680 / 6.7 s | 235 / 3.9 s (hit agr. 0.83) | **676 / 5.7 s** (hit agr. 0.93) |
| s25_base | 29 / 0.6 | 0 / 0.4 | 43 / 0.5 |
| s25_base_s1 | 29 / 0.6 | 0 / 0.4 | 44 / 0.5 |
| s25_m10 (286 forced) | 364 / 1.1 | 286 / 0.7 | 360 / 0.8 |
| s25_m10_s1 (282 forced) | 370 / 1.1 | 282 / 0.7 | 369 / 0.8 |
| s35_m10 (192 forced) | 192 / 0.7 | 192 / 0.6 | 192 / 0.6 |

On s15 the per-rank misses become 311 / 121 / 104 / 140 against 269 / 162 / 106 /
143, where they were 158 / 31 / 17 / 29. The waiting series on rank 3 moves
from 1.57 to 3.39 (observed 4.39). What remains of the s15 gap is on ranks 1
and 3 (waiting 2.5 against 5.4) and in the hit TTFT (2.8 against 4.4 s). The
prefill stretch under concurrency (1.10-1.23× E1, docs/testbed.md) is the
first candidate for that remainder (minor 10). So the statement "the saturated
arm is not reproduced ... its decode stalls hold the batch cap" (memory-model.md
l. 102-105) is contradicted, and so is "the rest are unforced misses the model
does not produce" (l. 101-102): with the engine's copy semantics the model
produces them.

In E2 the change is small in aggregate (mean TTFT 136.1 / 66.1 / 11.6 / 10.1 s
against 133.8 / 69.5 / 10.7 / 10.4 now, observed 134.5 / 67.1 / 11.5 / 11.1),
because the tail is one block out of 3-22. But it moves the turn-level
statistics of the cap-8 runs a lot (N3).

Resolution: implement the copy semantics (the extra block at admission, the
new tail, the orphan at MRU, and optionally the per-step MRU refresh of a
blocked head's tail). Rewrite statement 2 of "The serving system" with these
lines. Re-run everything.

### N2. Only the previous prompt is reusable, not prompt + completion

The replayer sends raw `/v1/completions` with the trace's prompt text and
`ignore_eos` (replay_text_trace.py l. 26-44). The model's generated tokens
never appear in the next prompt. The model sets the reusable prefix to
`prompt + out` (l. 137, 244) and credits a hit with ⌊(prompt+out)/512⌋·512
cached tokens (l. 182-183). Data: among follow-ups with cached > 0, the
cached count lies between ⌊prompt/512⌋·512 and ⌊prefix/512⌋·512 (prompt
reused, output recomputed) for 144/319, 59/168, 88/209, 144/316 turns (s10c8,
s20c0, s20c16, s20c8). The median output of those turns is 1.1-1.5k tokens. Of
the observed "partials", 9 / 6 / 6 / 9 are such turns, not evictions.

Effect, with the reusable prefix set to the previous prompt, and the blocks
holding generated tokens cached but ownerless: hit TTFT 2.1 / 2.1 / 1.7 /
1.7 s (now 1.9 / 1.9 / 1.9 / 1.4; observed 2.6 / 2.6 / 2.6 / 2.0), hit MRE
0.21-0.23 (now 0.36-0.54), partial MRE 0.06 / 0.29 / 0.46 / 0.06 (now 0.65 /
0.99 / 0.34 / 0.21). So most of what the document calls "client and frontend
time" (l. 90-92) is recomputed output tokens. The remaining offset is 0.3-0.9 s.
The class rule of analyze_e2.py also mislabels these turns as partial. Say so
wherever the observed class split is quoted.

### N3. The cap-8 turn-level numbers are knife-edge; do not quote them to two digits

In both cap-8 runs every miss is on rank 3, and there are 13-16 of them. The
per-class statistics for misses move with engine-faithful details that leave
the aggregate unchanged:

| s10c8, misses | MRE | Spearman |
|---|---|---|
| model now | 0.03 | 0.99 |
| with CoW | 0.43 | −0.46 |
| with prompt-only reuse | 0.43 | −0.46 |
| both | 0.83 | −0.62 |

For s20c8 the miss count goes 15 → 22 → 20 → 20. The B-sensitivity table
shows the same thing: at cap 8 the mean TTFT is not monotone in B (s20c8 8.2
at B = 52, 9.2 at 53; s10c8 5.4 at 54, 6.9 at 55). The uncapped miss count is
not monotone either (160 at 51, 163 at 52). "The response is smooth below 51
and falls off above it" (l. 149) does not describe the table. What is robust:
the uncapped and cap-16 runs (misses, per-rank counts, mean TTFT and waiting
series move by ≤ 5 % under every variant), and the cap-8 *aggregate* (mean
TTFT, which rank misses). Report the cap-8 per-turn miss metrics as "n = 13-16,
not stable under ±1 block or engine details", or pool them.

### N4. The idle-decode counterfactual is misread at cap 8, and it is the wrong lower bound

`e2_idle.txt` gives, at cap 8, **more** misses than observed decode (s20c8 37
against 15; s10c8 16 against 14) and the same mean TTFT (11.9 against 11.5
observed). In a closed system, faster decode shortens the cycle and raises the
request rate on rank 3. "Without the decode stretch the pool binds much less"
(l. 131-132) holds for the uncapped and cap-16 runs only. Say so; it is itself
an interesting closed-loop effect.

`D = out × 0.017 s` also removes the own-rank prefill pauses (guard D: an
admitted prefill evicts the decode batch for the step). Those pauses are
endogenous to this model, because it knows each rank's prefill intervals. The
informative counterfactual is therefore "no cross-rank stretch":
`D = out × ITL + (own-rank prefill time during the decode)`, computed inside
the simulation. That is the first half of the decode-stretch model below.

### N5. The running-block agreement is close to guaranteed by the observed decode durations

The mean running blocks per rank agree within 0.1-1.9 blocks in all 12 runs
(e.g. s20c0 r3 38.8 / 40.3), including s15, where the model is otherwise far
off. That is Little's law: with observed D, the mean held blocks ≈
Σ_i blocks_i·(P_i + D_i)/T is fixed by the inputs up to the small P error.
The correlation of the series (0.74-0.97) says a little more, but mostly that
D is placed at the right time. The waiting-count series is the real test of
the model's state. Present the kv series as a consistency check, not as
validation.

### N6. The paper still says what round 1 showed the data do not support

- Abstract l. 98-100 and intro l. 179-181: "a miss waits 46-107× longer than
  a hit, mostly for KV blocks"; §4.3 l. 791-797 the same, as "A resident
  prefix does not queue". In E2, 92-100 % of misses arrived to a queue and
  2-4 % of hits did. The ratio compares turns selected on congestion. The
  memory model makes the right statement possible: "misses are the turns that
  queued for blocks; the queue caused the eviction". The model also makes the
  thesis quantity computable (next section, step 4).
- §4.3 l. 787: "A rank's pool holds 52 blocks". 51 are allocatable.
- §4.3 l. 800-801: "The per-rank utilisation stays at ...". Under DP
  lockstep the statistic that matters is the share of time any rank
  prefills (67 / 58 / 31 / 31 %).
- docs/testbed.md l. 125-133 says of s15 that "every miss followed a 30 s
  gap". Measured: 49 % of s15 misses followed a gap of at least 29 s (mean
  gap 19.8 s against 3.0 s for hits). In s25 it is 29/29. So in E2b the gap
  story is largely right, and in E2 it is wrong (hit 5.9-6.6 s, miss
  5.0-7.2 s). The two replays have different miss mechanisms: congestion at
  50k contexts, LRU age at short contexts, with the copy orphans shrinking
  the effective cache. memory-model.md should state both.

The response says the paper sentence stays until the authors decide. Fine
for this block. But nothing from the model can enter §4.3 next to a sentence
it contradicts.

## Minor issues

1. **Causal chain** (l. 127): "The model covers links 2-5. Links 1-2 enter as
   the measured decode durations." Link 2 is in both. It covers links 3-5.
2. **FCFS check** (l. 27-28): "on no rank did a later-sent request get its
   first token before an earlier one". My round-1 check allowed 0.5 s.
   Either state the tolerance or recompute it without one.
3. **Eviction order** (statement 3): `free_blocks` appends hashed blocks to
   the MRU end but **prepends** hashless blocks to the front (block_pool.py
   l. 727-740). A partial tail with fewer than 512 computed tokens gets no
   synthetic hash (rbln_kv_cache_manager.py l. 736-745) and is evicted first.
   The model appends everything. It is rare at these lengths, but say it or
   implement it.
4. **Provenance of the "why a miss waits" numbers.** The think times, the
   92-100 % arrive-to-queue share, "a quarter to a third ... in the model"
   (l. 114-116) and "67 / 58 / 31 / 31 %" come from my round-1 scripts, not
   from memory_model.py. "In the model" refers to my model, not this one. Put
   them in memory_model.py or analyze_e2.py (the first is a 10-line addition:
   record, at each non-hit's send, whether its full prefix was resident) or
   mark them as reviewer computations.
5. **Latent indexing.** Arrival time uses the position in `sorted(sessions)`
   (l. 120-122), not `session_index`. `sessions[s][k]` assumes that no row of
   a session was filtered out (l. 81, 134). Both hold in all 12 runs (indices
   0..N−1 contiguous, 0 errors), but add assertions. Otherwise a dropped
   session shifts every later arrival by one spacing.
6. **Preemption** is a growth-failure count. The engine also blocks all
   admissions in a step with a preemption (`if not preempted_reqs`,
   rbln_scheduler.py l. 457-461) and re-queues the victim at the head. Fine as
   a caveat.
7. **Report the partial class.** Partial MRE is 0.65 / 0.99 in s20c0 / s20c16,
   and s20c16 partial TTFT is 17 against 35 s. The doc quotes only misses and
   hits. N2 fixes most of it.
8. **Chunked allocation.** `full_sequence_must_fit` is only a gate. The blocks
   are allocated chunk by chunk (kv_cache_manager.py l. 412-470,
   `num_tokens_need_slot = computed + chunk`). The model holds them all from
   admission. Negligible with exclusive prefill, but say it.
9. **docs/testbed.md**: besides the 30-s-gap sentence (N6), "the pool is 52
   blocks" should say 51 allocatable. The ITLs quoted there (0.10 s with a
   peer prefilling, 0.17-0.25 s with own prefills pending) need a source. If
   they come from the replays, say so; they are the numbers the decode probe
   must reproduce independently.
10. **Prefill stretch.** docs/testbed.md measures the server's prefill at
    1.10-1.23× E1 under concurrency (lockstep: a step lasts as long as the
    slowest rank). The model uses unstretched E1. Name it as a second omission
    next to decode.
11. **Agreement metric.** Report Cohen's κ (0.92 / 0.95 / 0.92 / 0.76 for
    s10c8 / s20c0 / s20c16 / s20c8) next to raw agreement. At cap 8 the
    majority class alone gives 0.83-0.84.

## Is it correctly scoped now?

Mostly yes. "Given the measured decode durations" is in the summary, the
results heading, and the caveats; "explains" and "no fitted parameter" are
gone. What is still too strong:
- the E2b paragraph (N1);
- the frontend attribution (N2);
- the idle counterfactual reading (N4);
- the running-block series as validation (N5);
- the cap-8 two-digit turn metrics (N3).

Circularity that remains, and should be said once:
- The per-turn D is attached to the model's first-token time. The stretch in
  D was produced by the congestion at the *observed* time. That is harmless
  where the model tracks the observed timeline (the TTFT errors are small
  relative to D), but it is conditioning on 369 outcome numbers per run.
- The think gaps are observed and are exogenous (replayer l. 395). That is
  fine.

## What belongs in the paper, and in what form

AGENTS.md rule 7: model output is not a measurement, and it enters the paper
only through generated files. memory_model.py is a trace-driven simulator of
the testbed replica with measured decode as input. It is neither a testbed
measurement nor libqueuingsim.

- **Now:** nothing from the model in the main text. First make the three
  corrections of N6 in the paper (the ratio sentence in abstract, intro and
  §4.3; 51 blocks; the any-rank-prefilling statistic). They are corrections
  from the measurements, not model results, so they need no model.
- **After N1-N2 and action items 1-6:** one or two sentences in §4.3 after
  "The wait is for KV blocks": "A replica model that adds the block pool
  (FCFS admission on blocks, the engine's LRU prefix cache) to the fitted
  cost reproduces, given the measured decode durations, which turns miss
  (κ ...) and the per-class TTFT (App. D)." The numbers must be macros from
  `make exp` (add memory_model.py to the target, writing
  `paper/exp/macros-memory.tex` and `tab-memory.tex`). The App. D table
  should hold the class counts and TTFT per run with a column label "model,
  measured decode", plus the waiting-count series as a figure. No
  proposition, no Lean. Nothing on κ for the cap-8 turn metrics beyond the
  aggregate (N3).
- **Where it really belongs:** it is the missing validation of §4.2's
  "simulated replica". paper/simulation.tex models decode as bandwidth PS
  with a constant ω and has no FCFS-on-blocks admission, yet this analysis
  shows block admission dominated the long-context replay. Port the pool
  mechanics (FCFS on blocks, engine LRU with copy semantics, closed client
  with gate) into libqueuingsim's replay model. Score it against E2/E2b with
  the metrics above; that is the "faithfulness scoring" experiment done
  honestly. Once decode is modelled (below), the §4.2 replica and this model
  should be one simulator.

## Next modelling step: the decode stretch

A preview from the replays themselves; these are in-sample regressions, so
they are *not* validation. For every E2 turn with ≥ 50 output tokens,
regress D on (out, overlap of the decode interval with own-rank prefill
intervals, overlap with other-rank prefill intervals outside own-rank
prefill). The prefill intervals are [first − P_E1, first]. The coefficients:
per-token time 0.029-0.037 s, own-rank overlap 1.05-1.48, other-rank overlap
0.85-1.12. Lockstep physics predicts about 1 and 1 − ITL/chunk ≈ 0.94. The
R² of 0.99 is mechanical (overlaps scale with D), so ignore it. What
matters: the stall coefficients are near their physical values, and the base
per-token time is about twice the idle 0.017 s. With 0.017 s the mean D is
25-35 % short, the same gap as the round-1 makespan. So the model needs
**decode step time as a function of batch size and resident context**, not
a single ITL.

Model (step-level, all ranks on one clock):
- each step lasts max over ranks of (the chunk time P(512, K) of a rank that
  prefills; else t_dec(b_r, ΣK_r) for its decode batch);
- a rank that prefills decodes nothing that step (guard D);
- every other rank advances each running request by one token;
- apply the same max to prefill chunks, which gives the 1.1-1.2× prefill
  stretch (minor 10);
- D is then endogenous, and the only new inputs are t_dec from a probe.

Probe (idle server, E1-style, no replay data):
1. t_dec(b, K) for b = 1, 2, 4, 8 and per-request contexts 2k, 12k, 50k,
   90k, one rank decoding, the others idle (dummy steps);
2. the same with all four ranks decoding (the lockstep max);
3. one rank decoding at (b, K) while a peer runs a prefill at context K′: ITL
   should equal the chunk time;
4. own-rank prefill pending: decode stalls completely.

Check the fitted t_dec against the testbed.md ITLs (0.017 idle, 0.10 with a
peer prefilling).

Validation (pre-register the metrics; out of sample):
- per-turn D (median relative error by rank), mean ITL and makespan per run
  for the four E2 runs and the E2b arms, with no parameter taken from them;
- then the TTFT, class, κ and waiting-series metrics with modelled D, next to
  the observed-D table;
- hold out s10c8 and s15_base entirely while iterating on the model;
- suggested acceptance: makespan within 10 %, miss count within 15 %, mean
  TTFT within 25 % on the uncapped and cap-16 runs; cap-8 judged on
  aggregates only.

Then, and only then, the model can compute the paper's thesis quantity at
50k contexts. For each miss, re-run with its prefix forced resident (and,
for hits, forced evicted) and record ΔΣTTFT over all turns. That is the
price of a miss in the sense of `prop:price` (total added TTFT), with the
block wait included. The raw hit/miss ratio cannot give it. It should be
compared with the bracket, in the manner of the short-context price test.

## Action list for the authors

1. Implement the sub-block copy semantics (N1): the source tail is excluded
   from the free count; the hit needs `need` free blocks plus the source;
   the tail gets a new block; the source returns to the MRU end without an
   owner. Rewrite statement 2 of "The serving system" with
   rbln_kv_cache_manager.py l. 386-505 and rbln_scheduler.py l. 718-753,
   886-890, 1090-1097.
2. Make only the previous prompt reusable; keep the generated-token blocks
   cached but useless (N2). Report the remaining hit offset as the frontend
   term.
3. Re-run E2 and E2b; replace the E2b paragraph (the saturated arm and the
   unforced misses). Delete the "decode stalls hold the batch cap"
   explanation unless the re-run still needs it.
4. Report the cap-8 per-turn miss metrics as unstable (n = 13-16) or pool
   them; fix the "smooth" sentence about the sensitivity table; add κ (N3,
   minor 11).
5. Fix the idle-counterfactual reading at cap 8. Add the "no cross-rank
   stretch" counterfactual (own-rank prefill pauses kept, computed inside
   the model) (N4).
6. Present the running-block series as a Little's-law consistency check;
   keep the waiting-count series as the validation (N5). Report the partial
   class (minor 7).
7. Fix the causal-chain sentence (links 3-5), the FCFS tolerance, the
   eviction-order statement, and the provenance of the reviewer-computed
   numbers; add the index assertions (minor 1-5).
8. In the paper (a correction from the measurements, independent of the
   model): reword the hit/miss ratio in abstract l. 98-100, intro l. 179-181
   and §4.3 l. 791-797 so that it is not read as the price of a miss. Say 51
   allocatable blocks (l. 787). Replace "per-rank utilisation" (l. 800-801)
   with the share of time any rank prefills. In docs/testbed.md fix "every
   miss followed a 30 s gap" (49 % in s15), 52 → 51, and the ITL source
   (N6, minor 9).
9. Add memory_model.py to `make exp` and generate its tables and macros
   before any number is quoted in the paper; then add the one- or
   two-sentence §4.3 mention and the App. D table (see "What belongs in the
   paper").
10. Run the decode probe (1-4 above), build the step-level lockstep model,
    and validate it out of sample on E2/E2b with pre-registered metrics.
11. With modelled decode, compute the model-based price of a miss at 50k
    contexts (per-miss counterfactual ΔΣTTFT) and compare it with the
    bracket of `prop:price`.
12. Plan to merge the pool mechanics into libqueuingsim's replay model so
    that §4.2's simulated replica is the validated one.
