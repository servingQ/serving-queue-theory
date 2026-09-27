# Review: miss feedback (docs/analytic-memory.md, MissFeedback.lean), round 2

Reviewer: queueing theory / applied probability (same reviewer as round 1).
Date: 2026-09-27. Material: my round-1 report, the response
(`2026-09-27-feedback-round1-response.md`), the rewritten
`docs/analytic-memory.md`, `lean/ServingQueueTheory/MissFeedback.lean`,
`scripts/exp/analyze_feedback.py`, `data/exp/e2b/`, and `paper/main.tex`
§3.3 / §4.3 for m8.

What I ran (throw-away scripts in the scratchpad; no repository file changed
except this report; no NPU access):

- `lake env lean ServingQueueTheory/MissFeedback.lean`: no output, 2.2 s.
  All 17 theorems are in `lean/scripts/AxiomAudit.lean` (l. 98–115); the
  audit has 91 `#print axioms` lines, as the note says.
- `python3 scripts/exp/analyze_feedback.py`: every number in the note's
  data section matches the output to the stated rounding (details in R3).
- Checks the script does not make: the full variance of the induced count;
  a turn-by-turn pairing of the arms (same sessions, same rounds); the
  run-to-run noise between the two baseline runs; the in-sample fit of the
  threshold rule; a smooth (logistic) version of it; the threshold applied
  out of sample at 3.5 s; `hi` of the price bracket with forced misses only.

## Verdict

**Accept (as a docs-level analysis),** after the corrections R1–R6 below.
They are wording-level plus one small script fix. None needs server time.

- The re-specification is right. The model now has both channels, the wait
  channel is called a hypothesis, and the Lean has real content: Tarski
  extremal equilibria on `[0,1]` without continuity, monotone comparative
  statics of the extremal points, and a PK instance whose collapse lemma is
  no longer a tautology.
- The data section is regenerable and its numbers are correct.
- Two things are still oversold, and one is wrong:
  - **Oversold: "bistable".** The Lean proves two *distinct extremal
    equilibria*. It does not prove that either one attracts.
  - **Oversold: "carried by the pool channel".** The wait channel is
    excluded convincingly. The pool channel is supported by elimination
    and by a strong association, but every quantitative pool model tried
    so far fails, now also out of sample at 3.5 s (R3).
  - **Wrong: "in a closed system … `H(0) > 0`".** A bounded wait removes
    only the *overload* route to `H(0) = 0`. With the pool channel, or with
    any step-shaped `G`, `H(0) = 0` is still possible in a closed system
    (R2).
- For the registered test, arm (b) as currently specified cannot
  discriminate. Both channels predict "almost none" for a 0.5 s delay under
  any smooth `G`. That was my round-1 design, and I correct it in R5.
- For the paper, one sentence of my round-1 report was incomplete, and
  the note repeats it: "the bracket with forced misses alone would still
  contain the rise". I checked only the lower end. The upper end is
  probably not met in seed 0 (R4).

## Status of the round-1 items

| # | Round-1 action | Status | Comment |
|---|---|---|---|
| 1 | Two channels; the wait channel a hypothesis | **resolved** | `H(h) = E_Z[G(Z+W(h); h)]`; long-context eviction-while-waiting marked as model output. The claim "the expectation over `Z` preserves it" is not in Lean (`feedback_map_monotone_two_channel` has a fixed `Z`). It is trivial, but cite it as prose, not next to a Lean name. |
| 2 | Knaster–Tarski | **resolved, with one naming issue** | `unit_feedback_extremal`, `unit_feedback_greatest_mono`, `feedback_{g,l}fp_mono` match the prose. `unit_feedback_bistable` proves `lfp = 0 ∧ a ≤ gfp`, i.e. multiplicity, not bistability (R1). Convergence of the iteration is not formalised; the response says so, the note does not. |
| 3 | PK instance; drop the tautology | **resolved** | `pkFeedback` is the PK mixture wait of `CacheReuse` (deterministic class services, `m₂ = hS_hit² + (1−h)S_miss²`), 0 when overloaded. `pkFeedback_monotoneOn` has the right hypotheses (`G` antitone and ≥ 0, `λ > 0`, `0 ≤ S_hit ≤ S_miss`). `pkFeedback_collapse` now carries the content "all-miss utilisation = λS_miss". Note that it is the *wait-channel, open* instance, the one the data do not support. Say so in result 3. |
| 4 | Closed population; cap wording; comparative-statics list | **partly** | Cap wording and the closed-loop signs are fixed. The closed-system sentence is wrong as stated (R2). The condition on `N` is not derived. The note says "becomes a condition on `N`", and it should add "not derived". |
| 5 | Corollary | **resolved** | `h₀`, `Φ_forced` vs `Φ̄_induced`, composition with the bracket, eviction order unchanged. One inherited error (R4). |
| 6 | Consistency section via a script | **resolved, band too narrow** | Formula, secant wording, 30 s table and insertion numbers all reproduce. The band is too narrow and degenerate at 3.5 s (R3). |
| 7 | m1, m3–m8 | **mostly** | m1 (2/9), m3, m4, m5, m6, m7 done. The λ = 0.20 row (0, 0.0103, 0.8841) agrees with my round-1 recomputation. m8 is not settled (R6). |
| 8 | Literature | **acceptable for docs** | All listed as UNVERIFIED, as rule 4 requires. Must be read before any paper sentence. |
| 9 | Registered tests | **open** | No registration committed. The design needs the R5 changes first. |
| 10 | Paper: nothing | **resolved** | But the existing §3.3 sentence overclaims (R6). |

