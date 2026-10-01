# Review: "Memory as a queue" (research/memory-model.md, scripts/exp/memory_model.py), round 3

Historical review: paths to the former Rust validation crate below refer to
the reviewed snapshot. Current validation is Python/pyserq in `validation/`;
see `research/serq.md` and `research/simulation-design.md`.

Reviewer role: queueing theory / systems, ICML/SIGMETRICS area chair.
Date 2026-09-26. I read my round-2 report, the authors' response
(research/reviews/2026-09-26-memory-round2-response.md), the rewritten
research/memory-model.md, research/testbed.md l. 105-160 (including the uncommitted
diff), scripts/exp/memory_model.py line by line, paper/main.tex (abstract,
intro l. 175-185, §4.3 l. 785-830), scripts/exp/analyze_e2.py l. 222-252, and
the engine: vllm_rbln/v1/core/rbln_scheduler.py (l. 190-470, 470-800, 860-910,
1080-1130) and rbln_kv_cache_manager.py (l. 160-240, 386-520, 540-800), and
upstream vllm/v1/core/{kv_cache_manager (l. 395-475), single_type_kv_cache_manager
(l. 135-225, 495-505), block_pool (l. 185-195, 700-745, 800-818)}.py in
~/vllm-rbln-dynkv/.venv (vLLM 0.26).

Re-runs: every file in data/exp/memory/ (e2, e2b, e2_idle, e2_nocross,
e2_B49..B55; .txt and .json) is reproduced byte for byte, 2 s per run. My
throw-away scripts in the session scratchpad: a copy of the model that records
both queue definitions; an independent check of the nocross decode times; the
observed queue statistic without the 60-request window; FCFS inversions with a
send-gap tolerance; the preemption counters from metrics.jsonl; nocross at
per-token times 0.025 and 0.033 s; and the E1 fit scaled by 1.15 (prefill
stretch). No repository file was changed except this report; the server and
the NPUs were not touched.

## Verdict: accept, as a model of the replica conditional on measured decode

The two engine corrections of round 2 are implemented as the engine does them,
and I found no remaining bug that moves a result. The long-context result is
sound: with the measured decode durations, strict FCFS admission on whole
prompts plus the engine's LRU prefix cache with sub-block copies reproduces
which turns miss (κ 0.98 / 0.99 uncapped and cap 16; 0.93 / 0.73 at cap 8),
the mean TTFT per class, the door waits, and the time-average waiting count on
every congested rank (0.79-0.98 series correlation). It survives a ±2-block
change of the pool in its direction, and a 15 % prefill stretch changes the
long-context aggregates by 0-7 % (below). The short-context saturated arm is
reproduced in its class counts; its TTFT gap has a named candidate (prefill
stretch) that the next step must produce endogenously.

The remaining issues are statements in the documents, not the model: one
comparison uses two different definitions of "arrived to a queue" (R3-1), the
no-cross-rank counterfactual is over-read (R3-2), and a few numbers are
misquoted or unsourced. None changes the conclusion. Fix them before any number
leaves docs/.

## Status of round-2 items

