/-
# Prefill/Decode disaggregation: a throughput no-gain theorem and its
# exact failure conditions

Proposition (paper `prop:pd`, App. B).  With `N` identical devices, per-request
prefill work `sP` and decode work `sD` (device-seconds), an ideal
aggregated deployment has capacity `N / (sP + sD)`.  A static split
`NP + ND = N` has capacity `min (NP/sP) (ND/sD)`.

* `pd_le_agg`                : the split never beats aggregation.
* `pd_eq_agg_at_rate_match`  : equality exactly at the rate-matched split
  `NP = N sP/(sP+sD)`.
* `pd_beats_agg_iff`         : with phase-specialisation gains `gP, gD`,
  interference `I`, network and memory caps, the *exact* condition under
  which PD wins.
* `pd_wins_example` / `pd_loses_example` : both regimes are realisable.

Hence "PD does not help agentic workloads" is regime-dependent, not a
theorem.
-/
import Mathlib.Tactic

namespace ServingQueueTheory

/-- Aggregated capacity (requests per second) of `N` devices. -/
noncomputable def aggCapacity (N sP sD : ℝ) : ℝ := N / (sP + sD)

/-- Static PD capacity: bottleneck of the two pools. -/
noncomputable def pdCapacity (NP ND sP sD : ℝ) : ℝ := min (NP / sP) (ND / sD)

/-- The static split never exceeds ideal aggregation. -/
theorem pd_le_agg {N NP ND sP sD : ℝ} (hsP : 0 < sP) (hsD : 0 < sD)
    (hsplit : NP + ND = N) :
    pdCapacity NP ND sP sD ≤ aggCapacity N sP sD := by
  unfold pdCapacity aggCapacity
  set m := min (NP / sP) (ND / sD) with hm
  have h1 : m ≤ NP / sP := min_le_left _ _
  have h2 : m ≤ ND / sD := min_le_right _ _
  have h1' : m * sP ≤ NP := by
    have := (le_div_iff₀ hsP).mp h1; exact this
  have h2' : m * sD ≤ ND := by
    have := (le_div_iff₀ hsD).mp h2; exact this
  have hsum : m * (sP + sD) ≤ N := by nlinarith
  rw [le_div_iff₀ (by linarith)]
  exact hsum

/-- Rate matching: `NP/sP = ND/sD` recovers the aggregated capacity. -/
theorem pd_eq_agg_at_rate_match {N sP sD : ℝ} (hsP : 0 < sP) (hsD : 0 < sD) :
    pdCapacity (N * sP / (sP + sD)) (N * sD / (sP + sD)) sP sD = aggCapacity N sP sD := by
  unfold pdCapacity aggCapacity
  have hsum : sP + sD ≠ 0 := by positivity
  have e1 : N * sP / (sP + sD) / sP = N / (sP + sD) := by
    field_simp
  have e2 : N * sD / (sP + sD) / sD = N / (sP + sD) := by
    field_simp
  rw [e1, e2, min_self]

/-- The rate-matched split is optimal among all splits. -/
theorem rate_match_optimal {N NP ND sP sD : ℝ} (hsP : 0 < sP) (hsD : 0 < sD)
    (hsplit : NP + ND = N) :
    pdCapacity NP ND sP sD ≤ pdCapacity (N * sP / (sP + sD)) (N * sD / (sP + sD)) sP sD := by
  rw [pd_eq_agg_at_rate_match hsP hsD]
  exact pd_le_agg hsP hsD hsplit

/-! ### Non-ideal model: interference, specialisation, network, memory. -/

/-- Aggregated capacity with prefill/decode interference overhead `I`
(device-seconds per request). -/
noncomputable def aggCapacityI (N sP sD I : ℝ) : ℝ := N / (sP + sD + I)

/-- Compute-bound PD capacity when dedicated pools reach specialisation
gains `gP, gD ≥ 1` (e.g. long-context prefill parallelism, wide-EP decode). -/
noncomputable def pdComputeCapacity (N sP sD gP gD : ℝ) : ℝ := N / (sP / gP + sD / gD)

/-- Full PD capacity: compute, KV-transfer bandwidth (`Bnet / E[K]`), and the
two memory-bound admission caps. -/
noncomputable def pdFullCapacity (N sP sD gP gD Bnet EK muPmem muDmem : ℝ) : ℝ :=
  min (min (pdComputeCapacity N sP sD gP gD) (Bnet / EK)) (min muPmem muDmem)

/-- **Exact win condition.**  PD strictly beats aggregation iff every one of
its four bottlenecks strictly exceeds the aggregated capacity. -/
theorem pd_beats_agg_iff (N sP sD I gP gD Bnet EK muPmem muDmem : ℝ) :
    aggCapacityI N sP sD I < pdFullCapacity N sP sD gP gD Bnet EK muPmem muDmem ↔
      aggCapacityI N sP sD I < pdComputeCapacity N sP sD gP gD ∧
      aggCapacityI N sP sD I < Bnet / EK ∧
      aggCapacityI N sP sD I < muPmem ∧
      aggCapacityI N sP sD I < muDmem := by
  unfold pdFullCapacity
  simp only [lt_min_iff]
  tauto

/-- With no specialisation gain and no interference, PD compute capacity
collapses to the ideal aggregated capacity: the no-gain theorem is the
`gP = gD = 1, I = 0` special case. -/
theorem pdCompute_eq_agg_of_no_gain (N sP sD : ℝ) :
    pdComputeCapacity N sP sD 1 1 = aggCapacityI N sP sD 0 := by
  unfold pdComputeCapacity aggCapacityI; simp

/-- Regime where PD wins: `sP = sD = 1`, interference `I = 0.5`, prefill
specialisation `gP = 2`, ample network and memory. -/
theorem pd_wins_example :
    aggCapacityI 32 1 1 0.5 < pdFullCapacity 32 1 1 2 1 1000 1 100 100 := by
  rw [pd_beats_agg_iff]
  unfold aggCapacityI pdComputeCapacity
  norm_num

/-- Regime where PD loses: same compute, but KV transfer is the bottleneck
(`Bnet/EK = 10 < 32/2.5`).  This is the ThunderAgent-style operating point. -/
theorem pd_loses_example :
    ¬ aggCapacityI 32 1 1 0.5 < pdFullCapacity 32 1 1 2 1 10 1 100 100 := by
  rw [pd_beats_agg_iff]
  unfold aggCapacityI pdComputeCapacity
  norm_num

end ServingQueueTheory
