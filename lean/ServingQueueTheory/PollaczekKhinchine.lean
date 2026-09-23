/-
# Pollaczek–Khinchine: variance of service time drives queueing delay

Proposition (Paper Prop. 2).  For an M/G/1 queue,
`E[Wq] = lam * E[S²] / (2 (1 - rho))`.

* `secondMoment_eq_variance_add_sq` : `E[S²] = Var[S] + E[S]²` for a finite
  discrete service-time distribution.
* `pkWait_mono_secondMoment` : holding `lam` and `rho` fixed, `E[Wq]` is
  monotone in `E[S²]` (hence in the variance).
* Concrete workloads `A = {1000,1000,1000,1000}` and
  `B = {100,100,100,3700}` have equal means but `E[S²]` ratio `3.43`.
-/
import Mathlib.Algebra.BigOperators.Ring.Finset
import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic

namespace ServingQueueTheory

open Finset

/-- Mean waiting time in queue for M/G/1 (Pollaczek–Khinchine). -/
noncomputable def pkWait (lam m2 rho : ℝ) : ℝ := lam * m2 / (2 * (1 - rho))

/-- Discrete distribution over `n` service-time values. -/
structure DiscreteService (n : ℕ) where
  p : Fin n → ℝ
  s : Fin n → ℝ
  p_nonneg : ∀ i, 0 ≤ p i
  p_sum : ∑ i, p i = 1

namespace DiscreteService

variable {n : ℕ} (D : DiscreteService n)

noncomputable def mean : ℝ := ∑ i, D.p i * D.s i
noncomputable def secondMoment : ℝ := ∑ i, D.p i * (D.s i) ^ 2
noncomputable def variance : ℝ := ∑ i, D.p i * (D.s i - D.mean) ^ 2

/-- `E[S²] = Var[S] + E[S]²`. -/
theorem secondMoment_eq_variance_add_sq :
    D.secondMoment = D.variance + D.mean ^ 2 := by
  unfold variance
  have h : ∀ i, D.p i * (D.s i - D.mean) ^ 2
      = D.p i * (D.s i) ^ 2 - 2 * D.mean * (D.p i * D.s i) + D.mean ^ 2 * D.p i := by
    intro i; ring
  simp_rw [h]
  rw [sum_add_distrib, sum_sub_distrib, ← mul_sum, ← mul_sum, D.p_sum]
  unfold secondMoment mean
  ring

end DiscreteService

/-- With `lam > 0` and `rho < 1`, the PK waiting time is monotone in `E[S²]`. -/
theorem pkWait_mono_secondMoment {lam rho m2 m2' : ℝ} (hlam : 0 < lam) (hrho : rho < 1)
    (h : m2 ≤ m2') : pkWait lam m2 rho ≤ pkWait lam m2' rho := by
  unfold pkWait
  have hden : 0 < 2 * (1 - rho) := by linarith
  apply div_le_div_of_nonneg_right _ hden.le
  exact mul_le_mul_of_nonneg_left h hlam.le

/-- Strict version. -/
theorem pkWait_strictMono_secondMoment {lam rho m2 m2' : ℝ} (hlam : 0 < lam) (hrho : rho < 1)
    (h : m2 < m2') : pkWait lam m2 rho < pkWait lam m2' rho := by
  unfold pkWait
  have hden : 0 < 2 * (1 - rho) := by linarith
  apply div_lt_div_of_pos_right _ hden
  exact mul_lt_mul_of_pos_left h hlam

/-- Same mean, larger variance ⇒ larger waiting time. -/
theorem pkWait_lt_of_variance_lt {n m : ℕ} (A : DiscreteService n) (B : DiscreteService m)
    {lam rho : ℝ} (hlam : 0 < lam) (hrho : rho < 1)
    (hmean : A.mean = B.mean) (hvar : A.variance < B.variance) :
    pkWait lam A.secondMoment rho < pkWait lam B.secondMoment rho := by
  apply pkWait_strictMono_secondMoment hlam hrho
  rw [A.secondMoment_eq_variance_add_sq, B.secondMoment_eq_variance_add_sq, hmean]
  linarith

/-! ### Concrete workloads from the paper. -/

/-- Workload A: four requests of length 1000. -/
noncomputable def workloadA : DiscreteService 4 where
  p := fun _ => 1 / 4
  s := fun _ => 1000
  p_nonneg := fun _ => by norm_num
  p_sum := by norm_num [Finset.sum_const]

/-- Workload B: `{100, 100, 100, 3700}`. -/
noncomputable def workloadB : DiscreteService 4 where
  p := fun _ => 1 / 4
  s := ![100, 100, 100, 3700]
  p_nonneg := fun _ => by norm_num
  p_sum := by norm_num [Finset.sum_const]

theorem workloadA_mean : workloadA.mean = 1000 := by
  unfold DiscreteService.mean workloadA
  norm_num [Fin.sum_univ_four]

theorem workloadB_mean : workloadB.mean = 1000 := by
  unfold DiscreteService.mean workloadB
  norm_num [Fin.sum_univ_four]

theorem workloadA_secondMoment : workloadA.secondMoment = 1000000 := by
  unfold DiscreteService.secondMoment workloadA
  norm_num [Fin.sum_univ_four]

theorem workloadB_secondMoment : workloadB.secondMoment = 3430000 := by
  unfold DiscreteService.secondMoment workloadB
  norm_num [Fin.sum_univ_four]

/-- Equal means, but B's queueing delay is `3.43×` A's at every stable load. -/
theorem workloadB_wait_ratio {lam rho : ℝ} (hrho : rho < 1) :
    pkWait lam workloadB.secondMoment rho = 3.43 * pkWait lam workloadA.secondMoment rho := by
  rw [workloadA_secondMoment, workloadB_secondMoment]
  unfold pkWait
  have : (2 * (1 - rho)) ≠ 0 := by
    have : 0 < 2 * (1 - rho) := by linarith
    exact ne_of_gt this
  field_simp
  ring

end ServingQueueTheory
