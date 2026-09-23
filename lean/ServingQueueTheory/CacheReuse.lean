/-
# KV-cache reuse as a service-time transformation

Proposition (paper `prop:cache`, §3).  A KV hit turns a prefill of cost `sMiss`
into one of cost `sHit ≤ sMiss`.  With hit probability `p`,
`E[S] = p sHit + (1-p) sMiss`, `rho = lam E[S]`.

* `meanService_antitone` : `E[S]` is antitone in `p`.
* `utilization_antitone` : so is `rho`, hence (via M/M/1 or PK) the
  queueing delay.
* `pkWait_mixture_antitone` : PK waiting time of the hit/miss mixture is
  antitone in the hit rate (both the second moment and the utilisation
  improve).
* Concrete: `sHit = 50ms, sMiss = 500ms, p = 0.8` ⇒ `E[S] = 140ms`;
  `lam = 1.8` ⇒ `rho : 0.9 → 0.252`.
-/
import Mathlib.Tactic
import ServingQueueTheory.PollaczekKhinchine

namespace ServingQueueTheory

/-- Mean service time under hit probability `p`. -/
def meanService (p sHit sMiss : ℝ) : ℝ := p * sHit + (1 - p) * sMiss

/-- Second moment of the two-point hit/miss mixture. -/
def secondMomentService (p sHit sMiss : ℝ) : ℝ := p * sHit ^ 2 + (1 - p) * sMiss ^ 2

/-- Utilisation `rho = lam * E[S]`. -/
def mixtureUtilization (lam p sHit sMiss : ℝ) : ℝ := lam * meanService p sHit sMiss

theorem meanService_antitone {sHit sMiss : ℝ} (h : sHit ≤ sMiss) {p q : ℝ} (hpq : p ≤ q) :
    meanService q sHit sMiss ≤ meanService p sHit sMiss := by
  unfold meanService; nlinarith

theorem utilization_antitone {lam sHit sMiss : ℝ} (hlam : 0 ≤ lam) (h : sHit ≤ sMiss)
    {p q : ℝ} (hpq : p ≤ q) :
    mixtureUtilization lam q sHit sMiss ≤ mixtureUtilization lam p sHit sMiss := by
  unfold mixtureUtilization
  exact mul_le_mul_of_nonneg_left (meanService_antitone h hpq) hlam

theorem secondMomentService_antitone {sHit sMiss : ℝ} (h0 : 0 ≤ sHit) (h : sHit ≤ sMiss)
    {p q : ℝ} (hpq : p ≤ q) :
    secondMomentService q sHit sMiss ≤ secondMomentService p sHit sMiss := by
  unfold secondMomentService
  have : sHit ^ 2 ≤ sMiss ^ 2 := by nlinarith
  nlinarith

/-- PK waiting time of the hit/miss mixture, as a function of the hit rate. -/
noncomputable def mixtureWait (lam p sHit sMiss : ℝ) : ℝ :=
  pkWait lam (secondMomentService p sHit sMiss) (mixtureUtilization lam p sHit sMiss)