## Remaining issues

### R1. "Bistability" is multiplicity

- `unit_feedback_bistable` / `feedback_bistable` say: if `H(0) = 0` and
  `H(a) ≥ a` for some `a > 0`, then `lfp = 0` and `gfp ≥ a`. That is
  two distinct equilibria. Stability is not proved.
- The heading "Collapse and bistability" and the Lean names therefore claim
  more than is proved. Either rename (e.g. "two extremal equilibria",
  `unit_feedback_two_equilibria`), or add the stability content. The easy
  half is available:
  - In the PK instance, the overloaded set `{h : λm₁(h) ≥ 1}` is an
    interval `[0, h_c]`, by `utilization_antitone`. `H = 0` there, by
    `pkFeedback_zero_of_overload`.
  - So every `h ∈ [0, h_c]` is sent to 0 in one step of the iteration.
  - That is a one-line theorem, and it is the "0 attracts" half.
  - The "gfp attracts from above" half needs one-sided continuity. It is
    not needed for a docs note. Say it is not proved.
- The worked example's "stable/unstable" labels mean `H′ < 1` or `> 1`
  for the iteration or the fluid heuristic `ḣ = (H(h) − h)/T`. State
  that in the caption. The dynamic reading is a heuristic, not a model of
  the stochastic system (round-1 M4).

### R2. The closed-system sentence

The note says: "In a closed system the wait is bounded, `H(0) > 0`, and the
bad state is a low-hit equilibrium rather than exact collapse." The first
clause does not imply the second.

- `H(0) = E_Z[G(Z + W(0); 0)]`. A bounded `W(0)` makes the argument
  finite. It does not make `G` positive there.
- With the pool channel, `G(·; 0)` is survival at the all-miss insertion
  rate. If the all-miss eviction horizon `T_C(0)` is below the shortest
  absence (step `G`, Che), then `H(0) = 0` in a closed system too.
- The same holds for the wait channel with a step `G`.
- Correct statement: a finite population removes the overload route to
  `H(0) = 0`. Exact collapse then requires the all-miss pool to flush
  faster than the shortest absence. Otherwise the bad equilibrium is a
  low-hit one, and the Tarski statements cover both cases.
- The same correction applies to `docs/research-plan.md` if it repeats the
  sentence.

### R3. The data section: numbers right, uncertainty and pool test wrong

All numbers check against the script output:

- δ 0.096/0.094/0.096; `h₀ → h_δ`; induced 52/62/0;
- `k` 0.179 [0.159, 0.199] and 0.186 [0.164, 0.207];
- TTFT 0.58 → 1.08 s; new tokens 1129 → 1609 and 1132 → 1612 per s per
  rank;
- the 30 s-gap table; absence insertions 34.5k/46.7k (base) and
  43.9k/56.6k (forced), seed 0;
- C = 49 092 / 48 202; predicted long-gap miss 0.465/0.538 against
  0.213/0.246 observed;
- `ΔL_P/lo_forced` = 1.316 and 1.258 (from `price_*.json`; that pair is
  not produced by `analyze_feedback.py` and should be).

Also checked:

- The `k` formula is correct: `R = 1/(1 − (1 − δ)k)` inverts to
  `k = (1 − 1/R)/(1 − δ)`. The wait-channel estimate is correct:
  `τ = 30/(−ln 0.923) ≈ 375 s`, `|W′| ≈ 0.50/0.112 = 4.5 s`, `k ≈ 0.011`.
  Restricted to the 13 % of follow-ups with long gaps (a smooth `G` fitted
  at 30 s is refuted by the zero short-gap misses anyway), it is 0.001.
  The conclusion holds either way.

What is wrong or missing:

1. **The band is too narrow.**
   - `band = √induced / n` treats the baseline term as exact.
   - `induced = X_B − cX_A` with X_B = 78/88 and X_A = 29, c ≈ 0.90, so
     `sd = √(X_B + c²X_A)` ≈ 10.1 and 10.6, not 7.2 and 7.9.
   - The ±1 sd bands become [0.15, 0.21] and [0.16, 0.22]. The 95 % bands
     are [0.12, 0.23] and [0.13, 0.24].
   - Say which (±1 sd or 95 %). "Poisson band" alone does not say.
   - The empirical run-to-run noise supports this order of magnitude. The
     two baseline runs agree in total (2932 vs 2933 hits) but disagree on
     14 turns (7 hit→miss, 7 miss→hit).
2. **At 3.5 s the band is degenerate.**
   - The script prints `k = 0.007 [0.007, 0.007]`. The 0.007 comes from
     about one extra partial hit, not from induced misses.
   - The honest statement is: 0 induced misses, and a 95 % Poisson upper
     bound of 3, i.e. `k ≤ 0.024`. Report that instead of "0.01".
3. **The two definitions differ slightly.**
   - "induced" counts unforced misses. `k` uses hit shares, so partials
     count as non-hits.
   - Seed 1 differs by about 5 turns (induced partials −5.5). Harmless,
     but the table puts the two side by side as if one were derived from
     the other. Add one line of definition.
4. **Pair the arms turn by turn.**
   - Both arms replay the same (session, round) keys (2988 in each). The
     paired table is sharper than the count difference.
   - Seed 0: hit→unforced 57, unforced→hit 8, 282 forced. Seed 1: 59 and
     6.
   - It identifies the induced *turns*. Any channel diagnostic should then
     be run on those 57/59 turns, not on class-level medians.
   - Only 4/78 and 11/88 of the forced arm's unforced misses directly
     follow a forced turn of the same session. That is about the base
     rate, so there is no same-session artefact. Worth one line.
5. **The threshold test fails in sample and out of sample. The note reports
   neither.**
   - *In sample.* C is chosen so that the baseline share matches, but only
     6 of 29 (seed 1: 9 of 29) baseline misses have more than C inserted
     tokens. The rule gets the share right and mostly picks the wrong turns.
   - *Smooth version.* A logistic fit of miss on inserted tokens (baseline,
     long gaps): slope 2.1 ± 0.4 per 10k tokens, so the association is
     strong (z ≈ 5). Applied to the forced arm, it predicts 0.37 and 0.43
     against 0.23 and 0.26 observed. It still overshoots, by 1.6×.
   - *Out of sample, 3.5 s.* With the 2.5 s capacity C ≈ 48k, 13 of 215
     long-gap absences in `s35_m10` (6 %) exceed C, and 0 missed.
     P(0 | Poisson 13) ≈ 2·10⁻⁶.
   - Reading: inserted tokens are associated with misses, but the eviction
     horizon is *not a fixed token count*. It depends on the pool state.
6. **What the pool state means for this replica.** The testbed pool is 51
   allocatable blocks of 4096 tokens per rank, with vLLM's LRU free queue.
   A prefix freed at `t₀` survives while

   (blocks allocated since `t₀`) + (cached blocks *ahead of it* reclaimed
   by hits) < (free-queue length at `t₀`).

   Three differences from the token proxy follow:
   - allocations are whole blocks, so a 5k re-prefill costs 2 blocks and a
     short append may cost 0 or 1;
   - hits by other sessions shorten the queue ahead;
   - the free-queue length at `t₀` shrinks with the in-use footprint, so it
     is load-dependent. That explains the 3.5 s failure.

   It also makes the note's dead-cache explanation precise. Under strict
   LRU, a dead block does not "absorb insertions". Rather, a forced
   session's old blocks are never reclaimed by a hit, so they stay ahead
   of later prefixes as a buffer. In the baseline, such blocks are pulled
   out of the queue when their session returns. Rewrite the sentence that
   way and keep it labelled as untested.

   The script should also count completion tokens: decode writes KV blocks
   too. `new_per_rank` includes them and `insertions` does not.