| # | Item | Status | Note |
|---|------|--------|------|
| N1 / 1 | Sub-block copy semantics | **Resolved** | memory_model.py l. 186-211: the source is excluded from the free count (l. 200), the tail is a new block (l. 208), the source goes ownerless to the MRU end on success (l. 209-211) and on a failed match (l. 201-202). This matches `get_computed_blocks_sub_block` (touch at l. 455), `allocate_slots(..., num_new_tokens + num_sub_block_tokens, num_new_computed_tokens=<full-block count>)` (l. 718-738; upstream `_has_partial_local_hit` is false, so no extra CoW block), `release_sub_block_match` (l. 886-890 → l. 507-513) and `release_copy_ops` (l. 1093-1097 → l. 580-585). The engine's cap check (l. 471) and guard B (l. 458-462) come before the lookup, so a head blocked by the cap or by a prefill does not refresh its source; the model's `while` condition (l. 182) has the same order. Statement 2 of the doc is right. |
| N2 / 2 | Only the previous prompt reusable | **Resolved** | Reusable = full prompt blocks + the prompt's tail block if it holds ≥ 512 prompt tokens (l. 279-281). I checked the case the doc does not mention: when the output fills the prompt's tail block, that block gets a full hash that never matches, but `_on_block_cached` indexes all its sub-blocks (rbln_kv_cache_manager.py l. 704-720), so its prompt sub-blocks still match. The model's rule is right in both cases. |
| N3 / 4 | Cap-8 instability; "smooth"; κ | **Resolved** | |
| N4 / 5 | Idle reading; nocross | **Resolved in the code; over-read in the text** | I checked nocross independently: for every turn, modelled D = out × 0.017 + the overlap of its decode with its own rank's prefill intervals (max error 1e-10 s). The versioned events are correct; see R3-2 for the reading. |
| N5 / 6 | Running blocks as a consistency check; partial class | **Resolved** | |
| minor 1 | Causal chain | **Resolved** | links 3-5 |
| minor 2 | FCFS tolerance | **Resolved, explanation wrong** | R3-4 |
| minor 3 | Hashless tail | **Resolved** | l. 284-292 matches block_pool.py l. 719-740 (prepend) up to one token (the engine hashes `num_computed_tokens` = prompt + out − 1) |
| minor 4 | Provenance | **Mostly resolved** | think times and arrive-to-queue shares are printed by memory_model.py; "67, 58, 31, 31 %" is printed by analyze_e2.py (`any_prefill`, macros `\eTwoAnyPf*`) and should be cited as such; "335 of 681" is printed by no script (I reproduced it: misses with think ≥ 29 s in s15_base) |
| minor 5 | Index assertions | **Resolved** | l. 92-93; I also checked that every session's first send is within 0.1 s of t0 + i·spacing in all 12 runs and that no prompt is shorter than the previous one |
| minor 6 | Preemption caveat | **Resolved**, see R3-6 | logged 4 / 1 / 1 / 0 confirmed from `vllm:num_preemptions` |
| minor 8, 10 | Chunked allocation; prefill stretch | **Resolved** | the stretch range differs between the two docs (R3-7) |
| minor 9 | testbed.md | **Resolved, one overstatement** | R3-8 |
| 8 | Paper corrections | **Done in v0.14** | §4.3 now says the ratio "is not the price of a miss", 51 allocatable blocks, and the any-rank prefill share. The "Note on the paper" in memory-model.md still says the opposite (R3-5). |
| 9-12 | make exp, probe, price at 50k, libqueuingsim | open | below |

## Remaining issues (all minor)

### R3-1. "Arrived to a queue" is defined differently for the observed and the model turns

Observed (l. 412, same as analyze_e2.py, and the paper's `\eTwoMissQueue*`):
another request of the rank was sent earlier and had not *started* its
prefill (start = first token − P_E1). Model (l. 170): `len(rk.queue) > 0 or
rk.pf_until > t`, i.e. waiting **or a prefill in progress**. The doc then puts
the two side by side ("92-100 % of misses and 2-4 % of hits ... (model: 95-100 %
and 6-9 %)"). With one definition for both:

| E2 run | waiting only: obs / model, misses | hits | waiting or prefilling: obs / model, misses | hits |
|---|---|---|---|---|
| s20c0 | 1.00 / 0.99 | 0.03 / 0.00 | 1.00 / 1.00 | 0.10 / 0.09 |
| s20c16 | 0.99 / 0.98 | 0.02 / 0.00 | 1.00 / 1.00 | 0.07 / 0.07 |
| s20c8 | 1.00 / 0.95 | 0.03 / 0.00 | 1.00 / 0.95 | 0.09 / 0.08 |
| s10c8 | 0.92 / 0.70 | 0.04 / 0.00 | 1.00 / 1.00 | 0.06 / 0.06 |

(Observed by observed class, model by model class, as the script does.) The
agreement is better than the doc says under the inclusive definition, and the
model's hits never arrive to a waiting queue under the strict one. Either
definition is fine; use one. Also note in passing that the observed start uses
the unstretched E1 time, so it is slightly late.

The 60-request window (l. 412) changes nothing: I recomputed without it and
0 of all turns in 12 runs change. Drop it or assert it.

### R3-2. The nocross counterfactual does not isolate the cross-rank stretch

`nocross` = out × 0.017 s + own-rank prefill pauses. The measured D differs
from it by two things, not one: the cross-rank stalls and the dependence of
the decode step time on batch size and resident context (my in-sample
regression in round 2 gave a base per-token time of 0.029-0.037 s, about twice
the idle 0.017). Re-running nocross with a larger per-token time:

| per-token s | s20 no cap | s20 cap 16 | s20 cap 8 | s10 cap 8 |
|---|---|---|---|---|
| 0.017 (doc) | 48.0 (111) | 41.1 (98) | 13.8 (47) | 13.2 (42) |
| 0.025 | 58.0 (122) | 47.4 (99) | 14.3 (43) | 13.2 (40) |
| 0.033 | 69.4 (121) | 52.6 (99) | 14.5 (42) | 13.6 (38) |

So about a quarter of the gap between nocross and measured (48 → 136 s
uncapped) may be step time under load, not cross-rank stall. Replace "the
cross-rank stretch carries most of the memory pressure" with "decode time
beyond the idle per-token time and the own-rank pauses carries most of the
memory pressure; the decode probe splits it into cross-rank stalls and
t_dec(b, K)". The same caution applies to the paper sentence (§4.3 l. 822-825)
"The pool binds because running turns hold their blocks through stretched
decodes": the model supports the "because stretched decodes" part (conditional
on measured D, idle decode gives 39.5 against 136.2 s), not yet the share of
the stretch that comes from other ranks' prefills.

