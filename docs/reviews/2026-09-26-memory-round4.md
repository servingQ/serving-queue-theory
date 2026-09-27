# Review: the decode-stretch step (docs/memory-model.md "Pre-registration" to end), round 4

Reviewer role: queueing theory / systems, ICML/SIGMETRICS area chair.
Date 2026-09-26 (read 22:40-23:30 KST; system clock 22:52 when I first
listed the files). I read docs/memory-model.md from "Pre-registration" to
the end, scripts/exp/probe_decode.py, analyze_decode.py and lockstep_model.py
line by line (with memory_model.py, which it imports), data/exp/decode/*
(probes.jsonl, probe.log, summary.json, fit_v1.json, fit_v2.json),
data/exp/lockstep/*, my round-3 report, and the engine:
vllm_rbln/v1/core/rbln_scheduler.py l. 180-470, 640-680, 725-760, 855-900,
vllm_rbln/v1/worker/dp_utils.py (all), and upstream
vllm/v1/core/sched/scheduler.py `_preempt_request` (l. 1215-1235).

Re-runs: `analyze_decode.py --form v2` reproduces fit_v2.json exactly;
`lockstep_model.py` with fit_v1.json and fit_v2.json reproduces all four
data/exp/lockstep/*.txt byte for byte. Throw-away scripts in the session
scratchpad: a copy of lockstep_model.py with switches (c0 as latency instead of
step time, stretch linear/flat/none, 512-token padding of partial chunks,
multiplicative lognormal step noise with a seed); a per-token decode
comparison; metric 1 without the D > 0.5 s filter; the registered max rule
fitted on probes A+B only. No repository file was changed except this report.
The server was not touched. Probe G ran on the server while I reviewed (started
22:51 by the authors, 60 records in probes.jsonl when I finished). I read its
records but did not run anything against the server.

**Disclosure that matters for the next step.** My diagnostic runs below were
done on s15_base and the long-context runs after v2 was seen. Together with
the authors' own v2 run, they spend s15_base as a hold-out. No variant of the
model can be validated on s15_base any more (M5).

## Verdict: the pre-registered validation failed, and the write-up must say more exactly what failed. v2 stays in docs/ as a post hoc model of the long-context regime. Only the probe measurements may enter the paper.

The authors did the most important thing right. They registered thresholds,
ran the model, and reported a failure as a failure. They did not tune
anything on the replays. Every step-model parameter reproduces from
probes.jsonl, and lockstep_model.py reads nothing from E2/E2b except arrivals,
think times, token counts, rank pins and forced-miss flags. The probes are
good measurements. Streamed chunks equal completion tokens in 348 of 354
records (the other 6 miss one or two), and window length divided by tokens
equals the median gap to within 1 %. So chunk times do measure engine steps
here.

Five things are wrong or missing, and they change what the section may claim:

1. v1 as run did not implement the registered model family. It sums contexts
   and buckets over ranks, but the registration says "a step's duration is the
   maximum over ranks of the rank's own step". The failure the section
   reports is therefore the failure of a deviation. The registered family,
   fitted on the registered probes A+B only, passes the long-context criteria
   and fails s15 (M1). The authors do not state this. They should, and they
   should not claim it as a pre-registered pass either.
2. The record of the registration cannot be verified, and part of it is wrong.
   The file is untracked, so there is no commit. The later section timestamps
   do not match the file times ("23:20 KST" is later than the clock when I
   checked, 22:52). memory_model.py was changed after registration without
   disclosure: its registered hash does not match, and the metric-1 code with
   its D > 0.5 s filter was added then (M2).
3. The v2 summary overstates. Criterion 2 (misses) fails in 2 of 4
   long-context runs. "Within 2 % in the two runs with enough misses to count"
   narrows the criterion after the fact. The per-turn decode in every
   short-context arm is poor (Spearman 0.13-0.26, MRE 0.48-0.70), and the
   section omits it (M3).
4. lockstep_model.py charges the frontend constant c0 as lockstep engine time
   on every first chunk. Probe C refutes this (M4). Three other unmeasured
   pieces also matter at saturation: partial-chunk cost, the decode graph
   while a peer prefills, and the stretch at k > 2.
5. At saturation s15 is a sensitivity amplifier. Each of the unmeasured
   pieces, and 2 % step noise, moves misses by 150-400 and mean TTFT by
   3-8 s. Probe G's data, already on disk, show that the linear stretch
   extrapolation is about right for short prompts. **Probe G does not settle
   s15** (M5).

## Major issues

### M1. v1 deviated from the registered family. The registered family, fitted on pre-registration data, fits the long-context runs.

The registration: "the ranks advance in lockstep steps; a step's duration is
the maximum over ranks of the rank's own step: a decode step τ(b, ΣK) of the
batch it holds". My round-3 specification said the same ("each step lasts the
maximum over ranks of that rank's phase time").
`fit_step_model` (v1) instead fits `α + β Σ_r bucket(b_r) + γ Σ_r ΣK_r` and
chooses it by cross-validation. The data cannot tell the two apart: in probe
B only rank 1 carries load, and it carries small contexts. The section itself
concedes this ("the probe cannot tell a sum from a maximum"). A rule that the
registration had already fixed was thus replaced by a fitted choice that the
data could not identify. That is a deviation, and it is not disclosed.

The engine settles the bucket part without any probe. dp_utils.py l. 244
(route AGREED): `num_reqs_padded = cfg.find_bucket(max(status.num_reqs[i]
for i in busy))`. All ranks pad to the bucket of the busiest rank, which is a
max, not a sum. Attention is rank-local. Reading this file before
registration would have ruled out v1's form.

What the registered family gives (my scratchpad; post hoc, because I ran it
after seeing everything): `τ = α + β max_r bucket(b_r) + γ max_r ΣK_r`,
fitted on A+B only (LOCO MAPE 0.053, α 0.01433, β 0.000958, γ 1.097e-7),
predicts probe F within 0-15 % (under by 5-15 % at 4 ranks). v1 predicted
92 ms against 37 ms measured. In the lockstep model:

| run | misses obs / model | mean TTFT obs / model (s) | κ | decode MRE, ρ |
|-----|--------------------|---------------------------|---|---------------|
| s10c8* | 13 / 14 | 11.1 / 11.2 | 0.97 | 0.03, 0.99 |
| s20c0 | 164 / 163 | 134.5 / 133.8 | 0.96 | 0.16, 0.95 |
| s20c16 | 123 / 121 | 67.1 / 66.1 | 0.99 | 0.05, 0.98 |
| s20c8 | 16 / 17 | 11.5 / 10.8 | 0.82 | 0.04, 0.98 |
| s15_base* | 681 / 1010 (+48 %) | 6.7 / 15.5 | 0.40 | 0.78, 0.23 |

This clears criteria 1-3 in all four long-context runs and fails criterion 4.
It does better than v2 on s10c8 and s20c8. Neither F nor the δ term is needed
for the long-context result. The honest account is this:

- v1 as run was not the registered model, and it failed.
- The registered family on registered data would have passed criteria 1-3 and
  failed criterion 4. This was computed after the fact by the reviewer, so it
  is not a pre-registered pass.
- v2 adds F and δ. Its long-context agreement is no better, and it also fails
  s15.

A consequence: the long-context runs are insensitive to how the decode step
is written within the max family (maxAB, maxABF, v2 agree to a few percent),
but sensitive to its level (v1 is 30-40 % slow and fails). They test the
decode clock to about ±10 %, and they test the memory chain given that clock.
They do not test the prefill side of the lockstep (M5 table: s20c0 misses stay
161-166 under every prefill-side variant).

### M2. The registration record cannot be verified, and it changed after the probes

- docs/memory-model.md is untracked (`??` in git status). Round 3 asked for "a
  section committed with the date and git hash" before the first run. Nothing
  was committed, so the 22:10 registration time rests on the authors' word.
  probes.jsonl carries only perf_counter-relative times and no wall clock.
- The file times support the order of events (probes A-E take about 22 min by
  the sum of run lengths and pauses; v1 outputs at 22:36:18; F about 13 min;
  fit_v1.json and fit_v2.json both at 22:50:54; v2 outputs at 22:50-22:51).
  They contradict the section headers: "Result ... (v1, 22:50 KST)" was
  written after 22:36, and "Probe F and model v2 (post hoc, 23:20 KST)" is a
  time that had not yet come when the files existed. Use times from `date` or
  from git, not estimates.
- The registration names memory_model.py sha256 prefix 53732fb2071ab33e. The
  current file is 1e256bd8ca12e198, modified 22:36:18, after probes A-E. The
  change added the metric-1 code, which includes a filter the registration
  does not name: only turns with measured decode D > 0.5 s count. Without the
  filter, v1 on s20c0 gives MRE 0.41, not 0.33, and s20c16 gives 0.54, not
  0.39. The filter did not change the verdict (v1 fails either way), but it
  made the registered model look better, and it was chosen after the data.
  Disclose it and report both numbers.
- fit_v1.json is a regeneration at 22:50:54, not the file v1 ran with (that
  was "fit.json", now gone). It reproduces v1's outputs byte for byte, because
  v1 reads only A, B and E and those rows are unchanged. Say so.
- Compared with round 3, the registered thresholds are looser. Round 3 asked
  for decode MRE per rank ≤ 0.25, makespan and ITL within 10 %, misses within
  15 %, TTFT per class within 25 %, and cap-8 runs judged on aggregates only.
  The authors registered MRE ≤ 0.35 per run, TTFT over all turns within 30 %,
  misses within 25 % in every run, and no makespan or waiting-count metric.
  Authors may register what they like, but the change should be named.
- The registered probe also omitted round-3 probe items 1 and 2: contexts
  {2k, 12k, 50k, 90k} with a mixed batch per b, and all four ranks decoding
  equal and unequal (b_r, K_r). Probe F is item 2. So F was not chosen only
  because the replays failed; the reviewer had asked for it before any data
  existed. That makes F more legitimate. It also means the registered probe
  departed from the agreed design, and that should be stated.

### M3. The v2 summary overstates the agreement

- Criterion 2 (misses within ±25 %) fails for v2 in s10c8 (7 / 13, held out)
  and s20c8 (22 / 16). The table marks both with ✗, but the prose says the
  model "reproduces the long-context replays" and "mean TTFT within 2 % in the
  two runs with enough misses to count". The second phrase narrows a
  registered criterion after the fact. (The v1 table's result column also
  names only cap 8, yet s10c8 fails too: 7 / 13.)
- Small counts are noisy, which is a fair point but belongs in the next
  registration. With 2 % lognormal step noise (10 seeds), v2's s20c8 misses
  range over 15-22. The observed 16 lies inside, so the ✗ there is within the
  model's own noise, and a pass would have been luck too. s10c8 gives 7 in
  every seed: a systematic undercount. Register counts below about 30 as
  intervals from an ensemble, not as ±25 %.
- Miss turns are what the paper is about. In s10c8, miss-turn TTFT is 142 s
  observed against 62 s in the model (MRE 0.92, ρ −0.18). In s20c8 the MRE
  is 0.25.
- Short-context arms: the section says "the light arms are reproduced" (TTFT,
  κ). It omits that per-turn decode duration fails in every short-context arm
  under v2: MRE 0.48-0.70, Spearman 0.13-0.26 (s25_base 0.63 / 0.13, s35_base
  0.63 / 0.24, s50_base 0.48 / 0.26, s25_m10 0.66 / 0.17). The median output
  there is 4 tokens, so a turn's decode time is almost entirely lockstep
  interference, the very mechanism the model claims. Per token: s25_base
  0.122 s observed against 0.152 model (median); s35_base 0.081 / 0.087; s15
  1.15 / 1.85. Light-arm TTFT (0.5-0.7 s) is about one E1 prefill, which any
  model matches, so it is weak evidence.
- "... and so explains the chain that v0 took as data" is too strong for a
  post hoc model that fails its registered criteria. Write "is consistent with".
  The step that carries the chain (cross-rank stretch → longer block holding →
  pool binds) has not been isolated. The counterfactual would be the same
  model with the cross-rank coupling off: each rank's step is its own, and
  prefill pauses only its own rank. Show it before saying "explains".

### M4. lockstep_model.py charges the frontend constant as lockstep engine time

`ct = a*m + b*m*(off + m/2) + (c0 if p["first"] else 0.0)`, and the step lasts
the maximum over ranks. So every first chunk stalls all four ranks for
c0 = 44 ms. But E1's P(n, K) is client-side TTFT (probe_prefill.py
`stream_ttft`), and c0 is the intercept of that fit: HTTP, frontend and output
path. Probe C shows that c0 is not engine time. With a peer prefilling 8192
tokens, the decoding rank's largest gap is 0.12 s. The model predicts a first
chunk of 0.099 + 0.044 = 0.143 s. The observed 0.12 s equals the last chunk at
offset 7.7k (0.126 s). At 32k the largest gap, 0.21 s, equals the last chunk
alone (0.0993 + 6.51e-9·512·32512 = 0.208 s). So no c0 spike reaches the peer.
In the short-context arms there are about 0.9 prefills per second per rank,
so the model adds about 4 × 0.041 ≈ 16 % of wall time that the engine does
not spend. c0 should be a latency added to the first token, not step time.
This correction comes from probe C, which is registered data, not from s15.
Adopt it on that ground, and freeze it before any new test.

Other items in the step accounting, in decreasing order of effect:

- **Partial chunks.** They cost a·m with no per-step floor. E1 has no n < 512
  and no n that is not a multiple of 512. The decode step's α ≈ 14 ms
  suggests a fixed per-step cost that a·m misses for small m. In s15, 18 % of
  prefills have n < 512, and every prefill ends with a partial chunk. Whether
  RBLN pads a prefill chunk to a compiled 512 is not established. Padding
  everything to 512 moves s15 by +95 misses (M5 table).
- **Decode while a peer prefills.** It is costed as τ(own bucket). The engine
  takes route ANY_PREFILL (dp_utils.py l. 206-216): decoding ranks run the top
  bucket (8) with the token dimension padded to `max_num_tokens`. Probe C
  measured this only for one 16k request (bucket 1). max(chunk, τ) hides it
  while chunks are 0.1-0.2 s, but it has not been measured for 8 × 50k.
- **Stretch on top of the max.** The multiplicative stretch is applied on top
  of the max over ranks' chunks. In probe E, rank 1 is 0.3 s ahead at larger
  offsets, so part of the measured 1.10 is already that max. By E1 the
  offset effect is about 3 points of the 10, so there is a small double count.
  The E and G ratios also include the unstretched c0 in the denominator. That
  is negligible at 16k but not at 2k (M5).
- **Preemption.** The model does not block admission in a preempting step (the
  engine skips the waiting loop when `preempted_reqs` is non-empty,
  rbln_scheduler.py l. 458-462). A self-preempted request keeps the `gen += 1`
  of a token it never computed, and a re-prefill emits no token. With 0-5
  preemptions per run this is immaterial. Otherwise preemption matches
  upstream: FCFS `self.running.pop()` (l. 380), `num_computed_tokens = 0`, and
  `waiting.prepend_request`.
- **Checked and correct.** A prefilling rank decodes nothing (guards A-D,
  l. 199-205, 861-884, and probe D). The first token comes at the end of the
  last chunk's step. One prefill at a time per rank, admitted with priority
  over decode. `len(run) >= max_seqs` matches `len(self.running) ==
  max_num_running_reqs`. Events are taken at step boundaries, which is when
  the engine next schedules. Idle jumps are correct. A request larger than the
  pool would sit in the queue forever, and `unfinished` would show it; it is 0
  everywhere.
- **Stale text.** The docstring still gives the Σ form and
  "data/exp/decode/fit.json". The "Omissions and caveats" list still has the
  decode stretch as future work and "Preempted requests are counted, not
  re-executed", which is no longer true of lockstep_model.py.

### M5. s15 at saturation: what the failure means, and why probe G does not settle it

**s15 amplifies small capacity errors.** Per-rank prefill work is balanced
(cold chunks 11002-11224 per rank), yet the observed congested rank is r0
(11.8 s, 269 misses) while v2 congests r2 and r3. With 2 % step noise the
congested rank changes from seed to seed (r3; r0 and r3; r1 and r3; ...).
Which rank tips into thrashing depends on the path, so per-rank agreement
cannot be asked of s15. The aggregate gap, by contrast, is systematic. Over
10 noise seeds v2 gives 840-1045 misses (observed 681) and mean TTFT
12.2-16.9 s (observed 6.7).

**Every unmeasured piece moves s15 by about as much as the gap.** v2, my
scratchpad switches, one run each:

| variant (post hoc diagnostics, not candidates) | s15 misses (obs 681) | s15 TTFT (obs 6.7) | s20c0 misses (obs 164) | s20c8 misses (obs 16) |
|---|---|---|---|---|
| v2 as is | 968 | 14.1 | 161 | 22 |
| c0 as latency (probe C) | 789 | 9.5 | 165 | 18 |
| stretch flat 1.10 for k ≥ 2 | 807 | 9.4 | 161 | 22 |
| no stretch | 615 | 5.6 | 166 | 16 |
| c0 as latency + flat stretch | 518 | 4.1 | 165 | 18 |
| partial chunks padded to 512 | 1063 | 17.3 | 166 | 18 |
| padded + c0 as latency | 877 | 11.6 | 166 | 18 |

The long-context columns barely move. The s15 columns span 518-1063 misses.
A model that "passes" s15 by picking one of these rows would be fitted to s15.

**What the saturated regime is.** The observed decode time per token in s15 is
1.15 s (median), against 0.12 s in s25 and 0.017 s idle. That is not one
token per peer chunk (0.1-0.2 s). It is decode starved by the own rank's
successive prefills: prefill has priority (guard D), the queue never empties,
and decodes advance only when admission stops at 8 running. The model has the
same mechanism and overstates it: 1.85 s per token, or 1.30 s with c0 as
latency. This is a clean, turn-level target that does not go through the
memory chain. Use it when localizing the error.

**Probe G, as run.** The data are on disk (60 records; not yet in the doc).
Ratios below are rank 0's prefill time over its solo time, both reps. The
second column removes c0 from both terms.

| rank 0 / peers | k = 2 | k = 3 | k = 4 | linear model (1.096 per rank) |
|---|---|---|---|---|
| 16k / 32k | 1.08 | 1.13 | 1.19 | 1.10, 1.19, 1.29 |
| 2k / 4k (c0 removed) | 1.11 (1.12) | 1.18 (1.20) | 1.25 (1.28) | same |
| 4k / 4k (partial overlap) | 1.08 | 1.13 | 1.20 | same |

For short prompts, the regime of s15, the linear extrapolation is about
right. For long prompts it is about 8 % high at k = 4. **G therefore removes
one candidate but does not explain s15.** Replacing the stretch with G's
values would change s15 far less than the c0 correction does. Design
problems in G: rank 0 starts 0.2 s after its peers, so in 4k/4k its last
0.2 s runs alone. `overlap` is computed and not used, and
`peers_done_before` is recorded but never reported. G does not measure the
"per-request overhead of many short prompts" that the doc announces. Only
short appends at an offset can measure that (G-bis below).

**What would settle it.** Measure the step, not the outcome.
(a) An engine-side step log during a replay: per step, wall time, per-rank
phase, tokens and requests. This could be a scheduler-output hook or the
engine's iteration stats, enabled for one run. The lockstep model is a
step-level claim, and it can then be validated step by step: step-duration
distribution by (phases across ranks), share of steps with k ranks
prefilling, running count per rank. This localizes the s15 error without
touching the end-to-end metrics.
(b) Probe G-bis for short appends. While rank 1 decodes 1 × 2k as an observer,
rank 0 runs a back-to-back burst of 20 appends with m ∈ {64, 128, 256, 512}
at offsets {2k, 8k}. The observer's gaps give the engine time of a partial
chunk, including any per-request engine overhead. TTFT minus that gives the
frontend part of c0.
(c) ANY_PREFILL decode cost: 8 × 16k and 3 × 50k decoding on rank 1 while
rank 0 prefills 32k.
(d) A new held-out saturated replay (a new trace seed at spacing 1.5 s, or
spacings 1.25 and 1.75 s), registered with the model frozen by a committed
hash, and with ensemble prediction intervals (step noise, think-time jitter)
as the thresholds.

## Minor issues

- m1. **Seed contamination.** A K=2048 b=1 rep 0 has `cached_tokens` 1536 (a
  smoke test reused seed 0). Its first token came at 0.11 s against 0.44 s in
  rep 1. Its decode step is unaffected (0.0160 against 0.0163), and it enters
  no prefill figure. It still breaks the registered "unique prompts, no prefix
  hits". The rng is sequential, so any rerun with the same seed replays every
  earlier prompt in order. That is harmless for decode windows and fatal for
  E and G timings. Disclose it. Add a nonce, or a wall-clock seed, and an
  assertion `cached_tokens == 0` in analyze_decode.py. (E: all 0. F used
  seed 1 and G seed 2: all 0.)
- m2. **Order and drift.** Configurations run in a fixed order, and rep 1 of A
  at 16k, b = 2-4 is consistently about 5 % slower than rep 0 (0.0206/0.0218,
  0.0230/0.0243, 0.0243/0.0255). δ (0.9 ms per active rank, 8-13 % of a step
  at 4 ranks) is identified mostly from F against A, which ran 20-40 min
  apart. It could partly be drift. Randomize the order, and repeat a reference
  configuration (A 16k b=4) at the start and end of each block.
- m3. **The form search is not in the repository.** "Seven forms" (v1) and
  "six forms" (v2) with their CV MAPEs cannot be reproduced; analyze_decode.py
  fits only the chosen form. Commit the list and the LOCO scores. (Mine: max
  rule without δ on A+B+F 0.055, with δ 0.044, A+B only 0.053.)
- m4. **Coverage.** b = 6, 7 were not probed (bucket 8, assumed flat). Per-rank
  ΣK in the replays reaches the pool (up to about 200k); probes reach 150k
  (3 × 50k) and 131k (8 × 16k). Probes C, D and E have one decoding request
  each and 2 reps.
- m5. The v1 table's "result" column for criterion 2 omits s10c8 (M3). The
  v1 paragraph's "28-43 % too long in every run" is a model/observed ratio of
  means; say so.
- m6. Paper consistency (outside this step, flagging once): Table 1's row
  "Prefill: FIFO queue served from the token budget the decode batch leaves"
  (main.tex l. 233) says the opposite of l. 907 ("decode gets what prefill
  leaves") and of guard D. On this engine, decode gets what prefill leaves.
  §4.3 l. 817 asserts "the ranks step in lockstep" with no measurement behind
  it. Probe C and D can now carry it (below).

## Answers to the five questions

1. **Pre-registration.** Honoured in spirit: thresholds fixed first, no replay
   parameters, failure reported. Not honoured in the letter:
   - v1 implemented a rule the registration had fixed otherwise (M1);
   - the analysis code changed after the probes, with an unregistered filter
     (M2);
   - the record is uncommitted and some of its timestamps are wrong (M2);
   - the registered probe omitted the round-3 item that became F.

   Is v2 legitimate? The form change rests on new probe data (F: 36-37 ms
   against v1's 92 ms) and on engine code (AGREED pads to the max bucket). It
   was not fitted to the replays. But the decision to look, the direction
   (decode too slow), and the new δ term, which lies outside the registered
   family, were all informed by the replay failure. Disclose it as "a
   replay-motivated probe; the form returns to the registered max rule plus
   one new term". The registered max rule on A+B alone already fits the long
   runs (M1). That weakens the case for δ and strengthens the case that the
   chain holds for any max-rule clock.
2. **Probe quality.**
   - Windows are right (after the last first token, before the first
     completion, rank-0 gaps).
   - Chunks measure steps (348/354 exact, window/tokens equals the median).
   - Contamination: one record, harmless to decode, must be disclosed (m1).
   - Two reps; drift of about 5 % is not controlled (m2).
   - C, D and E have b = 1 only, and the ANY_PREFILL decode graph is
     unmeasured (M4).
3. **Bugs.** c0 as lockstep time (M4, material at saturation). Partial-chunk
   cost unmeasured. Small stretch double count. Preemption details
   (immaterial). Stale docstring and caveats. No bug in first-token time,
   own-rank decode pause, idle jumps or re-queue order.
4. **s15.** The model is systematically too slow at saturation (ensemble
   interval excludes the observation). Which rank congests is path-dependent.
   Several unmeasured pieces each move the outcome by about the size of the
   gap. G's data show that the k > 2 stretch is not the cause for short
   prompts. G does not settle it. A step log, G-bis and an ANY_PREFILL probe
   would. After those, a new registered saturated run, since s15 is spent.
5. **What may be said, and where.**
   - Paper, now: the probe results are testbed measurements. They may enter
     §4.3 and App. D through `make exp`, as a generated
     `paper/exp/macros-decode.tex` and one small table from data/exp/decode
     (via a paper_decode_tables.py). Content: decode step against batch
     bucket and context; one decode token per peer 512-token chunk; an
     own-rank prefill stops decode for its whole length; prefill k ranks at
     once runs 1.08-1.28× longer; the step follows the largest rank's bucket
     and context, not their sum. These back the §4.3 "lockstep" sentence
     (m6) and the §6 sentence. They are properties of this stack and should
     be named so.
   - Paper, not now: no lockstep or memory model output. The registered test
     failed. v2 is post hoc. Rule 7 admits simulator numbers only through
     paper/simulation.tex from libqueuingsim. Only the user can change rule
     7, not the authors or I (round-3 action 10 is still open). If model
     output is wanted later, the path is:
     - freeze v3 (c0 as latency plus the G-bis and ANY_PREFILL terms,
       committed hash);
     - pass a new registered held-out test;
     - port it to libqueuingsim's replay model and report it in §4.2 through
       simulation.tex, labelled "model with probe-derived costs".
   - docs/memory-model.md: v2 may be described as "a post hoc model, not
     validated, that is consistent with the long-context replays within the
     tolerances of the table and fails the saturated short-context arm", with
     the corrections below. The model-based price of a miss (round-3 action
     12) should wait for v3 and its registered test.

## Action list

1. Commit the registration as it stood, or state that it was never committed
   and give the evidence (file times). Correct the section timestamps from
   `date`/git. Name the memory_model.py change after registration, including
   the D > 0.5 s filter, and report metric 1 with and without it (M2).
2. State that v1 as run used Σ over ranks against the registered maximum, and
   add the registered-family A+B-only result (M1 table), labelled as computed
   after the fact by the reviewer.
3. Rewrite the v2 summary. Criterion 2 fails in s10c8 and s20c8. Drop "the two
   runs with enough misses to count". Add the short-context per-turn decode
   failure and the per-token medians. Say "consistent with", not "explains"
   (M3).
4. Move c0 out of the step, as a first-token latency, on the evidence of
   probe C. Freeze this before any new test. Fix the docstring and the
   caveats list (M4).
5. Add probe G to the doc with the table above, including the c0-removed
   ratios and the partial-overlap caveat. Use `overlap`/`peers_done_before`
   or drop them. Say that G does not explain s15 (M5).
6. Run G-bis (short appends observed from a decoding peer) and the
   ANY_PREFILL decode probe. Randomize the configuration order, repeat a
   reference configuration, add a nonce and assert zero cached tokens (m1,
   m2).
7. If feasible without disturbing the testbed runbook, record an engine-side
   step log for one replay. Validate the lockstep model step by step before
   any end-to-end test.
8. Commit the form search with its LOCO scores (m3).
9. Declare s15_base spent. Register a new saturated held-out replay (new trace
   seed, or spacings 1.25 and 1.75 s) with the frozen v3 and ensemble
   intervals. Judge counts below about 30 by interval, not ±25 %.
10. Put the probe measurements in the paper via `make exp` (macros plus one
    App. D table) to back §4.3's lockstep sentence. Fix Table 1's "budget the
    decode batch leaves" (m6). No model output in the paper; round-3
    action 10 (rule 7) stays with the user.
