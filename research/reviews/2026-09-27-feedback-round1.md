# Review: miss feedback (research/analytic-memory.md, MissFeedback.lean), round 1

Reviewer: queueing theory / applied probability (same reviewer as the
earlier rounds). Date: 2026-09-27. Material: `research/analytic-memory.md`,
`lean/ServingQueueTheory/MissFeedback.lean`, with `research/memory-model.md`,
`paper/main.tex` (§2.4, §3.3, §4.3), `data/exp/e2b/`.

What I ran (throw-away scripts, scratchpad only; no repository file changed
except this report, no NPU access):

- `lake env lean ServingQueueTheory/MissFeedback.lean`: no output, 2 s. It
  compiles, has no `sorry`, and all seven theorems are in
  `lean/scripts/AxiomAudit.lean` (l. 98–105).
- I recomputed the worked example from its description (PK mixture, grid of
  10^5 points).
- I recomputed the implied slopes from `price_*.json`, and again from the
  full `rounds.jsonl` of the six arms using the classifier of `analyze_price.py`.
- I ran two diagnostics on the short-context arms that the note does not
  have: miss rate by think-time gap, and the tokens inserted on the rank
  during the think time against those inserted during the turn's own wait.

## Verdict

**Not ready for the paper. Worth keeping as a direction, after it is
re-specified.**

- The algebra is right. The Lean compiles.
- The formal content is thin. Most of the Lean is generic: the intermediate
  value theorem, the monotonicity of a composition, and the algebra of an
  affine map. One theorem is a tautology, and the two structural claims the
  prose leans on (extremal equilibria, stability) are not formalised.
- The more serious problem is the mechanism. The model assumes that the wait
  drives the feedback: `G` depends only on the absence, and the absence
  grows through `W(h)`. In the only data where `k` is measured (the
  short-context price test), that channel is too small by about an order of
  magnitude.
  - The induced misses sit on the 30 s think-time atom of the trace.
  - Under the note's own exponential `G`, the extra wait predicts
    `k ≈ 0.01`, against the implied 0.16–0.20.
  - What moves is the survival itself. A forced miss re-inserts its whole
    context, which raises the insertion rate and shortens the pool's
    eviction horizon.
- So `G` must depend on `h`. The theory survives that change: it is still
  a monotone fixed-point problem. But the text, the example and the
  "consistency" reading all have to change.

## Major issues

### M1. What the Lean proves vs what the prose claims