### R3-3. Misquoted numbers in memory-model.md

- "Mean hit TTFT differs by −0.7 to +0.9 s": it is −0.85 (s20c8) to +0.69
  (s10c8), i.e. −0.9 to +0.7.
- "Misses per rank ... 49/48, 25/25, 88/91 on ranks 1-3" and "the forced arms
  give 341/364, 348/370, 192/192" are model/observed; the table and the rest of
  the section are observed/model. Use one order.
- "the 0.1-0.3 s gap is the frontend offset" for the light base arms: the gaps
  are 0.13, 0.09, 0.08 s (the forced arms 0.3 s).
- The script's docstring (l. 27-33) still says decode is observed or idle and
  that "the prefix a session can reuse is its previous prompt plus completion".
  Both are out of date.

### R3-4. FCFS inversions in the short-context replays are real, not only jitter

With no tolerance the doc's counts are right (0-1 long context, 9-65 short).
But counting only overtakes by a request sent more than 0.5 s later, s15_base
still has 32 (from 10 distinct overtaken requests, one of them overtaken by six
requests sent up to 5.9 s later, TTFT 10.1 s against 3.6-4.8 s), the light and
forced arms 0-12, the long-context runs 0-1. "Where prefills take a fraction of
a second" explains jitter among near-simultaneous sends, not a 6 s overtake. I
could not find the mechanism in the code paths above (no preemption was logged
in s15; 9 of the 10 overtaken turns were sub-block hits, against 61 % of all
turns). Report the count with the tolerance, say the model assumes strict FCFS,
and list it as an unexplained engine behaviour at saturation. It does not
affect E2.

### R3-5. "Note on the paper" is stale

memory-model.md l. 209-216 says §4.3 reads the ratio as what a miss costs,
says 52 blocks and quotes only per-rank utilisation. v0.14 fixed all three
(l. 787-797, 810-825). Rewrite the note to what is still open: (i) the
"because" sentence (R3-2); (ii) the abstract's "and lose their prefixes while
they wait" rests, quantitatively, on the model (88-96 % of non-hits resident at
send). The measurements alone show only that misses arrived to a queue after
ordinary think times. That is a strong inference but not an observation. Once
the model enters the paper (below), §4.3 can give that share as a model
number. Until then the abstract clause should read as an inference from the
engine's admission rule.

### R3-6. Preemptions

The model now counts 8 / 7 against 4 / 1 logged (uncapped, cap 16); in round 2
it was 6 / 1. The reason is structural: a failed growth frees nothing in the
model, while one engine preemption releases a whole 50k-token request (13
blocks) and re-queues it at the head, so later growths succeed. Say that the
count is an upper bound and not comparable one to one.

### R3-7. Prefill stretch: one range, one source, and it is the s15 remainder

memory-model.md says 1.07-1.23×, research/testbed.md l. 157 says 1.10-1.23×. Give
one range and the script that prints it. The sensitivity is worth one line in
the doc. With the E1 fit scaled by 1.15:

