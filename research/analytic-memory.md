# Miss feedback: the hit rate as a fixed point of the queue and the pool

Status: 2026-09-27, analysis only, **not in the paper**. Lean:
`lean/ServingQueueTheory/MissFeedback.lean` (in the axiom audit, 92 theorems
audited in total). Data: `scripts/exp/analyze_feedback.py` →
`data/exp/e2b/feedback.json`. Reviews: `research/reviews/2026-09-27-feedback-round*.md`.

## Why

The paper prices a miss as a change of policy: a fraction of turns turns from
hits into misses, and the hit rate `h` is an input chosen by the KV policy.
The testbed shows that `h` is also an output. In the short-context price test,
forcing 10 % of the turns to miss produced further, unforced misses at the
higher load (52 and 62 in two seeds; none at the lower load). In the
long-context replay, nearly all misses arrived while their rank already had a
queue, with the same think times as the hits (observed); the replica model of
`research/memory-model.md` attributes them to evictions during the wait, but that
attribution is output of a post hoc model, not an observation. So misses
change the conditions that decide later hits. This note writes that loop down
as a map whose fixed points are the hit rates a replica can sustain.

## The model

- `W(h)` — the mean wait before service at hit rate `h` ∈ [0, 1],
  nonincreasing in `h`. Prefill-bound instance: the Pollaczek–Khinchine wait of
  the hit/miss mixture, `λ m₂(h)/(2(1 − λ m₁(h)))`, set to ∞ when overloaded;
  memory-bound instance: the wait of a multi-server queue of memory slots whose
  service is the holding time `S(h) + D`.
- `G(T; h)` — the probability that a paused prefix survives an absence `T`
  when the replica runs at hit rate `h`. Two channels move it:
  - **wait channel**: the absence is the think time plus the turn's own wait,
    `T = Z + W(h)`, and a prefix is exposed to eviction while its turn queues;
  - **pool channel**: every miss re-inserts a whole context, so the insertion
    rate `r(h)` falls with `h`, the pool's eviction horizon (the LRU
    characteristic time of the Che approximation, `T_C(h) ≈ C / r(h)` for a
    cache of `C` tokens) rises with `h`, and `G(T; h)` rises with `h` at fixed
    `T` (e.g. `G ≈ 1{T < T_C(h)}` or a smoothed version).
- The **feedback map** is `H(h) = E_Z[ G(Z + W(h); h) ]`, and an
  **equilibrium** is a hit rate it reproduces: `H(h) = h`.

`G` is antitone in `T` and monotone in `h`, and `W` is antitone in `h`, so `H`
is monotone whichever channel carries the slope
(`feedback_map_monotone_two_channel`; the expectation over `Z` preserves it).
This is a mean-field model: one survival law, the mean wait.

## Results (Lean names in parentheses)

**1. Extremal equilibria, without continuity.** A monotone map of [0, 1]
into itself has a least equilibrium `h_` and a greatest `h̄`, and every
equilibrium lies between them (`unit_feedback_extremal`; Knaster–Tarski,
`feedback_extremal`). Continuity is not needed; with continuity the
intermediate value theorem also locates an equilibrium in any `[a, 1]` with
`H(a) ≥ a` and `H(1) ≤ 1` (`feedback_equilibrium_above`; its special case
`a = 0` uses `H(0) ≥ 0` and `H(1) ≤ 1`, given by the map staying in [0, 1]).

**2. Comparative statics.** If a change raises the map pointwise on [0, 1],
the greatest equilibrium does not fall, and neither does the least
(`unit_feedback_greatest_mono`, `feedback_gfp_mono`, `feedback_lfp_mono`;
Tarski and Topkis). Which changes raise the map depends on the loop being open
or closed: a larger pool raises `G` and so `H`; a lower offered load lowers `W`
and `r`; but in the closed loop a shorter think time or faster decode also
raises the turn rate `N/(Z + R)`, and the net sign is not determined
(the replica model shows faster decode giving *more* misses at a cap of 8).

**3. Collapse and two extremal equilibria.** If `H(0) = 0` and `H(a) ≥ a`
for some `a > 0`, the least equilibrium is 0 and the greatest is at least `a`
(`unit_feedback_bistable`, `feedback_bistable`); this is a statement about two
distinct equilibria, not about which one attracts. In the open prefill-bound
instance `H(0) = 0` holds whenever the all-miss load `λ S_miss ≥ 1`
(`pkFeedback_collapse`), `H = 0` wherever the stage is overloaded
(`pkFeedback_zero_of_overload`), and the map is monotone on [0, 1]
(`pkFeedback_monotoneOn`, from `pkWait_mixture_antitone`). There all-miss also
attracts: an overloaded hit rate is mapped to 0 in one step and stays there
(`pkFeedback_absorbing`). **In a closed system** (a finite population `N`, as
the replicas are) the wait is bounded, which removes the overload route to
`H(0) = 0`, but not the others: with the pool channel, or any step-shaped `G`,
`H(0) = 0` is still possible. Whether the bad state is exact collapse or a
low-hit equilibrium is then a property of `G`; the Tarski statements cover both,
and the admission target becomes a condition on `N`, not on `λ`.