7. **Wording in the note and the research plan.**
   - "The think window carries 10–20× the eviction exposure" compares a
     median with a mean. Using means for both, or medians for both, the
     baseline ratio is 50–75×, not 10–20×. Say "one to two orders of
     magnitude".
   - `docs/research-plan.md` says "carried by the pool channel … not the
     wait". Write instead: "not the wait (excluded); the pool channel is
     indicated by the insertion association, but no constant-capacity
     pool model fits (overshoots 1.6–2.2× at 2.5 s, fails at 3.5 s)".

### R4. The price test and the bracket: my round-1 sentence was incomplete

- The note repeats my round-1 claim that the bracket with forced misses
  alone would still contain the rise (`ΔL_P/lo_forced` = 1.32, 1.26). That
  checks only the *lower* end.
- The upper end with forced misses only (`hi_forced`) is not computed.
  Scaling `hi` by `lo_forced/lo` gives 1.96 < ΔL_P = 2.05 in seed 0, and
  2.21 > 2.15 in seed 1. The queue factor `(1 − ρ)/(1 − ρ′)` would be
  smaller still with forced work only, which lowers `hi_forced` further.
- So in seed 0 the forced-only bracket probably does *not* contain the
  rise, and the induced misses would be needed to close it. That is weak
  evidence for feedback in the price test, not evidence against it.
- Compute `hi_forced` in `analyze_price.py` and replace the sentence with
  whatever it gives. Until then write "the lower end with forced misses
  alone is below the rise; the upper end is not computed".

### R5. The registered channel-separation test, as designed, cannot discriminate

Under Che-type LRU, a prefix is lost roughly when `r · T > C_eff`: the
insertion rate times the absence exceeds the effective capacity. The two
"channels" are then the two factors of one product. The wait channel moves
`T`, and the pool channel moves `r`. The forced arm moved `log r` by
+0.35 and `log T` by +0.017. This reframing gives a sharper design.

- **Arm (b) at +0.5 s predicts "almost none" under both hypotheses** for
  any smooth `G`. It only tests a step `G` with its horizon in
  [30, 30.5] s. Keep it only as a paired-delay arm: delay each returning
  turn by the forced arm's per-turn TTFT increase for the same (session,
  round), not by the mean. The tail matters for a step `G`.
- **Add (b′), equal log-dose on `T`.** Stretch the long think gaps by the
  same factor as the forced arm's insertion rate (30 s → about 42 s).
  - The product form predicts that (b′) and (a) give similar long-gap miss
    shares.
  - A pure wait-channel reading predicts that (b′) ≫ (b).
  - A reading where `r` matters but `T` does not (not Che) predicts
    (b′) ≈ (b).
  - This test separates the three readings. Record that the stretched
    think time lowers the turn rate a little (closed loop), and measure `r`
    in every arm.
- **Arm (a) is not "insertion only".** Cold fillers also add prefill work,
  so they raise `W`.
  - Register the predicted TTFT rise and its wait-channel contribution
    (small, by R3).
  - Match *block allocations per second per rank*, not tokens. Use prompt
    sizes like the forced re-prefills: 4096-token blocks make this matter.
  - Fillers leave dead blocks *behind* live prefixes. Forced misses leave
    them *ahead* (R3.6). So (a) is expected to exceed the forced arm's
    induced count if the buffer story is right. Register that as the
    discriminating sign.
- **Measure evictions directly if at all possible.** If the rbln vLLM
  build supports KV-cache events (block stored/removed; upstream vLLM has
  a KV-events publisher, not verified for this fork), turn them on. Then
  `G(T; h)` and the free-queue position are observed, not inferred from a
  first-token proxy.
- **Decision rule and power, written before the run.**
  - Two seeds per arm. Outcome: induced long-gap misses, paired by
    (session, round) against the baseline.
  - Noise floor: 14 discordant turns between the two baseline runs, so
    about ±4 on a net count. The forced arm's effect is 57–59 hit→miss
    turns, so two seeds give ample power for "most" vs "almost none".
  - Write the rule as numbers (e.g. an arm "reproduces" the effect if its
    net induced count is ≥ 0.5 × 55 in both seeds, "none" if ≤ 10), and
    commit it with the predictions.