| Prose claim | Lean | Status |
|---|---|---|
| (1i) `H` nondecreasing | `feedback_map_monotone` | Correct, but only for finite `W : ℝ → ℝ`. The overload convention `W = ∞ ⇒ H = 0` cannot be expressed and is not proved. |
| (1ii) an equilibrium exists | `feedback_equilibrium_exists` | Correct. Continuity is a *hypothesis*. The overload boundary (the note's "H extended by 0 is continuous") is exactly the point at issue, and it is assumed away. |
| (1ii) the set of equilibria has a least and a greatest element | none | Not formalised. |
| (1iii) equilibrium in [a,1] | `feedback_equilibrium_above` | Correct. |
| (2i) overloaded at all-miss ⇒ `H(0)=0` ⇒ collapse | `feedback_collapse` | **Vacuous.** It proves `H 0 = 0 → 0` is a fixed point. The content, "all-miss load ≥ 1 ⇒ H(0) = 0", is not in Lean. |
| (2) all-miss is stable if `H ≡ 0` near 0; "bistable" | none | Not formalised. "Bistable" is asserted from the existence of two fixed points, which is not bistability. |
| (3) comparative statics; "the greatest equilibrium does not fall" | `feedback_comparative_statics` | The hypothesis is only `H x ≤ K x`, which is weaker, so the theorem is fine. The "greatest" sentence is not proved. |
| (4) forced-miss equilibrium and amplification | `forced_miss_*` | Correct algebra for an affine map. |
| stability (`H' < 1` attracts) | none | Not proved. The table's "stable/unstable" labels are numerical. |

Use Knaster–Tarski instead of the IVT for the structural part. It is
stronger and removes the continuity problem.

- `[0,1]` is a complete lattice (`Set.Icc.completeLattice`), and a
  monotone self-map is an `OrderHom`.
- `OrderHom.isGreatest_gfp` / `lfp` give the greatest and least equilibria
  with **no continuity at all**. The overload boundary stops mattering.
- `gfp` is monotone in the map (it is itself an `OrderHom` on
  `α →o α`). That is exactly "the greatest equilibrium does not fall"
  (monotone comparative statics of extremal equilibria, Topkis /
  Milgrom–Roberts).
- For stability of the iteration: with `H` monotone, `h_n` from `h_0 = 1`
  is nonincreasing. If `H` is continuous from the left, it converges to the
  gfp, and symmetrically from 0 to the lfp. That gives "the greatest
  equilibrium attracts everything above it" as a theorem.
- Bistability is then provable as a statement: (a) `H = 0` on `[0, h_c)`,
  so 0 attracts `[0, h_c)` in one step; (b) the gfp is `> 0` and attracts
  a set that contains a left neighbourhood of it whenever `H(h) > h` just
  below it.
- Formalise the PK instance concretely. Define `H_pk h = if λ m₁(h) < 1
  then G (Z + mixtureWait …) else 0`. Prove it monotone using
  `pkWait_mixture_antitone` plus the case split. Prove `H_pk 0 = 0` from
  `λ S_miss ≥ 1`, and `H_pk = 0` on `[0, h_c)`. Then
  `feedback_collapse` has content.
- The memory-bound instance ("multi-server queue of memory slots,
  nonincreasing because S(h) is") needs either a proof or a citation for
  the monotonicity of the Erlang-C wait in the holding time at fixed λ
  and c.

### M2. The mechanism in the data is not the one in the model

The note's model: `G(T)` is independent of the pool state and of `h`, and
the feedback runs through `W(h)` alone. That is prefix exposure during
queueing. The short-context arms say otherwise.

Miss rate of non-forced follow-ups, full runs (my recomputation):

| arm | gap ≥ 29 s: n, miss share | gap < 29 s: n, miss share |
|---|---|---|
| s25 base | 378, 0.077 | 2610, 0.0000 |
| s25 forced | 338, 0.213 | 2364, 0.0025 |
| s25 base, seed 1 | 378, 0.077 | 2610, 0.0000 |
| s25 forced, seed 1 | 342, 0.246 | 2364, 0.0017 |
| s35 base / forced | 252 / 226, 0 | 1740 / 1574, 0 |

- 92–95 % of the induced misses follow the 30 s think-time atom, like
  100 % of the baseline's.
- The survival of a 30 s absence falls from 0.92 to 0.77–0.79.
- Over the same change, the mean TTFT rises from 0.58 to 1.08 s, so the
  absence grows by under 2 %.
- Under the note's exponential `G`, fitting `G(30 s) = 0.923` gives
  τ ≈ 375 s. Then `k = h |W'(h)| / τ ≈ 0.98 × 4.5 s / 375 s ≈ 0.01`,
  about 6 % of the implied slope.
- A step-shaped `G` (LRU) could make the wait matter. But that needs the
  eviction horizon to sit within half a second above 30 s for a sixth of
  the sessions, a coincidence I would not assume.

What does move is the insertion rate:

- New (non-cached) tokens per second per rank rise from 1130 to 1610
  (+42 %) in the forced arms. A forced miss writes its whole context under
  a new nonce, and its old blocks stay as dead cache.
- Tokens inserted on the rank during the 30 s think window: median 47–62k
  before a miss, 35–46k before a hit, in both arms.
- Tokens inserted during the turn's own wait: mean 2–5k. The think window
  carries 10–20× the eviction exposure of the wait.
- The first-token time is a proxy for insertion, and block granularity is
  ignored. But the ordering is not close.

So the feedback measured at 2.5 s runs through the pool:
misses → insertions → a shorter eviction horizon → misses for long
absences. This is the classical LRU characteristic-time picture (Che
approximation): with an insertion rate `r(h)` nonincreasing in `h`, the
horizon `T_C(h)` is nondecreasing, and `G(T; h) ≈ 1{T < T_C(h)}`, or a
smoothed version.

The theory absorbs this at no cost:
`H(h) = E_Z[ G(Z + W(h); h) ]`, with `G` antitone in `T` and monotone in
`h`, is still monotone. The Tarski results and the multiplier algebra do
not care which channel produces the slope. But:

- The "Why" section, the model section and the corollary must name both
  channels. The pool channel is also the one §3.3 of the paper already
  describes: "a miss holds … more bytes, which evicts more suspended state".
- The long-context evidence for the wait channel ("88–96 % had their
  prefix resident when sent and lost it while waiting") is **model output**
  of the post hoc, unvalidated memory model (round-4 verdict). The
  observed facts, misses arriving to a queue and equal think times, are
  compatible with a common cause: congestion raises both the queue and the
  eviction rate. Present the wait channel as a hypothesis for the
  long-context regime, not a finding.

### M3. Open-model artefacts: the exact collapse and the comparative statics

- **The collapse depends on the open model.** `W = ∞` and the exact
  all-miss equilibrium come from the open PK wait. The replica the note
  wants to describe is closed at the turn level (think loop, session cap),
  and the paper's own `prop:finite` and the trace findings say that the
  open wait overstates by 4–20× there.
  - With a finite population the wait is bounded, so `H(0) > 0`, and the
    "collapse" is a *low-hit* equilibrium, not `h = 0`.
  - The Tarski formulation handles this unchanged (lfp > 0).
  - Proposition 2(i) and the admission target "keep the all-miss load
    below 1" have to be restated for the closed model: a condition on the
    session cap `N`, not on λ.
- **The comparative statics' signs are not unconditional in a closed
  loop.** "A shorter think time raises H" holds only with λ held fixed. In
  the closed loop λ = N/(Z + R), so a shorter Z also raises the turn rate.
  `research/memory-model.md` shows exactly that ("at the cap of 8 faster decode
  gives **more** misses: the loop is closed"). The same caveat applies to
  "a lower arrival rate". Proposition 3 is correct as an abstract
  statement. The parenthetical list of changes that "raise the map" is
  not.
- **An admission cap is not an arrival rate.** The worked example's
  "λ = 0.18 (an admission cap)" conflates the two. A cap bounds the
  replica population and moves the excess to the door (door waits of
  500–770 s in the long-context replays). Model it as a finite `N`, or say
  that λ = 0.18 is a lower offered rate.

### M4. Mean-field choices

- **A fixed Z is the wrong reduction here.** The data show the feedback
  lives entirely in the tail of Z, the 30 s atom. Use `H(h) = E[G(Z +
  W(h); h)]`. The slope `k` is then roughly the density of `Z + W` at the
  eviction horizon times the horizon's sensitivity to `h`. The 2.5 s value
  of `k` is therefore a property of the trace's 30 s cap meeting `T_C`.
  It does not transfer to other think-time laws. Say so wherever `k` is
  quoted.
- **Mean wait inside G.** For convex `G` (the exponential),
  `G(Z + E W) ≤ E G(Z + W)` by Jensen, so the mean-field map *understates*
  `H`. For a step `G` the error has no sign. State this. The
  distributional version costs nothing in the monotonicity proofs.
- **The direction of causality is modelled as instantaneous.** The
  "adjustment iteration" is not a model of the stochastic system. Either
  call it a fluid heuristic, `ḣ = (H(h) − h)/T_turnover`, whose 1-D
  stability condition is also `H'(h*) < 1` and whose monotone `H` rules
  out oscillation, or drop the dynamic language. Metastability in the
  stochastic system (exit times from the good well) is a separate and
  much harder claim. It is not in reach, and the note correctly lists it as
  a limitation.

### M5. The corollary Φ/(1−k)

The first-order algebra is right once the `h₀` factor is kept:

- total hit loss `δh₀/(1 − (1 − δ)k)`;
- direct loss `δh₀`;
- induced loss per forced miss `h₀k/(1 − k) + O(δ)`.

The note drops `h₀` in "each forced miss causes k/(1−k) further misses".
Three problems follow.

1. **The induced misses do not carry the forced miss's price.** They are
   other turns, the long-gap ones, with their own `n, K`. From
   `price_*.json`, the priced multiplier `lo/lo_forced` is 1.16 and 1.10,
   while the count multiplier is 1.21–1.22. The induced misses are priced
   at about three quarters of a forced miss each. The right first-order
   statement is
   `price ≈ h₀[Φ_forced + (k/(1−k)) Φ̄_induced]`,
   not `Φ/(1−k)`.
2. **How it composes with Proposition 1 (the bracket).**
   - Prop. 1 holds for *given* `q_i`. Feedback makes the total miss
     fraction endogenous: `q = q_forced + q_induced(q_forced)`.
   - The bracket applies to that total: lower end `λΣ q_i Φ_i`, upper end
     inflated by `(1 − ρ)/(1 − ρ')`, where ρ' includes the induced work.
   - So there are two amplifiers of different origin. The queue's is
     `(1 − ρ)/(1 − ρ')`, a second-order nonlinearity. The cache's is
     `1/(1 − k)`, first order, and it can diverge at low ρ. They
     multiply. They do not substitute for each other.
3. **The E2b price test already counts the induced misses.**
   - `lo` prices forced plus (forced-arm minus base) unforced misses.
     §4.3 says "the misses the change caused" and names the feedback.
   - So the corollary does not correct the paper's test. It is a *model*
     of `q_induced`.
   - The corollary becomes a claim only if `k` is predicted ex ante from
     `G` and `W` and then checked against the measured induced count.
   - For the record, the bracket with forced misses alone would still
     contain the observed rise (`ΔL_P/lo_forced` = 1.32 and 1.26 in
     aggregate). The price test does not discriminate between "feedback"
     and "no feedback" as it stands.

A useful point the note misses: if `k` is a property of the replica (one
number for all programs), then `1/(1−k)` scales every `u_i = p_iΦ_i/(c_iτ_i)`
by the same factor.

- It leaves the eviction *order* unchanged.
- It shifts only the comparison with θ: keep vs drop, admit vs refuse, and
  the offload threshold.
- That fits the paper's structure. The multiplier belongs to θ and
  admission (§3.3), not to the key.
- If the induced misses concentrate on long-absence programs, as they do
  here, the multiplier is program-specific, and then it can reorder.
  Worth one sentence.

### M6. The "consistency" section

- **The formula is right up to small corrections.** Under the affine map,
  (total loss)/(direct loss) = `1/(1 − (1 − δ)k)`, hence
  `k = (1 − direct/total)/(1 − δ)`. The note's version needs four
  corrections:
  - direct = `h₀ F`, not `F`;
  - the baseline's unforced misses should be scaled by the non-forced
    share `(1 − δ)` before being subtracted;
  - partial hits have to be treated consistently;
  - δ is the realised share (0.094–0.096 of follow-ups), not 0.10.
- **Recomputed values.**
  - Full runs, model-consistent (`(h₀ − h_δ)/(δ h₀)`): k = 0.179 and
    0.186.
  - The note's formula on full runs: 0.163 and 0.192.
  - The note's formula on the windowed counts: 0.196 and 0.200.
  - Poisson error on the induced count (52 ± 10): about ±0.04.
  - The numbers are robust at "about 0.15–0.2". The third digit is not
    meaningful.
- **With δ = 0.1 and a drop in `h` of 0.11, `k` is a chord slope of `H`**
  over `[h_δ, h₀]`, not `H'(h₀)`. The corollary needs the derivative.
  Report it as the secant.
- **"The feedback grows with load, as the model says" is not honest as
  written.**
  - Two loads. At 3.5 s, `k = 0` because the baseline has no misses at
    all. The survival of a 30 s absence is 1 there, and `G` is flat.
  - That is a corner, not a slope that has grown.
  - More importantly, the model's own channel (M2) predicts `k ≈ 0.01`,
    not 0.2. The data are consistent with *a* monotone feedback map. They
    are inconsistent with the one written down.
- **Suggested wording:** "positive at 2.5 s (about 0.15–0.2, a secant
  over a hit-rate drop of 0.11), zero at 3.5 s where no turn missed; the
  induced misses follow the 30 s think gaps and coincide with a 42 %
  higher insertion rate, so they run through the pool's eviction horizon
  rather than through the wait."

### M7. Literature: what must be cited, what is new

None of the structure is new. The note must say so and cite the following.
Rule 4: verify each one in the source before citing, and mark any not read
as UNVERIFIED. The entries below are ones I know. I have not re-read them
for this review.

- **Thrashing and load control.**
  - Denning, "Thrashing: its causes and prevention" (AFIPS FJCC 1968).
  - Courtois, "Decomposability, instabilities, and saturation in
    multiprogramming systems" (CACM 1975). Page-fault feedback gives
    multiple equilibria in multiprogramming, and the cure is a cap on the
    multiprogramming level. This is the closest ancestor of "the
    admission cap removes the collapse equilibrium".
- **Bistability and fixed-point approximations in loss networks.**
  - Gibbens, Hunt and Kelly, "Bistability in communication networks"
    (1990).
  - Kelly, "Loss networks" (Ann. Appl. Probab. 1991): the Erlang fixed
    point, its non-uniqueness under alternative routing, and trunk
    reservation as the control that restores a unique good equilibrium.
    That control is the analogue of the admission cap.
  - ALOHA bistability: Carleial and Hellman, IEEE Trans. Commun. 1975.
- **LRU survival.** Fagin 1977; Che, Tung and Wang (IEEE JSAC 2002);
  Fricker, Robert and Roberts (ITC 2012). The characteristic time and its
  dependence on the insertion rate: the right form for `G(T; h)` (M2).
- **Extremal equilibria and monotone comparative statics.** Tarski 1955;
  Topkis; Milgrom and Roberts, "Comparing equilibria" (AER 1994).
  Proposition 3 is their theorem in one dimension.
- **Metastable failures in systems.** Bronson et al. (HotOS 2021):
  retries and timeouts sustain an overloaded state after the trigger is
  gone. Optional.
- **Congestion instability in LLM serving.** `ao2026congestion` is
  already cited in §3.3, from the abstract only. Say precisely what it
  shows before claiming "the same instability without reuse".

**What is new** is narrow: coupling the prefix-cache survival with the
prefill queue and the agentic think-time loop, and reading the price of a
miss through a cache multiplier. That is enough for a paragraph and a
testable prediction. It is not enough for a section, and not for four new
propositions.

## Minor issues

- m1. The worked example has one wrong number. At λ = 0.25, ρ(h) =
  0.25(5 − 4.5h) < 1 iff h > 2/9, so `H = 0` on `[0, 0.222)`, not
  `h < 0.056`. Everything else reproduces:
  - λ = 0.25: equilibria 0, 0.2496 (H' = 12.0, W = 76 s) and 0.8820
    (H' = 0.073, W = 0.53 s);
  - λ = 0.18: 0.8848 (H' = 0.045).
  - Also: at λ = 0.20 the all-miss load is exactly 1, and the collapse and
    a second unstable point at h ≈ 0.010 still exist. The collapse
    disappears only for λ < 0.2.
- m2. In the example, the good equilibrium's slope is 0.07. That is the
  model's own statement that the wait channel is weak at a healthy
  operating point. It supports M2.
- m3. Proposition 1(ii) says "(ii) is (iii) with a = 0". It also needs
  `H(0) ≥ 0` and `H(1) ≤ 1`. Lean has them via `hmaps`. Say so in the
  prose.
- m4. Proposition 4 needs `0 ≤ δ ≤ 1` for the interpretation.
  `forced_miss_equilibrium` has only `0 ≤ δ`. This is harmless: the
  equation holds algebraically.
- m5. The "Why" section states the long-context eviction-while-waiting as
  observed. It is memory-model output (M2). Also, "strict FCFS admission
  evicted … theirs among them" should say "in the model".
- m6. The corollary is headed "the price of a miss with feedback" but is
  first order in δ. Say "marginal" in the heading.
- m7. The status line says "in the axiom audit": confirmed. Add
  `research/analytic-memory.md` to the `research/research-plan.md` "where we are"
  list, so a fresh session knows it exists and that it is not in the
  paper.
- m8. §3.3 of the paper already asserts the instability ("compete
  unstably") and §4.3 names "the feedback of §3.3". Whatever form this
  takes, those two sentences must agree with it. Currently the paper's
  sentence is the pool channel, and the note's is the wait channel.

## What it would take to enter the paper

- **No new proposition boxes.** AGENTS.md fixes four propositions and
  forbids re-promoting demoted facts. None of Propositions 1–4 here clears
  that bar on its own: two are the IVT, one is a tautology, one is affine
  algebra.
- **Right place and form: §3.3 (admission), one paragraph of prose.**
  1. The realised hit rate is a monotone function of itself,
     `h = E[G(Z + W(h); h)]`, so least and greatest equilibria exist, and
     any change that raises the map raises both. Inline `\provedby` of the
     Tarski theorems (to be written), with Courtois/Kelly cited for the
     phenomenon.
  2. At the good equilibrium the price of a miss scales by the cache
     multiplier: a first-order sentence with inline `\provedby` of
     `forced_miss_amplified`. State that it moves θ comparisons, not the
     eviction order.
  3. The admission cap acts on the low equilibrium. For the closed model,
     state it for the population `N`, with a Lean-proved condition, or say
     it in words without a number.
- **No worked-example numbers in the paper** unless the sign changes are
  proved in Lean (e.g. `H(0.2) < 0.2`, `H(0.3) > 0.3`, `H(0.95) < 0.95`
  at λ = 0.25, with exp bounds: feasible). Otherwise drop them. Rule 1
  covers derived numbers in prose.
- **The implied k** is a testbed-derived number. If it appears, it must
  come from a script into `paper/exp/` via `make exp` (e.g. a macro
  `\eTwobImpliedK`), never typed. And only with the M6 wording.
- Given the page budget and the fact that the §4.3 price test does not
  discriminate feedback, my advice is to **hold the paragraph until the
  test below has run**. Until then keep only the existing sentences, with
  m8 fixed.

## The most informative next test

The key question is which channel carries the feedback, and whether the
map has the predicted shape. Register all predictions before the run, as
in memory-model round 3. Everything is at the 2.5 s short-context load,
where `k > 0`, with the same trace family.

1. **Channel separation (two arms plus the existing base and forced
   arms).**
   - (a) *Insertion only.* Inject cold filler prompts from nonce sessions
     that never return, matching the forced arm's extra inserted tokens
     per second per rank (≈ +480 tok/s), with 1-token outputs spread over
     time.
   - (b) *Absence only.* Delay each returning turn at the client by the
     forced arm's extra mean wait (≈ 0.5 s), with no extra work.
   - Prediction from M2: (a) reproduces most of the induced misses on 30 s
     gaps, and (b) almost none.
   - If (b) does most of the work instead, the note's model stands and M2
     is wrong.
2. **Dose response.** δ ∈ {0.05, 0.10, 0.20} (two seeds each).
   - The affine model predicts `h₀ − h_δ = δh₀/(1 − (1 − δ)k)` with *one*
     `k`. Curvature measures `H''`.
   - Predict `k` beforehand from a `G(T; h)` estimated on the base arms.
     That needs absences spread around the horizon: re-derive the trace
     with think gaps uncapped or jittered around 20–40 s, since the
     current trace's 30 s atom leaves `G` observable at one point only.
3. **Bistability / hysteresis** (only after 1–2, and only where the
   closed-population model predicts two equilibria).
   - Ramp the session spacing down and then up, or apply a transient
     burst (δ = 0.5 for 60 s, then δ = 0).
   - A hysteresis loop in the hit rate is the signature. Recovery after
     the burst refutes bistability at that load.
   - Because s15_base is spent, this is a new registered run.

The analysis above needs no new server time to repeat. The diagnostics
behind M2 and M6 can go into a small `scripts/exp/analyze_feedback.py`, so
that the numbers quoted in the note are regenerable.

## Action list

1. Re-specify the model: `H(h) = E_Z[G(Z + W(h); h)]`, with `G` antitone
   in the absence and monotone in `h` (the pool channel). Name the wait
   channel a hypothesis for the long-context regime (M2, M4).
2. Replace the IVT-based structure with Knaster–Tarski in Lean: least and
   greatest equilibria without continuity, monotonicity of the gfp/lfp in
   the map, monotone convergence of the iteration from 1 and 0 under
   one-sided continuity, and a bistability statement (M1).
3. Formalise the PK instance: the piecewise `H_pk`, its monotonicity from
   `pkWait_mixture_antitone`, `H_pk = 0` on `[0, h_c)`, and `H_pk 0 = 0`
   from `λ S_miss ≥ 1`. Replace the tautological `feedback_collapse` (M1).
4. Restate collapse and admission for the closed population (finite `N`).
   Fix the "λ = 0.18 is a cap" wording and the comparative-statics list
   (M3).
5. Rewrite the corollary: keep `h₀`, separate `Φ_forced` from
   `Φ̄_induced`, and show how it composes with the bracket and its
   `(1−ρ)/(1−ρ')`. Note that a common `k` does not change the eviction
   order (M5).
6. Rewrite the consistency section with the corrected formula, the
   recomputed values with error bars, "secant", and the M6 wording. Add
   the 30 s-gap table and the insertion-rate numbers. Generate them with
   a script (M2, M6).
7. Fix m1 (h < 2/9) and m3–m8. Reconcile §3.3/§4.3's feedback sentences
   with whichever channel the tests support.
8. Add the literature of M7 to the note, each checked in the source or
   marked UNVERIFIED.
9. Register and run the channel-separation test, then the dose response
   on a trace with spread think gaps, and only then any bistability test.
10. Paper: nothing now. After items 1–9, at most one §3.3 paragraph with
    inline `\provedby` and no new proposition box.
