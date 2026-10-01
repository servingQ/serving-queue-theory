# Metastability of a prefix cache under load (serQ issue #120)

Status: 2026-10-01, **lecture note only** (Lecture 7 of
`lectures/queueing-serving/notes.tex`, at the user's request), not in the paper.
Lean: `lean/ServingQueueTheory/CacheOrder.lean` (what LRU keeps under FCFS) and
`Metastability.lean` (birth–death tools, open stability, admit-then-hold), all in
the axiom audit. Numerics and simulation, all generated:

| script | output |
|---|---|
| `scripts/metastability_ctmc.py` | exact CTMC tables → `metastability-tables.tex`, `research/metastability-results.json` |
| `scripts/metastability_serq.py` | serQ v0.1.0 runs of `lectures/queueing-serving/programs/metastable.sq` → `research/metastability-serq.json` |
| `scripts/metastability_figs.py` | figures `fig-meta-{drift,recovery,region,burst,sweep}.pdf`, `metastability-figs.tex` |
| `scripts/metastability_failure.py` | Gillespie sample paths of a burst → `fig-meta-failure.pdf`, `metastability-failure.tex`, `research/metastability-failure.json` |
| `scripts/metastability_calibration.py` | calibration against serQ → `fig-meta-calibration.pdf`, `metastability-exp.tex`, `research/metastability-calibration.json` |

Nothing here is a measurement (rule 7): CTMC numbers are exact model output,
serQ runs are a discrete-event model of vLLM's scheduler.

## Source read

Alvaro, Isaacs, Majumdar, Muniswamy-Reddy, Salamati, Soudjani, *Formal Analysis
of Metastable Failures in Software Systems*, arXiv:2510.03551 v2 (arXiv HTML,
read 2026-10-01, through a summariser plus verbatim quotes of Def. 5.1, Thm 5.2,
the (u, v) state and the drift definition of §5.1). Their experiments:
calibration by CMA-ES (§4, §6.1), drift visualisation (§5.1, §6.2), parameter
sensitivity of the two hitting times (§6.2, Fig. 13), recovery policies (§6.3),
a two-server pipeline (§6.4). We repeat drift, recovery vs. initial state,
region of metastability, and calibration with held-out bursts; the user asked
for the main ones only. The OSDI 2022 paper and the four related papers named
in the issue were not read; no novelty claim.

## Results

Proved (Lean names):
1. **Mattson's stack-distance criterion** (`mattson_lru_hit_iff`; cited prose in
   the lecture, not a proposition): under LRU a session hits iff fewer than `C`
   distinct sessions were served since its last turn. Under FCFS with one
   outstanding turn per session, a turn behind `C` waiting turns misses.
2. **Saturated rounds** (`lru_round_robin_all_miss`, `round_hits_le_capacity`,
   `pinned_round_hits`): round-robin with `N > C`, from an empty cache: LRU 0
   hits; any rule at most `C` per round; pinning `C` sessions attains `C`.
3. **The closed FCFS–LRU replica** (`closed_fcfs_lru_rises_iff`,
   `closed_fcfs_lru_no_congested_mode`): with completion rate `1/S_miss` above
   `C` (queue-length analogue, assumed), the queue law peaks at `N − Z/S_miss`
   above the cache, and `N ≤ C + Z/S_miss` admitted sessions leave no congested
   mode: an admission rule. For serQ's replica it binds at
   `Z* = (N − C) S_miss ≈ 2.5 s` with C the whole pool (32.6 contexts), inside
   the simulated cliff (full-reuse hit rate 0.67, 0.31, 0.03 at Z = 3, 2.5, 2 s):
   it marks the collapse, not the onset, and the fitted C = 38 would put it
   below 1 s. An order-of-magnitude check, not a fit. Open limit (remark only): stable iff `λ S_miss < 1` for
   every `C` (`fcfs_lru_open_stable_iff`).
4. **Admit, then hold** (`admission_hold_service_le`,
   `admission_hold_recovery_le`, `admission_hold_no_trough`): memory taken at
   admission (cap `B`) never slows service or recovery, and the queue law has no
   trough above `B`, so every barrier lies at or below `B`. It does **not**
   exclude a congested mode: with large enough `a B` losses start below `B` and
   a mode above `B` is possible (round-2 review counterexample).
5. Tools: product form, passage times, locality/monotonicity, Arrhenius lower
   bound, d'Alembert (`bd_*`, `passTime_*`, `recoveryTime_*`,
   `open_wait_loss_stable_iff_ratio_test`, …); `recovery_ranking_flip` is kept in
   Lean but no longer in the lecture.

Numerical (exact chain or serQ):
- Metastable failure in time: a=1.2, Z=42.5 s, 60 s burst at Z=12 s. Exact
  laws (`expm_multiply`): congested with probability 0.93 at 1000 s and 0.60
  at 3000 s when waiting turns hold memory, against 0.10 at 3000 s without the
  burst (stationary 0.18); 0.04 at 1000 s and 0.00 at 3000 s with memory taken
  at admission (B=16). 40 Gillespie paths for the picture only.
- Queue-and-cache chain (N=40, Z=27, C=48, a=1): closed class of 297 of
  12 341 states (h ≤ 8, c ≡ 0; reviewer finding); lumped chain exact for the
  marginal, optimistic ×3 for recovery; warm vs flushed start 0.005 vs 0.96.
- Region: bimodal only for a ≥ 1 (memory per waiting turn ≈ one context).
- serQ (vLLM rules, admission-time allocation): cliff without hysteresis;
  recovery 40–50 s after bursts.
- serQ hits are now full-reuse hits (`full_hit`; the library's `hit` counts any
  reuse): 0.77 at Z=4 s, 0.00 at Z=1.5 s.
- Calibration (round-2 fixes: same 25 s windows for both, two-parameter grids
  for both chains, service times derived from serQ, full-reuse target): PS
  chain cannot fit (RMSE 0.36); the one-at-a-time chain (random order among
  the waiting turns, evicted turn at the head) fits partly (C=38 above the
  physical 32.6, β=12 at the grid edge, RMSE 0.12, 0.16 vs 0.00 at the highest
  load) and recovers from the held-out bursts in 65/75 s vs serQ 40/50 s.

## serQ issues filed (2026-10-01)

- vrvrv/serQ#230: a hold nested in a hold on the same pool loses the session's
  cached prefix (blocked the reservation-on-arrival experiment in serQ).
- vrvrv/serQ#231: a session attribute silently shadows a context variable
  (`present`), PS capacity 8× off; same class as the old PD lecture bug.
- vrvrv/serQ#232: diagnostics umbrella (lints, degenerate-observe note, state
  sampling, `--version`).

## Next

1. The positive prediction: an engine that holds a prompt's blocks while the
   turn waits (PD decoder waiting for a KV transfer) should be metastable.
   serQ #230 is fixed in v0.1.1 (IR 10, serQ #234), now pinned; or the PD program `llmd_nixl_pull.sq`.
2. Measure the loss onset, `C − N` and memory per waiting turn on the testbed
   with the burst protocol, predictions registered first.
3. A concurrency cost of pinning (Exercise 7.3).
4. Read PEEK, Continuum, 2605.04595, 2606.15555 before any novelty claim.
