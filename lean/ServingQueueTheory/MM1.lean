/-
# M/M/1 response time: nonlinear blow-up near saturation

Proposition (paper `prop:mm1`, §3).  For a single-server Markovian queue with
arrival rate `lam` and service rate `mu`, the mean response time is
`W = 1 / (mu - lam)`.  We prove:

* `mm1Wait_eq_rho_form` : `W = (1/mu) / (1 - rho)` with `rho = lam/mu`.
* `mm1Wait_strictMono`  : `W` is strictly increasing in `lam` on `[0, mu)`.
* `mm1Wait_unbounded`   : for every bound `M` there is a stable load
  (`lam < mu`) whose response time exceeds `M`.
* Concrete numbers from the paper (`mu = 10`): `lam = 9, 9.5, 9.9` give
  `W = 1, 2, 10`.
-/
import Mathlib.Analysis.SpecialFunctions.Pow.Real

namespace ServingQueueTheory

/-- Mean response time of an M/M/1 queue (valid for `lam < mu`). -/
noncomputable def mm1Wait (mu lam : ℝ) : ℝ := 1 / (mu - lam)

/-- Utilisation. -/
noncomputable def utilization (mu lam : ℝ) : ℝ := lam / mu

/-- `W = (1/mu) / (1 - rho)`: the response time is the service time
inflated by `1/(1-rho)`. -/
theorem mm1Wait_eq_rho_form {mu lam : ℝ} (hmu : 0 < mu) :
    mm1Wait mu lam = (1 / mu) / (1 - utilization mu lam) := by
  unfold mm1Wait utilization
  have hmu' : mu ≠ 0 := ne_of_gt hmu
  field_simp

/-- Response time is strictly increasing in the arrival rate on the stable
region `0 ≤ lam < mu`. -/
theorem mm1Wait_strictMono {mu : ℝ} :
    StrictMonoOn (mm1Wait mu) (Set.Ico 0 mu) := by
  intro a ha b hb hab
  unfold mm1Wait
  have hb' : 0 < mu - b := by linarith [hb.2]
  have : mu - b < mu - a := by linarith
  exact one_div_lt_one_div_of_lt hb' this

/-- For any target `M`, some stable load already has response time `> M`:
the latency curve is unbounded as `lam → mu⁻`. -/
theorem mm1Wait_unbounded {mu : ℝ} (hmu : 0 < mu) (M : ℝ) :
    ∃ lam, 0 ≤ lam ∧ lam < mu ∧ M < mm1Wait mu lam := by
  -- pick eps = min(mu, 1/(|M|+1)) and lam = mu - eps
  set eps : ℝ := min mu (1 / (|M| + 1)) with heps
  have hM1 : 0 < |M| + 1 := by positivity
  have heps_pos : 0 < eps := by
    rw [heps]; exact lt_min hmu (by positivity)
  have heps_le_mu : eps ≤ mu := min_le_left _ _
  have heps_le : eps ≤ 1 / (|M| + 1) := min_le_right _ _
  refine ⟨mu - eps, by linarith, by linarith, ?_⟩
  unfold mm1Wait
  have h1 : mu - (mu - eps) = eps := by ring
  rw [h1]
  -- 1/eps ≥ |M| + 1 > M
  have h2 : |M| + 1 ≤ 1 / eps := by
    have := one_div_le_one_div_of_le heps_pos heps_le
    simpa using this
  calc M ≤ |M| := le_abs_self M
    _ < |M| + 1 := by linarith
    _ ≤ 1 / eps := h2

/-! ### Concrete numbers used in the paper (`mu = 10 req/s`). -/

theorem mm1Wait_example_9 : mm1Wait 10 9 = 1 := by
  unfold mm1Wait; norm_num

theorem mm1Wait_example_9_5 : mm1Wait 10 9.5 = 2 := by
  unfold mm1Wait; norm_num

theorem mm1Wait_example_9_9 : mm1Wait 10 9.9 = 10 := by
  unfold mm1Wait; norm_num

/-- A 10% increase of arrival rate (9 → 9.9) multiplies latency by 10. -/
theorem mm1Wait_example_ratio : mm1Wait 10 9.9 = 10 * mm1Wait 10 9 := by
  unfold mm1Wait; norm_num

end ServingQueueTheory
