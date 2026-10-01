/-
# Metastability of a replica that loses prefixes while it is congested

Research module for serQ issue #120 (`research/metastability.md`), not in the
paper. It recasts the CTMC analysis of metastable failures of Alvaro et al.
(arXiv:2510.03551) for a prefill queue whose work grows with its own length:
a turn that waits longer is more likely to find its prefix evicted, so the mean
service time `s n` at queue length `n` rises from the hit work toward the miss
work. Projected on the queue length the replica is a birth–death chain with
birth rate `up n` (`λ` open, `(N - n)/Z` closed) and death rate `down n = 1/s n`.

Key theorems:
* `bd_detailed_balance` — the product-form stationary weights satisfy detailed
  balance.
* `bd_weight_le_iff`, `bd_local_mode_iff` — the stationary law rises exactly
  where births outpace deaths; its local modes are the downward crossings of
  the fluid drift (the metastable states).
* `passTime_first_step`, `passTime_top`, `passTime_unique` — the closed form of
  the mean time to step down one level solves, and is the only solution of, the
  first-step equations of the finite chain.
* `passTime_congr`, `recoveryTime_congr` — locality: the time to recover from
  level `m` to level `n` depends on the rates at levels above `n` only.
* `passTime_mono`, `recoveryTime_mono` — faster service or fewer arrivals at the
  levels above `n` never lengthen the recovery.
* `passTime_ge_barrier` — the elementary half of the Arrhenius law: stepping
  down past level `k` takes at least the stationary mass ratio of any higher
  level to level `k`, over the death rate at `k`.
* `open_wait_loss_stable_iff_ratio_test` — d'Alembert's ratio test on the
  stationary weights: if the service time tends to the miss work, the open queue
  has a stationary law when `λ S_miss < 1` and none when `λ S_miss > 1`,
  whatever the hit work and however late the losses start.
* `open_stability_tail_only` — two service profiles that agree beyond some
  queue length have a stationary law together or not at all.
* `recovery_ranking_flip` — an intervention can lower the stationary mean queue
  more than another and yet lengthen the recovery from a burst.
-/
import Mathlib.Tactic
import Mathlib.Analysis.SpecificLimits.Normed

open Finset Filter Topology

namespace ServingQueueTheory

/-! ### Birth–death chains -/

/-- `bdRatio up down k j`: stationary mass of level `k + j` relative to level
`k`, for birth rate `up i` out of level `i` and death rate `down i` out of
level `i`. -/
noncomputable def bdRatio (up down : ℕ → ℝ) (k : ℕ) : ℕ → ℝ
  | 0 => 1
  | j + 1 => bdRatio up down k j * (up (k + j) / down (k + j + 1))

/-- Stationary weights relative to the empty level. -/
noncomputable abbrev bdWeight (up down : ℕ → ℝ) (n : ℕ) : ℝ := bdRatio up down 0 n

theorem bdWeight_succ (up down : ℕ → ℝ) (n : ℕ) :
    bdWeight up down (n + 1) = bdWeight up down n * (up n / down (n + 1)) := by
  simp [bdWeight, bdRatio]

/-- Detailed balance: the flow up out of `n` equals the flow down out of `n+1`. -/
theorem bd_detailed_balance (up down : ℕ → ℝ) (n : ℕ) (hd : down (n + 1) ≠ 0) :
    bdWeight up down n * up n = bdWeight up down (n + 1) * down (n + 1) := by
  rw [bdWeight_succ]; field_simp

theorem bdRatio_nonneg (up down : ℕ → ℝ) (k : ℕ) (hu : ∀ i, 0 ≤ up i)
    (hd : ∀ i, 0 ≤ down i) (j : ℕ) : 0 ≤ bdRatio up down k j := by
  induction j with
  | zero => simp [bdRatio]
  | succ j ih => exact mul_nonneg ih (div_nonneg (hu _) (hd _))

/-- Nonnegativity from the rates at levels `≥ k` only. -/
theorem bdRatio_nonneg_from (up down : ℕ → ℝ) (k : ℕ) (hu : ∀ i, k ≤ i → 0 ≤ up i)
    (hd : ∀ i, k ≤ i → 0 ≤ down i) (j : ℕ) : 0 ≤ bdRatio up down k j := by
  induction j with
  | zero => simp [bdRatio]
  | succ j ih => exact mul_nonneg ih (div_nonneg (hu _ (by omega)) (hd _ (by omega)))

