/-
# The price of a miss at a batching server

Proposition (paper `prop:decode`, §2.5).  The decode stage of a replica that runs continuous
batching with chunked prefill is modelled as a processor-sharing (PS)
station with capacity `φ n` when `n` turns share it.  Its stationary law is
`π n ∝ ρⁿ / (φ 1 ⋯ φ n)` and depends on the service distribution only
through the load `ρ = λ E[S]` (insensitivity; cited in the paper).

* `stationaryMean_mono` : for any nonnegative weights `a n` (e.g.
  `1 / (φ 1 ⋯ φ n)`), the mean of `π n ∝ a n ρⁿ` on `{0, …, N}` is
  nondecreasing in `ρ` (Prop. decode (i)).
* `ps_eviction_rank_by_work` : hence an eviction that adds less expected
  work leaves no more turns in the system, at every load (Prop. decode (i)).
* `psNum_diff_exact`, `psPrice_lower`, `psPrice_upper` : for constant
  capacity `C`, `L = ρ / (C - ρ)` and turning a fraction `q i` of arrivals
  into misses raises `L` by exactly `(C - ρ)/(C - ρ') · λ Σ q i Φ i` with
  `Φ i = C ΔS i / (C - ρ)²` (Prop. decode (ii)).
* `psPrice_unbounded` : `Φ` is unbounded as `ρ → C` (Prop. decode (iii)).
-/
import Mathlib.Tactic

namespace ServingQueueTheory

open Finset

/-! ### Any capacity function: the mean is monotone in the load. -/

/-- Mean of the distribution `π n ∝ a n ρⁿ` on `{0, …, N}`. -/
noncomputable def stationaryMean (a : ℕ → ℝ) (N : ℕ) (ρ : ℝ) : ℝ :=
  (∑ n ∈ range (N + 1), (n : ℝ) * a n * ρ ^ n) / (∑ n ∈ range (N + 1), a n * ρ ^ n)

/-- Pairwise term of the exchange argument. -/
theorem pair_term_nonneg {ρ₁ ρ₂ : ℝ} (h1 : 0 < ρ₁) (h12 : ρ₁ ≤ ρ₂) (n m : ℕ) :
    0 ≤ ((n : ℝ) - m) * (ρ₂ ^ n * ρ₁ ^ m - ρ₁ ^ n * ρ₂ ^ m) := by
  have h2 : 0 < ρ₂ := lt_of_lt_of_le h1 h12
  rcases le_total m n with h | h
  · obtain ⟨k, rfl⟩ := Nat.exists_eq_add_of_le h
    have hk : ρ₁ ^ k ≤ ρ₂ ^ k := pow_le_pow_left₀ h1.le h12 k
    have e : ((↑(m + k) : ℝ) - m) * (ρ₂ ^ (m + k) * ρ₁ ^ m - ρ₁ ^ (m + k) * ρ₂ ^ m)
        = (k : ℝ) * (ρ₁ ^ m * ρ₂ ^ m * (ρ₂ ^ k - ρ₁ ^ k)) := by
      push_cast; ring
    rw [e]
    apply mul_nonneg (by positivity)
    apply mul_nonneg (by positivity)
    linarith
  · obtain ⟨k, rfl⟩ := Nat.exists_eq_add_of_le h
    have hk : ρ₁ ^ k ≤ ρ₂ ^ k := pow_le_pow_left₀ h1.le h12 k
    have e : ((n : ℝ) - ↑(n + k)) * (ρ₂ ^ n * ρ₁ ^ (n + k) - ρ₁ ^ n * ρ₂ ^ (n + k))
        = (k : ℝ) * (ρ₁ ^ n * ρ₂ ^ n * (ρ₂ ^ k - ρ₁ ^ k)) := by
      push_cast; ring
    rw [e]
    apply mul_nonneg (by positivity)
    apply mul_nonneg (by positivity)
    linarith