/-- Raising the hit rate never increases queueing delay, provided the
system is stable at the *lower* hit rate. -/
theorem pkWait_mixture_antitone {lam sHit sMiss : ℝ} (hlam : 0 < lam)
    (h0 : 0 ≤ sHit) (h : sHit ≤ sMiss)
    {p q : ℝ} (hpq : p ≤ q) (hq0 : 0 ≤ q) (hq1 : q ≤ 1)
    (hstable : mixtureUtilization lam p sHit sMiss < 1) :
    mixtureWait lam q sHit sMiss ≤ mixtureWait lam p sHit sMiss := by
  unfold mixtureWait pkWait
  have hq_le := utilization_antitone hlam.le h hpq
  have hm2 := secondMomentService_antitone h0 h hpq
  have hdenp : 0 < 2 * (1 - mixtureUtilization lam p sHit sMiss) := by linarith
  have hdenq : 0 < 2 * (1 - mixtureUtilization lam q sHit sMiss) := by linarith
  have hden : 2 * (1 - mixtureUtilization lam p sHit sMiss)
      ≤ 2 * (1 - mixtureUtilization lam q sHit sMiss) := by linarith
  have hnum : lam * secondMomentService q sHit sMiss ≤ lam * secondMomentService p sHit sMiss :=
    mul_le_mul_of_nonneg_left hm2 hlam.le
  have hnum_nonneg : 0 ≤ lam * secondMomentService q sHit sMiss := by
    unfold secondMomentService
    have h1 := mul_nonneg hq0 (sq_nonneg sHit)
    have h2 := mul_nonneg (by linarith : (0:ℝ) ≤ 1 - q) (sq_nonneg sMiss)
    exact mul_nonneg hlam.le (by linarith)
  calc lam * secondMomentService q sHit sMiss / (2 * (1 - mixtureUtilization lam q sHit sMiss))
      ≤ lam * secondMomentService q sHit sMiss / (2 * (1 - mixtureUtilization lam p sHit sMiss)) :=
        div_le_div_of_nonneg_left hnum_nonneg hdenp hden
    _ ≤ lam * secondMomentService p sHit sMiss / (2 * (1 - mixtureUtilization lam p sHit sMiss)) :=
        div_le_div_of_nonneg_right hnum hdenp.le

/-! ### Concrete numbers (seconds). -/

theorem meanService_example : meanService 0.8 0.05 0.5 = 0.14 := by
  unfold meanService; norm_num

theorem utilization_example_miss_only : mixtureUtilization 1.8 0 0.05 0.5 = 0.9 := by
  unfold mixtureUtilization meanService; norm_num

theorem utilization_example_hit80 : mixtureUtilization 1.8 0.8 0.05 0.5 = 0.252 := by
  unfold mixtureUtilization meanService; norm_num

end ServingQueueTheory

namespace ServingQueueTheory

/-! ### Where the variance comes from in agentic workloads

Even with a high hit rate, the second moment of the hit/miss mixture is
dominated by the (rare, expensive) miss term.  We measure this by the
squared coefficient of variation `CV² = E[S²]/E[S]² - 1` and by the ratio
of the M/G/1 waiting time to that of an M/M/1 with the same mean
(`(1 + CV²)/2`, since exponential service has `E[S²] = 2 E[S]²`). -/

/-- Squared coefficient of variation of the hit/miss mixture. -/
noncomputable def mixtureCV2 (p sHit sMiss : ℝ) : ℝ :=
  secondMomentService p sHit sMiss / (meanService p sHit sMiss) ^ 2 - 1

/-- PK delay relative to exponential service with the same mean and load:
`E[Wq]_{M/G/1} / E[Wq]_{M/M/1} = (1 + CV²) / 2`. -/
theorem pkWait_ratio_to_exponential {lam mean m2 rho : ℝ} (hlam : lam ≠ 0) (hmean : mean ≠ 0)
    (hrho : rho ≠ 1) :
    pkWait lam m2 rho / pkWait lam (2 * mean ^ 2) rho = (1 + (m2 / mean ^ 2 - 1)) / 2 := by
  unfold pkWait
  have h1 : (1 - rho) ≠ 0 := sub_ne_zero.mpr (Ne.symm hrho)
  field_simp
  ring

/-- Agentic operating point: 96 % prefix hit, append-prefill 50 ms on a hit,
full 5 s re-prefill on a miss.  `CV² > 15`, i.e. more than `8×` the
queueing delay of exponential service at the same utilisation. -/
theorem mixtureCV2_agentic_example : 15 < mixtureCV2 0.96 0.05 5 := by
  unfold mixtureCV2 secondMomentService meanService; norm_num

/-- Same hit rate but a *cheap* miss (`r = 2`): `CV² < 0.05`, essentially
deterministic.  Variance is a property of the miss penalty, not of the
workload label. -/
theorem mixtureCV2_cheap_miss_example : mixtureCV2 0.96 0.05 0.1 < 0.05 := by
  unfold mixtureCV2 secondMomentService meanService; norm_num

end ServingQueueTheory
