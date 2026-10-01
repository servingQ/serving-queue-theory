# Metastability: the wait-loss feedback as dynamics (serQ issue #120)

Status: 2026-10-01, **lecture note only** (Lecture 7 of
`lectures/queueing-serving/notes.tex`, at the user's request), not in the paper.
Lean: `lean/ServingQueueTheory/Metastability.lean` (16 theorems in the axiom
audit). Numerics: `scripts/metastability_ctmc.py` →
`research/metastability-results.json` and the generated
`lectures/queueing-serving/metastability-tables.tex`. All numbers are exact
CTMC computations on models (no simulation, no measurement; rule 7).

## Source read

Alvaro, Isaacs, Majumdar, Muniswamy-Reddy, Salamati, Soudjani, *Formal Analysis
of Metastable Failures in Software Systems*, arXiv:2510.03551 v2 (read via the
arXiv HTML, 2026-10-01). What we use: state `(u, v)` = requests in the server
and queue, requests in the retry orbit; timeout probability rising with `u`;
the drift field `Σ Q((u,v),(u',v'))·(u'−u, v'−v)` (§5.1, "Qualitative
Analysis through Visualization"); ρ-metastability by escape probabilities
(Def. 5.1) and eigenvalues near 0 ↔ inverse mean hitting times (Thm 5.2);
recovery time as a mean hitting time. Metastable Failures in the Wild
(OSDI 2022) is named in the issue but has **not** been read; not cited.

## Mapping

| Alvaro et al. | here |
|---------------|------|
| queue `u` | prefill queue length `n` |
| orbit `v` (requests to retry) | lost prefixes: queued misses `m`, cold thinkers `c` |
| timeout probability `r(u)` ↑ | loss probability `m(n)` ↑ (LRU evicts waiting prefixes first) |
| a timeout adds **arrivals** | a loss adds **work**; turns are conserved |
| open arrivals | open `λ`, or closed `N` sessions with think time `Z` |

The change of mechanism changes the answers: the closed system is finite and
ergodic (metastability = slow mixing, never instability); projected on `n`
the chain is birth–death with closed-form passage times.

## Results

Proved (Lean names):
1. Modes of the stationary law = stable fluid equilibria
   (`bd_weight_le_iff`, `bd_local_mode_iff`).
2. Passage time `T_k = Σ_{j≥k} π_j/(π_k μ_k)`, unique solution of the
   first-step equations (`passTime_first_step`, `passTime_top`,
   `passTime_unique`).
3. Locality: recovery to level `n` reads only rates above `n`; monotone in them
   (`passTime_congr`, `recoveryTime_congr`, `passTime_mono`, `recoveryTime_mono`).
4. Arrhenius lower bound `T_k ≥ π_j/(π_k μ_k)` (`passTime_ge_barrier`).
5. **Open queue: stable iff `λ S_miss < 1`** (strictly; d'Alembert), whatever the
   hit work or the onset of losses; profiles equal beyond `K` are stable together
   (`open_wait_loss_stable_iff_ratio_test`, `open_wait_loss_stable_iff`,
   `open_stability_tail_only`). KV capacity, pinning and a faster hit path cannot
   move the limit; prefill speed and cheaper restore (reload) can.
6. Steady state and recovery rank interventions differently, 3-state example
   (`recovery_ranking_flip`).
7. (lecture proof only, not in Lean) Lumping onto a ±1 coordinate with
   stationary-averaged rates preserves the stationary marginal (cut equation).

Numerical (model, exact):
- Open, `S_hit=0.5`, `S_miss=5`, logistic `m` at 20: mean collapse time from
  empty `10^16.2` s at `λS_miss=1.05`, `10^3.2` s at 5. Mathematical
  instability vs practical lifetime: capacity planning needs the barrier.
- Closed, `Z=1.5N`, `m` at `N/4`: barrier ≈ 0.21 per session; recovery and
  1/gap exponential in `N` (8.5e3 s at N=20 → 2.5e17 s at N=160).
- Hysteresis (N=40): bimodal for 25 ≤ Z ≤ 120 s; collapse needs rate > N/25,
  recovery needs rate < N/120 (factor ≈ 5).
- 3D chain `(h, m, c)` (N=40, Z=27, C=48, a=1; 12 341 states): lumped chain
  matches the marginal to 3e-16 but its gap is 3.2× too large and its recovery
  time 418 s vs 1375 s; warm vs cold start at the same empty queue: P(bad at
  30 s) 0.005 vs 0.96. **Queue length is enough for steady state, not for
  dynamics**; the lost-prefix count is the slow variable (the orbit analogue).
- Burst (Z 27 → 12 s for B s): P(bad 600 s later) 0.35 → 0.62, saturating by
  B ≈ 60 s; ~1500 s back to an empty queue.
- Interventions (ranks by response / by recovery): prefill ×1.25 1/2; KV +4 3/1;
  hit path ×1.25 2/3; protect waiting φ=1 4/4; φ=0.5 5/5; miss path ×1.25 6/6.
  Steady-state and recovery winners differ. Protection is monotone in φ here
  because the chain has no cost of pinned memory.

## What is new relative to the issue's prior work

Narrow and conditional: (i) the open-queue stability limit under wait loss is
`1/S_miss` independent of cache size/protection, with the metastable band up to
`1/S_hit`; (ii) locality of recovery (interventions acting only on lightly
loaded states cannot shorten recovery); (iii) exact demonstration that a
queue-length model is stationary-exact but dynamically optimistic. Not checked
against PEEK, Continuum, 2605.04595, 2606.15555 (named in the issue, unread).

## Next

1. Measure `m(n)` (or the overflow slack `C − N` and per-turn memory `a`) on the
   testbed or with serQ's vLLM program; fit and predict the burst table before
   running it (registered).
2. Add a concurrency cost of pinning (Exercise 7.3) to answer "partial vs full
   protection".
3. FIFO instead of PS in the 3D chain; block-level LRU.
4. Read the four related papers named in the issue before any novelty claim.