theorem bdRatio_pos (up down : ℕ → ℝ) (k : ℕ) (hu : ∀ i, 0 < up i)
    (hd : ∀ i, 0 < down i) (j : ℕ) : 0 < bdRatio up down k j := by
  induction j with
  | zero => simp [bdRatio]
  | succ j ih => exact mul_pos ih (div_pos (hu _) (hd _))

/-- The stationary law rises from `n` to `n+1` exactly when the birth rate out
of `n` is at least the death rate out of `n+1` (the fluid drift is upward). -/
theorem bd_weight_le_iff (up down : ℕ → ℝ) (n : ℕ) (hw : 0 < bdWeight up down n)
    (hd : 0 < down (n + 1)) :
    bdWeight up down n ≤ bdWeight up down (n + 1) ↔ down (n + 1) ≤ up n := by
  rw [bdWeight_succ, le_mul_iff_one_le_right hw, one_le_div hd]

/-- A level `n ≥ 1` is a local mode of the stationary law exactly when the
drift points up just below it and down just above it. -/
theorem bd_local_mode_iff (up down : ℕ → ℝ) (n : ℕ) (hu : ∀ i, 0 < up i)
    (hd : ∀ i, 0 < down i) :
    (bdWeight up down n ≤ bdWeight up down (n + 1) ∧
        bdWeight up down (n + 2) ≤ bdWeight up down (n + 1)) ↔
      (down (n + 1) ≤ up n ∧ up (n + 1) ≤ down (n + 2)) := by
  have hw : ∀ m, 0 < bdWeight up down m := bdRatio_pos up down 0 hu hd
  constructor
  · rintro ⟨h1, h2⟩
    refine ⟨(bd_weight_le_iff up down n (hw n) (hd _)).1 h1, ?_⟩
    by_contra h
    push Not at h
    have : bdWeight up down (n + 1) < bdWeight up down (n + 2) := by
      rw [bdWeight_succ up down (n + 1), lt_mul_iff_one_lt_right (hw _),
        one_lt_div (hd _)]
      exact h
    linarith
  · rintro ⟨h1, h2⟩
    refine ⟨(bd_weight_le_iff up down n (hw n) (hd _)).2 h1, ?_⟩
    rw [bdWeight_succ up down (n + 1)]
    calc bdWeight up down (n + 1) * (up (n + 1) / down (n + 1 + 1))
        ≤ bdWeight up down (n + 1) * 1 := by
          apply mul_le_mul_of_nonneg_left _ (hw _).le
          rw [div_le_one (hd _)]; exact h2
      _ = bdWeight up down (n + 1) := mul_one _

theorem bdRatio_shift (up down : ℕ → ℝ) (k j : ℕ) :
    bdRatio up down k (j + 1) = (up k / down (k + 1)) * bdRatio up down (k + 1) j := by
  induction j with
  | zero => simp [bdRatio]
  | succ j ih =>
    rw [bdRatio, ih, bdRatio]
    have h1 : k + 1 + j = k + (j + 1) := by omega
    rw [h1]; ring

/-! ### Passage and recovery times of the finite chain on `{0, …, M}` -/

/-- Mean time to step down from level `k` to level `k - 1` in the chain on
`{0, …, M}`: the stationary mass at and above `k`, relative to `k`, over the
death rate at `k`. -/
noncomputable def passTime (up down : ℕ → ℝ) (M k : ℕ) : ℝ :=
  (∑ j ∈ range (M + 1 - k), bdRatio up down k j) / down k

/-- Mean time to recover from level `m` to level `n` (`n ≤ m`): one downward
passage per level crossed. -/
noncomputable def recoveryTime (up down : ℕ → ℝ) (M m n : ℕ) : ℝ :=
  ∑ k ∈ Ico (n + 1) (m + 1), passTime up down M k

/-- At the top level the only move is down. -/
theorem passTime_top (up down : ℕ → ℝ) (M : ℕ) (hd : down M ≠ 0) :
    down M * passTime up down M M = 1 := by
  simp [passTime, bdRatio]; field_simp