- The dose response on spread think gaps remains the right second step. It
  is the only way to see `G(T; h)` at more than one `T`.

### R6. m8: the paper's §3.3 sentence is neither the note's channel nor supported as "unstable"

- §3.3: "the two compete unstably: a miss holds its turn in the prefill
  queue and then in the batch for longer, which holds more bytes, which
  evicts more suspended state".
  - That is the *occupancy* route, a smaller free queue. The note's pool
    channel is the *re-insertion* route, a higher `r`.
  - The testbed shows a *stable* amplifier: `k ≈ 0.18 < 1`, and the
    iteration converges. Multiplicity is shown only in the open worked
    example, and instability nowhere on the testbed.
- The note's claim that §3.3 "already describes the pool channel, which is
  the one the data support" is therefore not accurate.
- Recommended, independent of the feedback work, since it is a live paper
  claim:
  - Replace "unstably" with "and each miss makes the next more likely".
  - Name both routes: the miss re-inserts its whole context, and it holds
    its bytes for longer.
  - Keep "unstable" only for what §4.2's simulation shows, if it shows
    thrashing.
  - In §4.3, "more through the pool" should read "after the 30 s gap, not
    through the wait".
  - This is a paper edit, so `make check` applies.
- The Lean module header (l. 4–11) still describes the wait channel only,
  and `feedback_comparative_statics`' docstring still lists "a shorter
  think time" among the changes that raise `H`, which round-1 M3 withdrew.
  Update both. The prose next to a Lean statement is what a reader checks
  (AGENTS.md rule 6).

## What remains before …

**(a) a registered channel-separation test**

1. Redesign per R5: paired-delay (b), equal-log-dose (b′), block-matched
   (a) with a registered TTFT effect, a numeric decision rule, two seeds.
2. Build a block-level free-queue proxy from the existing logs (R3.6).
   Check it in sample, then against 3.5 s, *before* the run. Or enable KV
   events. Without one of them the pool channel has no quantitative
   prediction to register, only a sign.
3. Commit the registration (arms, predictions, decision rule, analysis
   script) before any server time, as in memory-model round 3.

**(b) any paper sentence**

1. The registered test run and analysed, with the channel settled at least
   by sign.
2. R1 (rename, or prove the one-step attraction), R2 (closed-system
   sentence), R4 (`hi_forced`).
3. The literature of the note read in the source. Courtois and Kelly at
   least, if the paragraph cites the phenomenon.
4. Any `k` or induced count only as a `make exp` macro, with the corrected
   band.
5. Still at most one prose paragraph in §3.3 with inline `\provedby` of the
   Tarski theorems and `forced_miss_amplified`. No proposition box, and no
   worked-example numbers unless their sign changes are proved.
6. R6's §3.3/§4.3 wording can and should be fixed now, independently.

## Action list

1. Rename "bistable" to "two extremal equilibria" in the note and in the
   Lean names/docstrings, or add the one-step attraction of `[0, h_c]` to
   0 for `pkFeedback`. Define "stable" in the worked-example caption as
   `H′ < 1` of a heuristic iteration (R1).
2. Fix the closed-system sentence: bounded wait removes only the overload
   route to `H(0) = 0`. State that the condition on `N` is not derived (R2).
3. Script: full-variance band (`√(X_B + c²X_A)`), state ±1 sd or 95 %,
   Poisson upper bound at zero counts. Paired (session, round) table.
   Completion tokens in the insertions. Emit `ΔL_P/lo_forced` (R3).
4. Note: report the threshold rule's in-sample hit (6/29, 9/29), the
   logistic prediction (0.37/0.43 against 0.23/0.26), the 3.5 s
   out-of-sample failure (13 above C, 0 misses), and the corrected
   dead-cache mechanism. Change "10–20×" to "one to two orders of
   magnitude". Soften the research-plan line (R3).
5. `analyze_price.py`: compute `hi_forced`. Replace the "bracket contains
   it with forced misses alone" sentence with the result (R4).
6. Redesign and commit the channel-separation registration per R5, with a
   block-level pool proxy validated on existing data first.
7. Update the Lean module header and the `feedback_comparative_statics`
   docstring. Cite "expectation over `Z`" as prose (R6, item 1).
8. Paper, now and independent of this note: §3.3 "compete unstably" →
   amplification with both routes named; §4.3 "through the pool" → "after
   the 30 s gap, not through the wait"; `make check` (R6).
