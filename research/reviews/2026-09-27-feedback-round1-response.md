# Response to the miss-feedback review, round 1 (2026-09-27)

| # | Action | Done | Where |
|---|--------|------|-------|
| 1 | Re-specify with both channels; wait channel a hypothesis | yes | analytic-memory.md "The model": `H(h) = E_Z[G(Z + W(h); h)]`; `feedback_map_monotone_two_channel`; the long-context eviction-while-waiting is marked model output |
| 2 | Knaster–Tarski in Lean | yes | `feedback_extremal`, `feedback_gfp_mono`, `feedback_lfp_mono`, `feedback_bistable`; on [0,1]: `unit_feedback_extremal`, `unit_feedback_greatest_mono`, `unit_feedback_bistable` (no continuity). Convergence of the iteration is not formalised |
| 3 | PK instance; drop the tautology | yes | `pkFeedback`, `pkFeedback_monotoneOn` (from `pkWait_mixture_antitone`), `pkFeedback_zero_of_overload`, `pkFeedback_collapse` (from `λ S_miss ≥ 1`); `feedback_collapse` removed |
| 4 | Closed population; cap wording; comparative-statics list | yes (prose) | result 2 and 3: closed loop gives a low-hit equilibrium; signs of Z and decode changes undetermined in a closed loop; "λ = 0.18 is a lower offered rate", a cap is a finite N. The closed-population condition on N is not derived |
| 5 | Corollary | yes | `h₀[Φ_forced + (k/(1−k)) Φ̄_induced]`; composition with the bracket; the price test does not discriminate; a common k does not change the eviction order |
| 6 | Consistency section with a script | yes | `scripts/exp/analyze_feedback.py` → `data/exp/e2b/feedback.json`: k secant 0.18 [0.16, 0.20] and 0.19 [0.16, 0.21], 0.01 at 3.5 s; the 30 s-gap table; +42 % insertion; absence vs own-wait insertions; your wording. New: a threshold (characteristic-time) test of the pool channel overshoots the forced arm's long-gap misses twofold (0.47/0.54 predicted, 0.21/0.25 observed) |
| 7 | m1, m3–m8 | yes | 2/9; λ = 0.20 row recomputed (0, 0.0103, 0.8841); m3 in result 1; m4 δ ∈ [0,1] in result 4; m5, m6 wording; m7 research-plan pointer; m8 paper section notes the pool channel as the supported one |
| 8 | Literature | listed, UNVERIFIED | none read; marked as such |
| 9 | Registered tests | planned | channel separation, dose response on spread gaps, then hysteresis; need a committed registration |
| 10 | Paper | nothing | as advised |