/-- First-step equation below the top: `μ_k T_k = 1 + λ_k T_{k+1}`. -/
theorem passTime_first_step (up down : ℕ → ℝ) (M k : ℕ) (hk : k < M)
    (hd : down k ≠ 0) (hd' : down (k + 1) ≠ 0) :
    down k * passTime up down M k = 1 + up k * passTime up down M (k + 1) := by
  have hM : M + 1 - k = (M + 1 - (k + 1)) + 1 := by omega
  unfold passTime
  rw [hM, sum_range_succ']
  simp only [bdRatio_shift, ← mul_sum]
  simp only [bdRatio]
  field_simp
  ring

/-- The closed form is the only solution of the first-step equations. -/
theorem passTime_unique (up down : ℕ → ℝ) (M : ℕ) (T : ℕ → ℝ)
    (hd : ∀ i, down i ≠ 0) (htop : down M * T M = 1)
    (hstep : ∀ k < M, down k * T k = 1 + up k * T (k + 1)) :
    ∀ k ≤ M, T k = passTime up down M k := by
  have key : ∀ d k, k + d = M → T k = passTime up down M k := by
    intro d
    induction d with
    | zero =>
      intro k hk
      simp at hk; subst hk
      have h := passTime_top up down k (hd k)
      exact mul_left_cancel₀ (hd k) (htop.trans h.symm)
    | succ d ih =>
      intro k hk
      have hkM : k < M := by omega
      have h1 := hstep k hkM
      have h2 := passTime_first_step up down M k hkM (hd k) (hd (k + 1))
      rw [ih (k + 1) (by omega)] at h1
      exact mul_left_cancel₀ (hd k) (h1.trans h2.symm)
  intro k hk
  exact key (M - k) k (by omega)

/-- Locality of the ratio: it reads the rates at levels `≥ k` only. -/
theorem bdRatio_congr (up down up' down' : ℕ → ℝ) (k : ℕ)
    (h : ∀ i, k ≤ i → up i = up' i ∧ down i = down' i) (j : ℕ) :
    bdRatio up down k j = bdRatio up' down' k j := by
  induction j with
  | zero => simp [bdRatio]
  | succ j ih =>
    simp only [bdRatio, ih, (h (k + j) (by omega)).1, (h (k + j + 1) (by omega)).2]

theorem passTime_congr (up down up' down' : ℕ → ℝ) (M k : ℕ)
    (h : ∀ i, k ≤ i → up i = up' i ∧ down i = down' i) :
    passTime up down M k = passTime up' down' M k := by
  unfold passTime
  rw [(h k le_rfl).2]
  congr 1
  exact sum_congr rfl fun j _ => bdRatio_congr up down up' down' k h j

/-- Locality of recovery: changing the rates at levels `≤ n` (for instance,
speeding up the hit path, which only the lightly loaded levels use) leaves the
recovery time from any burst level down to `n` unchanged. -/
theorem recoveryTime_congr (up down up' down' : ℕ → ℝ) (M m n : ℕ)
    (h : ∀ i, n < i → up i = up' i ∧ down i = down' i) :
    recoveryTime up down M m n = recoveryTime up' down' M m n := by
  unfold recoveryTime
  refine sum_congr rfl fun k hk => passTime_congr _ _ _ _ M k fun i hi => h i ?_
  simp only [mem_Ico] at hk; omega

theorem bdRatio_mono (up down up' down' : ℕ → ℝ) (k : ℕ)
    (hu : ∀ i, k ≤ i → 0 ≤ up i ∧ up i ≤ up' i)
    (hd : ∀ i, k ≤ i → 0 < down' i ∧ down' i ≤ down i) (j : ℕ) :
    bdRatio up down k j ≤ bdRatio up' down' k j := by
  induction j with
  | zero => simp [bdRatio]
  | succ j ih =>
    simp only [bdRatio]
    have h0 : 0 ≤ bdRatio up down k j :=
      bdRatio_nonneg_from up down k (fun i hi => (hu i hi).1)
        (fun i hi => (hd i hi).1.le.trans (hd i hi).2) j
    obtain ⟨hu0, hu1⟩ := hu (k + j) (by omega)
    obtain ⟨hd0, hd1⟩ := hd (k + j + 1) (by omega)
    apply mul_le_mul ih (div_le_div₀ (hu0.trans hu1) hu1 hd0 hd1)
      (div_nonneg hu0 (hd0.le.trans hd1)) (h0.trans ih)

/-- Faster service (higher death rates) and fewer arrivals at the levels at or
above `k` never lengthen the passage down from `k`. -/
theorem passTime_mono (up down up' down' : ℕ → ℝ) (M k : ℕ)
    (hu : ∀ i, k ≤ i → 0 ≤ up i ∧ up i ≤ up' i)
    (hd : ∀ i, k ≤ i → 0 < down' i ∧ down' i ≤ down i) :
    passTime up down M k ≤ passTime up' down' M k := by
  unfold passTime
  have hs : ∑ j ∈ range (M + 1 - k), bdRatio up down k j ≤
      ∑ j ∈ range (M + 1 - k), bdRatio up' down' k j :=
    sum_le_sum fun j _ => bdRatio_mono up down up' down' k hu hd j
  have h0 : 0 ≤ ∑ j ∈ range (M + 1 - k), bdRatio up down k j := by
    exact sum_nonneg fun j _ => bdRatio_nonneg_from up down k (fun i hi => (hu i hi).1)
      (fun i hi => (hd i hi).1.le.trans (hd i hi).2) j
  exact div_le_div₀ (h0.trans hs) hs (hd k le_rfl).1 (hd k le_rfl).2

/-- Recovery from `m` to `n` reads only the levels above `n`, and is shortened
by faster service and fewer arrivals there. -/
theorem recoveryTime_mono (up down up' down' : ℕ → ℝ) (M m n : ℕ)
    (hu : ∀ i, n < i → 0 ≤ up i ∧ up i ≤ up' i)
    (hd : ∀ i, n < i → 0 < down' i ∧ down' i ≤ down i) :
    recoveryTime up down M m n ≤ recoveryTime up' down' M m n := by
  unfold recoveryTime
  refine sum_le_sum fun k hk => passTime_mono _ _ _ _ M k (fun i hi => hu i ?_)
    (fun i hi => hd i ?_)
  all_goals simp only [mem_Ico] at hk; omega

/-- The elementary half of the Arrhenius law: the passage down from `k` takes
at least the stationary mass of level `k + j` relative to `k`, over the death
rate at `k`. With a bad mode at `k + j` and a saddle at `k` the ratio is the
exponential of the barrier. -/
theorem passTime_ge_barrier (up down : ℕ → ℝ) (M k j : ℕ) (hj : j < M + 1 - k)
    (hu : ∀ i, k ≤ i → 0 ≤ up i) (hd : ∀ i, k ≤ i → 0 < down i) :
    bdRatio up down k j / down k ≤ passTime up down M k := by
  unfold passTime
  apply div_le_div_of_nonneg_right _ (hd k le_rfl).le
  exact single_le_sum (f := fun j => bdRatio up down k j)
    (fun i _ => bdRatio_nonneg_from up down k hu (fun i hi => (hd i hi).le) i)
    (mem_range.2 hj)

/-- Stationary mean level of the chain on `{0, …, M}`. -/
noncomputable def bdMean (up down : ℕ → ℝ) (M : ℕ) : ℝ :=
  (∑ n ∈ range (M + 1), (n : ℝ) * bdWeight up down n) /
    ∑ n ∈ range (M + 1), bdWeight up down n

/-- Steady state and recovery rank interventions differently. On `{0, 1, 2}`
with unit arrival and service rates, quadrupling the service rate at level 1
(the lightly loaded level) halves the stationary mean, while doubling it at
level 2 (the congested level) lowers the mean less; but only the second
shortens the recovery from 2 to 1, which the first leaves unchanged
(`recoveryTime_congr`). -/
theorem recovery_ranking_flip :
    bdMean (fun _ => 1) (fun n => if n = 1 then 4 else 1) 2 = 1 / 2 ∧
      bdMean (fun _ => 1) (fun n => if n = 2 then 2 else 1) 2 = 4 / 5 ∧
      recoveryTime (fun _ => 1) (fun n => if n = 1 then 4 else 1) 2 2 1 = 1 ∧
      recoveryTime (fun _ => 1) (fun n => if n = 2 then 2 else 1) 2 2 1 = 1 / 2 := by
  refine ⟨?_, ?_, ?_, ?_⟩ <;>
    simp [bdMean, recoveryTime, passTime, bdWeight, bdRatio, sum_range_succ] <;> norm_num

/-! ### The open queue: stability is decided by the miss work -/

/-- Stationary weights of the open queue with arrival rate `lam` and mean
service time `s n` at queue length `n`. -/
noncomputable def openWeight (lam : ℝ) (s : ℕ → ℝ) : ℕ → ℝ
  | 0 => 1
  | n + 1 => openWeight lam s n * (lam * s (n + 1))

theorem openWeight_eq_bdWeight (lam : ℝ) (s : ℕ → ℝ) (n : ℕ) :
    openWeight lam s n = bdWeight (fun _ => lam) (fun i => 1 / s i) n := by
  induction n with
  | zero => simp [openWeight, bdWeight, bdRatio]
  | succ n ih => rw [openWeight, bdWeight_succ, ih]; field_simp

theorem openWeight_pos (lam : ℝ) (s : ℕ → ℝ) (hlam : 0 < lam) (hs : ∀ n, 0 < s n)
    (n : ℕ) : 0 < openWeight lam s n := by
  induction n with
  | zero => simp [openWeight]
  | succ n ih => exact mul_pos ih (mul_pos hlam (hs _))

/-- d'Alembert's ratio test on the stationary weights. If the mean service time
tends to `sMiss` as the queue grows, the open queue has a stationary law
(the weights are summable) when `lam * sMiss < 1` and none when
`lam * sMiss > 1`. -/
theorem open_wait_loss_stable_iff_ratio_test (lam sMiss : ℝ) (s : ℕ → ℝ)
    (hlam : 0 < lam) (hs : ∀ n, 0 < s n) (hlim : Tendsto s atTop (𝓝 sMiss)) :
    (lam * sMiss < 1 → Summable (openWeight lam s)) ∧
      (1 < lam * sMiss → ¬ Summable (openWeight lam s)) := by
  have hratio : (fun n => ‖openWeight lam s (n + 1)‖ / ‖openWeight lam s n‖) =
      fun n => lam * s (n + 1) := by
    funext n
    have hw := openWeight_pos lam s hlam hs n
    rw [Real.norm_of_nonneg (openWeight_pos lam s hlam hs (n + 1)).le,
      Real.norm_of_nonneg hw.le, openWeight]
    field_simp
  have ht : Tendsto (fun n => ‖openWeight lam s (n + 1)‖ / ‖openWeight lam s n‖)
      atTop (𝓝 (lam * sMiss)) := by
    rw [hratio]
    exact (hlim.comp (tendsto_add_atTop_nat 1)).const_mul lam
  refine ⟨fun h => summable_of_ratio_test_tendsto_lt_one h ?_ ht,
    fun h => not_summable_of_ratio_test_tendsto_gt_one h ht⟩
  exact Eventually.of_forall fun n => (openWeight_pos lam s hlam hs n).ne'

/-- The serving instance: the service time is the hit work plus the miss
probability `m n` times the extra work of a miss, and the miss probability of
a queued turn tends to one as the queue grows. Then stability is decided by
`lam * sMiss` alone; the hit work and the shape of `m` do not enter. -/
theorem open_wait_loss_stable_iff (lam sHit sMiss : ℝ) (m : ℕ → ℝ)
    (hlam : 0 < lam) (hHit : 0 < sHit) (hle : sHit ≤ sMiss)
    (hm : ∀ n, 0 ≤ m n) (hlim : Tendsto m atTop (𝓝 1)) :
    (lam * sMiss < 1 → Summable (openWeight lam fun n => sHit + m n * (sMiss - sHit))) ∧
      (1 < lam * sMiss →
        ¬ Summable (openWeight lam fun n => sHit + m n * (sMiss - sHit))) := by
  apply open_wait_loss_stable_iff_ratio_test lam sMiss _ hlam
  · intro n; have := mul_nonneg (hm n) (sub_nonneg.2 hle); linarith
  · have := (hlim.mul_const (sMiss - sHit)).const_add sHit
    simpa using this

/-- Two service profiles that agree beyond queue length `K` have a stationary
law together or not at all: KV capacity, pinning or a faster hit path, which
change only how early the losses start, cannot move the stability limit. -/
theorem open_stability_tail_only (lam : ℝ) (s s' : ℕ → ℝ) (K : ℕ) (hlam : 0 < lam)
    (hs : ∀ n, 0 < s n) (hs' : ∀ n, 0 < s' n) (hK : ∀ n, K < n → s n = s' n) :
    Summable (openWeight lam s) ↔ Summable (openWeight lam s') := by
  have hw := openWeight_pos lam s hlam hs
  have hw' := openWeight_pos lam s' hlam hs'
  have key : ∀ j, openWeight lam s' (j + K) =
      (openWeight lam s' K / openWeight lam s K) * openWeight lam s (j + K) := by
    intro j
    induction j with
    | zero => simp; field_simp [(hw K).ne']
    | succ j ih =>
      have e : j + 1 + K = (j + K) + 1 := by omega
      rw [e, openWeight, openWeight, ih, hK (j + K + 1) (by omega)]
      ring
  rw [← summable_nat_add_iff K, ← summable_nat_add_iff (f := openWeight lam s') K]
  constructor
  · intro h
    have := h.mul_left (openWeight lam s' K / openWeight lam s K)
    simpa [key] using this
  · intro h
    have h2 := h.mul_left (openWeight lam s K / openWeight lam s' K)
    refine h2.congr fun j => ?_
    rw [key]
    field_simp [(hw K).ne', (hw' K).ne']

end ServingQueueTheory