/-- **Prop. decode (i), monotonicity.**  With nonnegative weights and
`a 0 > 0`, the stationary mean number is nondecreasing in the load. -/
theorem stationaryMean_mono (a : ℕ → ℝ) (N : ℕ) (ha : ∀ n, 0 ≤ a n) (ha0 : 0 < a 0)
    {ρ₁ ρ₂ : ℝ} (h1 : 0 < ρ₁) (h12 : ρ₁ ≤ ρ₂) :
    stationaryMean a N ρ₁ ≤ stationaryMean a N ρ₂ := by
  have h2 : 0 < ρ₂ := lt_of_lt_of_le h1 h12
  set s := range (N + 1) with hs
  have h0 : 0 ∈ s := by simp [hs]
  have hP : ∀ ρ : ℝ, 0 < ρ → 0 < ∑ n ∈ s, a n * ρ ^ n := by
    intro ρ hρ
    have hle : a 0 * ρ ^ 0 ≤ ∑ n ∈ s, a n * ρ ^ n :=
      Finset.single_le_sum (f := fun n => a n * ρ ^ n)
        (fun n _ => mul_nonneg (ha n) (pow_nonneg hρ.le n)) h0
    have : 0 < a 0 * ρ ^ 0 := by simpa using ha0
    linarith
  unfold stationaryMean
  rw [← hs, div_le_div_iff₀ (hP ρ₁ h1) (hP ρ₂ h2)]
  -- write both cross products as double sums
  set F : ℕ → ℕ → ℝ := fun n m => (n : ℝ) * a n * ρ₂ ^ n * (a m * ρ₁ ^ m) with hF
  set G : ℕ → ℕ → ℝ := fun n m => (n : ℝ) * a n * ρ₁ ^ n * (a m * ρ₂ ^ m) with hG
  have e1 : (∑ n ∈ s, (n : ℝ) * a n * ρ₂ ^ n) * (∑ n ∈ s, a n * ρ₁ ^ n)
      = ∑ n ∈ s, ∑ m ∈ s, F n m := Finset.sum_mul_sum _ _ _ _
  have e2 : (∑ n ∈ s, (n : ℝ) * a n * ρ₁ ^ n) * (∑ n ∈ s, a n * ρ₂ ^ n)
      = ∑ n ∈ s, ∑ m ∈ s, G n m := Finset.sum_mul_sum _ _ _ _
  have e1' : ∑ n ∈ s, ∑ m ∈ s, F n m = ∑ n ∈ s, ∑ m ∈ s, F m n := Finset.sum_comm
  have e2' : ∑ n ∈ s, ∑ m ∈ s, G n m = ∑ n ∈ s, ∑ m ∈ s, G m n := Finset.sum_comm
  have key : 0 ≤ ∑ n ∈ s, ∑ m ∈ s, ((F n m - G m n) + (F m n - G n m)) := by
    apply Finset.sum_nonneg; intro n _
    apply Finset.sum_nonneg; intro m _
    have e : (F n m - G m n) + (F m n - G n m)
        = a n * a m * (((n : ℝ) - m) * (ρ₂ ^ n * ρ₁ ^ m - ρ₁ ^ n * ρ₂ ^ m)) := by
      simp only [hF, hG]; ring
    rw [e]
    exact mul_nonneg (mul_nonneg (ha n) (ha m)) (pair_term_nonneg h1 h12 n m)
  simp only [Finset.sum_add_distrib, Finset.sum_sub_distrib] at key
  linarith

/-- **Prop. decode (i), ranking.**  At a PS server whose mean number depends
on the policy only through the load, an eviction that adds expected work
`A₁` per arrival is no worse than one that adds `A₂ ≥ A₁`, at every load. -/
theorem ps_eviction_rank_by_work (a : ℕ → ℝ) (N : ℕ) (ha : ∀ n, 0 ≤ a n) (ha0 : 0 < a 0)
    {ρ lam A₁ A₂ : ℝ} (hlam : 0 ≤ lam) (hpos : 0 < ρ + lam * A₁) (hA : A₁ ≤ A₂) :
    stationaryMean a N (ρ + lam * A₁) ≤ stationaryMean a N (ρ + lam * A₂) :=
  stationaryMean_mono a N ha ha0 hpos (by nlinarith)

/-! ### Constant capacity: the price in closed form. -/

/-- Mean number at an M/G/1-PS station of capacity `C`: `ρ / (C - ρ)`. -/
noncomputable def psNum (C ρ : ℝ) : ℝ := ρ / (C - ρ)

/-- The price of one miss at a PS server of capacity `C`. -/
noncomputable def psPrice (C ρ dS : ℝ) : ℝ := C * dS / (C - ρ) ^ 2

variable {ι : Type*}