| run | misses obs / model (E1 → ×1.15) | mean TTFT obs / model (E1 → ×1.15) | κ |
|---|---|---|---|
| s20c0 | 164 / 162 → 165 | 134.5 / 136.2 → 142.0 | 0.98 → 0.98 |
| s20c16 | 123 / 123 → 121 | 67.1 / 66.3 → 71.6 | 0.99 → 0.98 |
| s15_base | 681 / 631 → 679 | 6.7 / 5.4 → 6.8 | 0.80 → 0.81 |

The long-context result is insensitive to it. The s15 gap closes. This is
in-sample and must not be adopted as a fitted factor. It is a prediction the
lockstep model should reproduce without being told (see the plan below; s15
stays held out).

### R3-8. research/testbed.md (uncommitted diff) overstates the s15 mechanism

"about half the misses followed a 29-30 s gap; the rest arrived to a queue and
lost their prefix while waiting". In the model only 39 % of s15 non-hits had
their prefix resident at send (88-96 % in E2). Replace "the rest ... lost their
prefix while waiting" with "91 % arrived to a queue", and move the
lost-while-waiting mechanism to the long-context replay, where the model
supports it.

### R3-9. Approximations to name once (no action on the code)

- A stale copy source is ownerless in the model and never matches. In the
  engine it keeps its sub-block hashes, so it can serve a match if the newer
  copy was evicted first. That is rare because the source is freed earlier and
  sits ahead of the newer copy in LRU order.
- `longest_match` picks an arbitrary block among equal-depth holders. The newer
  copy wins whenever the query goes deeper than the stale one, which holds for a
  growing prompt.
- Sessions do not share prefixes (first turns show 0-1 of 37 cached; E2b ids
  are salted), so per-session reuse is enough.

## What may be said, and where

AGENTS.md rule 7: simulator output is not a measurement. As written, it enters
the paper only through paper/simulation.tex with numbers generated by
libqueuingsim into paper/sim/. memory_model.py is a second, trace-driven
simulator with measured inputs. The rule has no slot for it. Adding one is the
user's decision, not the agents'.

**docs/ (now, after R3-1 to R3-8):** everything in memory-model.md, scoped as
it is: "a replica model given the measured decode durations reproduces ...".
Keep the circularity sentence.

**Paper, §4.3, one or two sentences (only after (a) the user amends rule 7 to
admit `paper/exp/macros-memory.tex` and `tab-memory.tex` generated by
`make exp` from memory_model.py, labelled as model output, and (b) that target
exists):** after "The wait is for KV blocks", for example:
"A replica model that adds the engine's block pool (admission in arrival order
when the whole prompt fits, LRU prefix cache with sub-block copies) to the
fitted prefill cost, and takes the measured decode durations as input,
reproduces which turns miss (κ \mem... uncapped and at 16) and the mean TTFT of
each class (App. D); in it \mem...-\mem...\,% of the misses had their prefix
resident when sent." What may be claimed: the block pool plus FCFS
reproduces the class of each turn and the per-class means given decode, and the
misses lost their prefixes while they waited. What may not be claimed: that the
model explains the waits unconditionally, what share of the stretch comes from
cross-rank stalls (R3-2), turn-level miss metrics at cap 8, or that the
saturated short-context arm is reproduced beyond its class counts. Not in the
abstract or intro; no proposition, no Lean.

**Appendix D:** one generated table per E2 run (class counts and mean TTFT,
observed / "model, measured decode"; κ; door wait; waiting count per congested
rank) and the waiting-count series as a generated figure. The E2b rows can go
in the same table with the saturated arm's rank-level under-prediction stated
in the caption.

**If rule 7 is not amended:** nothing from the model in the paper. The route is
action 12 (port the pool mechanics into libqueuingsim's replay model and
report it in §4.2, where the "simulated replica" should be the validated one).

## The decode-stretch step: confirmed, with refinements

The round-2 plan stands: probe on an idle server, then a step-level lockstep
model, then an out-of-sample test. Refinements from this round:

**Probe (idle server, no replay data; per the testbed runbook):**
1. Single-rank decode step time t_dec against batch and context. The server
   compiles only decode buckets 1, 4 and 8 (serve_m27.sh l. 18), so use
   b ∈ {1, 2, 3, 4, 5, 8}, to test whether step time depends on the bucket or
   on b. Use per-request contexts {2k, 12k, 50k, 90k} and one mixed batch per b,
   to test whether ΣK or max K matters. Fixed out = 256, ignore_eos, 3 repeats,
   other ranks idle (dummy steps).
2. All four ranks decoding: the same (b, K) on all ranks, and unequal
   (b_r, K_r). This tests the lockstep max rule. With EP it also tests whether
   step time depends on the total tokens across ranks rather than the per-rank
   maximum.
3. Peer prefill: one rank decodes (b, K) while a peer prefills a prompt at
   K′ ∈ {0, 12k, 50k, 90k}. The decoding rank's ITL during the prefill should
   equal the peer's 512-token chunk time P(512, K′). Measure the peer's prefill
   time too; this is the prefill stretch (R3-7) measured directly.
4. Own-rank prefill: decode stalls for the whole prefill (guard D).
5. Sanity values, not fit: 0.017 s idle, 0.10 s with a peer prefilling,
   0.17-0.25 s with own prefills pending (read off the replays).

**Model:** one clock for all ranks. Each step lasts the maximum over ranks of
that rank's phase time: the chunk time P(512, K) if it prefills, else
t_dec(bucket(b_r), K_r) from the probe, else the idle step. A prefilling rank
decodes nothing. The others advance each running request by one token.
Prefill chunks get the same max, so the prefill stretch is endogenous. Growth
and preemption happen at step granularity, and a preemption frees the victim
(this fixes R3-6). The only new inputs are probe fits. Keep the observed-D mode
as a switch for comparison.

**Pre-registered validation:** before the first run on E2/E2b, commit a
section to memory-model.md with the date and git hash. It lists the metrics,
the thresholds and the held-out runs. Do not iterate on the held-out runs.
- held out: s10c8 and s15_base (neither may be looked at while the model is
  built);
- decode: per-turn D median relative error per rank ≤ 0.25; mean ITL per run
  and makespan per run within 10 %;
- end-to-end: miss count within 15 %, mean TTFT per class within 25 %, κ,
  waiting-count means on congested ranks, on the uncapped and cap-16 runs;
  cap-8 runs judged on aggregates only (mean TTFT, which rank misses);
- s15_base: the class counts and mean TTFT within the same bounds, without any
  prefill-stretch factor (R3-7 says the stretch alone would do it; the model has
  to produce it from the step rule);
- report failures as failures. No parameter may be taken from E2/E2b; if the
  probe's functional form fails, change it with a new probe, not with a fit to
  the replays.

Only then compute the model-based price of a miss at 50k contexts (per-miss
counterfactual ΔΣTTFT, the prefix forced resident or evicted) and compare it
with the bracket of `prop:price`.

## Final action list

1. Use one definition of "arrived to a queue" for observed and model turns and
   requote (R3-1); drop or assert the 60-request window.
2. Reword the nocross reading in memory-model.md, and flag the paper's
   "because" sentence as covering stretched decodes, not their cross-rank share
   (R3-2).
3. Fix the misquotes and the docstring (R3-3).
4. Report FCFS inversions with a 0.5 s send-gap tolerance; name the s15
   overtakes as unexplained (R3-4).
5. Rewrite "Note on the paper" to the two open points (R3-5).
6. Call the model's preemption count an upper bound (R3-6).
7. One prefill-stretch range with its source; add the ×1.15 sensitivity line
   (R3-7).
8. research/testbed.md: replace "the rest ... lost their prefix while waiting"
   for s15 (R3-8); put the "335 of 681" computation in a script.
9. Name the approximations of R3-9 once in the caveats.
10. Ask the user whether rule 7 of AGENTS.md should admit model output from
    `make exp` (memory_model.py → `paper/exp/macros-memory.tex`,
    `tab-memory.tex`). If yes, add the target and then the §4.3 sentence and
    the App. D table as above. If no, keep it in docs/ until action 12.
11. Run the decode probe (items 1-5), build the lockstep step model, and
    pre-register and run the out-of-sample validation as above.
12. After 11: the model-based price of a miss at 50k contexts; then merge the
    pool and step mechanics into libqueuingsim's replay model.