**4. The forced-miss multiplier.** For an affine map `H(h) = c + k h`,
`0 ≤ k < 1` (`h₀ = c/(1 − k)`), forcing a share `δ ∈ [0, 1]` of turns to miss
gives the equilibrium `h_δ = (1 − δ)c/(1 − (1 − δ)k)`
(`forced_miss_equilibrium`) and `h₀ − h_δ = δ c/((1 − k)(1 − (1 − δ)k)) ≥ δ h₀`
(`forced_miss_amplified`): the direct loss `δh₀` plus the induced loss.

**Corollary (the marginal price of a forced miss).** To first order in `δ`,
a forced miss converts a would-be hit with probability `h₀` and induces
`h₀ k/(1 − k)` further misses on *other* turns, each with its own price. So
`price ≈ h₀ [Φ_forced + (k/(1 − k)) Φ̄_induced]`, not `Φ/(1 − k)`. Three
consequences:
- it composes with the paper's bracket (Proposition 1): the bracket applies to
  the total miss fraction `q_forced + q_induced`, with its own queue factor
  `(1 − ρ)/(1 − ρ′)`; the cache multiplier is a second, first-order amplifier
  that multiplies it and can be large at low ρ;
- the short-context price test already priced the induced misses ("the misses
  the change caused"). With the forced misses alone the bracket is
  [1.56, 1.88] and [1.71, 2.13] at 2.5 s (`hi_forced` in `analyze_price.py`),
  and the observed rises 2.05 and 2.15 lie above its upper end in both seeds
  (the second narrowly); with the induced misses included they lie inside
  ([1.80, 2.27], [1.89, 2.44]). So at that load the induced misses are needed
  to account for the rise. The corollary is a model of `q_induced`, testable as
  a prediction only if `k` is predicted in advance;
- a replica-wide `k` scales every `u_i = p_iΦ_i/(c_iτ_i)` by the same factor:
  it leaves the eviction order unchanged and moves only the comparisons with
  θ (keep or drop, admit, offload). If the induced misses concentrate on long
  absences, as here, the multiplier is program-specific and can reorder.

## What the short-context data say (`analyze_feedback.py`)

| pair (2.5 s unless noted) | δ (realised) | h₀ → h_δ | induced | k (secant) |
|---------------------------|--------------|----------|---------|------------|
| base → forced, seed 0 | 0.096 | 0.981 → 0.869 | 52 | 0.18 [0.12, 0.23] |
| base → forced, seed 1 | 0.094 | 0.982 → 0.870 | 62 | 0.19 [0.13, 0.24] |
| 3.5 s | 0.096 | 0.994 → 0.898 | 0 | ≤ 0.024 |

`k` here is a secant of `H` over a hit-rate drop of 0.11, not `H′(h₀)`; the
bands are 95 % Poisson bands on the induced count with the variance of both
arms. At 3.5 s no follow-up missed in either arm: 0 induced misses, `k ≤ 0.024`
at 95 %, a corner rather than a slope that has shrunk.

**Which channel.** Misses of non-forced follow-ups, by think gap:

| arm | gap ≥ 29 s: n, miss share | gap < 29 s: n, miss share |
|-----|---------------------------|---------------------------|
| 2.5 s base (seed 0 / 1) | 378, 0.077 / 378, 0.077 | 2610, 0 / 2610, 0 |
| 2.5 s forced (seed 0 / 1) | 338, 0.213 / 342, 0.246 | 2364, 0.0025 / 2364, 0.0017 |
| 3.5 s base / forced | 252, 0 / 226, 0 | 1740, 0 / 1574, 0 |

- The induced misses follow the 30 s think gaps (the trace's cap), as all of
  the baseline's do. The survival of a 30 s absence falls from 0.92 to about
  0.78, while the mean TTFT rises only from 0.58 to 1.08 s: the absence grows
  by under 2 %.
- **Wait channel** alone: with an exponential `G` matched to `G(30 s) = 0.923`
  (τ ≈ 375 s) and `|W′| ≈ 4.5 s`, it gives `k ≈ h|W′|/τ ≈ 0.01`, a sixth or
  less of the measured secant.
- **Pool channel**: new (non-cached) tokens per second per rank rise from 1129
  to 1609 (+42 %; seed 1: 1132 → 1612). During a long-gap turn's absence its
  rank inserted a median 35k tokens before a hit and 47k before a miss
  (baseline), 44k and 57k in the forced arm; during the turn's own wait, 0.6–5k.
  The think window carries 10–20× the eviction exposure of the wait.
- **A fixed token-count threshold fails, in and out of sample.** Choosing the
  capacity `C` so that the baseline's long-gap miss share equals the share of
  long-gap absences with more than `C` inserted tokens (C ≈ 48–49k tokens):
  in sample only 6 and 9 of the baseline's 29 long-gap misses lie above `C`;
  applied to the forced arm it predicts long-gap miss shares of 0.47 and 0.54
  against 0.21 and 0.25 (a smooth logistic version still overshoots 1.6×,
  review round 2); applied at 3.5 s, 12 absences of the forced arm lie above
  `C` and none missed. Inserted tokens go with misses, but the eviction horizon
  is not a fixed token count. For a free queue of 4096-token blocks this is
  expected: survival depends on block allocations (not tokens), on hits that
  reclaim blocks ahead in the queue, and on how long the free queue is; a
  forced miss's dead blocks, freed ahead of live prefixes, are one instance.

**Reading.** `k` is positive at 2.5 s (about 0.15–0.2, a secant over a
hit-rate drop of 0.11) and zero at 3.5 s, where no turn missed; the induced
misses follow the 30 s think gaps and coincide with a 42 % higher insertion
rate, so they run through the pool's eviction horizon rather than through the
wait. The data are consistent with *a* monotone feedback map; they exclude
the wait channel as the main route; the pool channel is inferred by
elimination and by association (insertions go with misses), not established,
since no fixed-threshold version of it fits.

## A worked example (open, prefill-bound; numbers are numerical, not propositions)

Deterministic `S_hit = 0.5 s`, `S_miss = 5 s`, `Z = 7 s`, `G(T) = exp(−T/60 s)`
(wait channel only), grid of 10⁵ points:

| offered rate | all-miss load | equilibria (slope `H′`) |
|--------------|---------------|-------------------------|
| λ = 0.25 /s | 1.25 | 0 (stable; `H = 0` on `[0, 2/9)`), 0.250 (unstable, 12.0), 0.882 (stable, 0.07) |
| λ = 0.20 /s | 1.00 | 0, an unstable point near 0.010, and the good one |
| λ = 0.18 /s (a lower offered rate) | 0.90 | 0.885 (stable, 0.05) only |

The collapse disappears only for λ < 0.2. The good equilibrium's slope 0.07 is
the model's own statement that the wait channel is weak at a healthy operating
point. This example is open (λ given); a session cap is a finite `N` and must
be modelled as one.

## Literature (to check in the source before any citation; all UNVERIFIED here)

Thrashing, load-dependent bistability and its load-control cure in paging
systems (Denning, 1968; Courtois, 1975); fixed points of Erlang loss networks
and their bistability, trunk reservation as the analogue of an admission cap
(Gibbens, Hunt and Kelly, 1990; Kelly, 1991); bistability in slotted ALOHA
(Carleial and Hellman, 1975); the LRU characteristic time (Fagin, 1977; Che,
Tung and Wang, 2002; Fricker, Robert and Roberts, 2012); order-theoretic fixed
points and monotone comparative statics (Tarski, 1955; Topkis, 1978; Milgrom
and Roberts, 1990); congestion instability of LLM replicas (Ao et al., 2026,
already cited in the paper). These were named by the reviewer from memory; none
has been read for this note. What is new here is narrow: coupling prefix-cache
survival with the prefill (or memory) queue and the session think loop, and
reading the price of a miss through a cache multiplier.

## Next

1. A registered channel-separation run at the 2.5 s load, predictions and
   decision rules committed before it runs. Treat eviction as roughly
   `r · T > C`: the insertion rate `r` and the absence `T` are the two factors
   of one product, so each channel is tested by moving one factor by the same
   log-dose as the forced arm moved `r` (+42 %):
   (a) insertion only — cold filler prompts from sessions that never return,
   matched to the forced arm's extra **block allocations** per rank (not
   tokens), with the filler's own TTFT side effect registered;
   (b′) absence only — the think gaps stretched by the same factor
   (30 s → about 42 s) with no extra work;
   (b) kept only as a paired per-turn delay of ≈0.5 s, which both channels
   predict to do almost nothing.
   Decision rules as numbers, against the measured noise floor (about 14
   discordant turns between the two baseline runs). Before the run: validate a
   block-level free-queue proxy on the existing logs (in sample and at 3.5 s),
   or enable the engine's KV-cache events if the rbln fork supports them.
2. A dose response (δ = 0.05, 0.10, 0.20, two seeds) on a trace with think gaps
   spread around 20–40 s, so that `G(T; h)` is observable at more than one `T`
   and `k` can be predicted from the base arms.
3. Only then a hysteresis or burst test of bistability, at a load where the
   closed-population model predicts two equilibria.

## Paper

Nothing now. §3.3 ("the two compete unstably") and §4.3 ("the feedback of
§3.3") already describe the pool channel, which is the one the data support.
After the tests, at most one prose paragraph in §3.3 with inline `\provedby`
(the Tarski theorems, the multiplier), no new proposition box, no worked-example
numbers unless their sign changes are proved, and any testbed-derived `k`
only through `make exp`.