/-- **Exact change.**  Turning a fraction `q i` of arrivals into misses
raises `L` by exactly `(C - ρ)/(C - ρ')` times the summed price. -/
theorem psNum_diff_exact (s : Finset ι) (q dS : ι → ℝ) {C ρ lam : ℝ} (hρ : ρ < C)
    (hstab : ρ + lam * ∑ i ∈ s, q i * dS i < C) :
    psNum C (ρ + lam * ∑ i ∈ s, q i * dS i) - psNum C ρ
      = (C - ρ) / (C - (ρ + lam * ∑ i ∈ s, q i * dS i))
          * (lam * ∑ i ∈ s, q i * psPrice C ρ (dS i)) := by
  unfold psNum psPrice
  have hsum : ∑ i ∈ s, q i * (C * dS i / (C - ρ) ^ 2)
      = C / (C - ρ) ^ 2 * ∑ i ∈ s, q i * dS i := by
    rw [Finset.mul_sum]
    refine Finset.sum_congr rfl fun i _ => ?_
    ring
  rw [hsum]
  set A := ∑ i ∈ s, q i * dS i
  have hu : C - ρ ≠ 0 := by linarith
  have hv : C - (ρ + lam * A) ≠ 0 := by linarith
  field_simp
  ring

/-- **Prop. decode (ii), lower bound.** -/
theorem psPrice_lower (s : Finset ι) (q dS : ι → ℝ) {C ρ lam : ℝ} (hlam : 0 ≤ lam)
    (hρ : ρ < C) (hq : ∀ i ∈ s, 0 ≤ q i) (hdS : ∀ i ∈ s, 0 ≤ dS i) (hC : 0 < C)
    (hstab : ρ + lam * ∑ i ∈ s, q i * dS i < C) :
    lam * ∑ i ∈ s, q i * psPrice C ρ (dS i)
      ≤ psNum C (ρ + lam * ∑ i ∈ s, q i * dS i) - psNum C ρ := by
  rw [psNum_diff_exact s q dS hρ hstab]
  have hA : 0 ≤ ∑ i ∈ s, q i * dS i :=
    Finset.sum_nonneg fun i hi => mul_nonneg (hq i hi) (hdS i hi)
  have hlin : 0 ≤ lam * ∑ i ∈ s, q i * psPrice C ρ (dS i) := by
    apply mul_nonneg hlam
    refine Finset.sum_nonneg fun i hi => mul_nonneg (hq i hi) ?_
    unfold psPrice
    have := hdS i hi
    positivity
  have hv : 0 < C - (ρ + lam * ∑ i ∈ s, q i * dS i) := by linarith
  have hratio : 1 ≤ (C - ρ) / (C - (ρ + lam * ∑ i ∈ s, q i * dS i)) := by
    rw [le_div_iff₀ hv]; nlinarith
  nlinarith

/-- **Prop. decode (ii), upper bound** (attained). -/
theorem psPrice_upper (s : Finset ι) (q dS : ι → ℝ) {C ρ lam : ℝ} (hρ : ρ < C)
    (hstab : ρ + lam * ∑ i ∈ s, q i * dS i < C) :
    psNum C (ρ + lam * ∑ i ∈ s, q i * dS i) - psNum C ρ
      ≤ (C - ρ) / (C - (ρ + lam * ∑ i ∈ s, q i * dS i))
          * (lam * ∑ i ∈ s, q i * psPrice C ρ (dS i)) :=
  (psNum_diff_exact s q dS hρ hstab).le

/-- **Prop. decode (iii).**  The price of a miss is unbounded as the load
approaches capacity. -/
theorem psPrice_unbounded {C dS : ℝ} (hC : 0 < C) (hdS : 0 < dS) (M : ℝ) :
    ∃ ρ, ρ < C ∧ M < psPrice C ρ dS := by
  set eps : ℝ := min 1 (C * dS / (|M| + 1)) with heps
  have hM1 : 0 < |M| + 1 := by positivity
  have heps_pos : 0 < eps := lt_min one_pos (by positivity)
  have heps1 : eps ≤ 1 := min_le_left _ _
  have heps_le : eps ≤ C * dS / (|M| + 1) := min_le_right _ _
  refine ⟨C - eps, by linarith, ?_⟩
  unfold psPrice
  have h : C - (C - eps) = eps := by ring
  rw [h]
  have heps2 : eps ^ 2 ≤ eps := by nlinarith
  have hk : |M| + 1 ≤ C * dS / eps := by
    rw [le_div_iff₀ heps_pos]
    have := (le_div_iff₀ hM1).mp heps_le
    linarith
  have hk2 : C * dS / eps ≤ C * dS / eps ^ 2 :=
    div_le_div_of_nonneg_left (by positivity) (by positivity) heps2
  have : M ≤ |M| := le_abs_self M
  linarith

end ServingQueueTheory
