/-
# Decode sojourn under a shared capacity: the scaling identity

Issue #28: the conditional theory behind the colocated-vs-split decode
comparison.  `PDDisaggregation.lean` is about *capacity* (requests per
second).  This module is about the *time* a request spends decoding at
the same throughput, and it is a statement about the processor-sharing
(PS) idealisation of `BatchServer.lean`, not about a step engine.

The decode stage is a PS station with capacity `φ n` when `n` turns are
present, Poisson arrivals of rate `lam` and i.i.d. work of mean `ES`.  Its
stationary law is `π n ∝ (lam ES)^n / (φ 1 ⋯ φ n)` (`psWeight`), on `ℕ`
when the weights are summable (the stable case), and the paper reads the
mean number off a finite truncation `{0, …, N}` (`psMeanNumber`).

* `psWeight_scale`, `psMeanNumber_scale`, `psLaw_scale`,
  `psWeight_summable_scale_iff` : multiplying the arrival rate and the
  capacity function by the same `c ≠ 0` leaves every weight, hence the
  law, its normalisability and the mean number, unchanged.
* `psMeanNumber_eq_stationaryMean` : the truncated mean is the
  `stationaryMean` of `BatchServer.lean`, so `stationaryMean_mono`
  applies to it.
* `sojourn_scale`, `decode_sojourn_scale` : by Little's law the mean
  sojourn `L / lam` is divided by `c`.
* `dedicated_is_scaled_unified`, `dedicated_mean_number_eq`,
  `dedicated_sojourn` : one colocated engine whose decodes get the
  fraction `f` of a capacity `φ` is `(lam, f φ)`; one dedicated decode
  engine that takes the requests of the `1/f` colocated engines it
  replaces is `(lam / f, φ)`, the former scaled by `c = 1/f`.  Same
  number decoding, sojourn multiplied by `f`.
* `tpot_fixed_output_scale`, `tpot_token_weighted_scale`,
  `request_weighted_tpot_not_from_means` : with a fixed output length the
  request-weighted TPOT `T / (o - 1)` scales with the sojourn; with a
  random output length the token-weighted TPOT `E[T] / E[o - 1]` does,
  while the request-weighted mean `E[T / (o - 1)]` is not a function of
  `E[T]` and `E[o - 1]`.
* `psNum_anti_capacity`, `decode_share_loss` : at the same demand a
  smaller capacity leaves more turns in the batch.  A miss adds no decode
  demand (`BatchServer.lean`), but an engine that runs a prefill in a step
  of its own takes that step from its decodes, so the share `f` is not a
  constant there and the identity above does not describe it.

Conditions, stated once: the identity needs a PS station whose capacity
is a fixed function of the number present (a constant time share `f`),
Poisson arrivals to the decode station (a Poisson stream split at random
among `1/f` engines is Poisson; the departures of a prefill queue are
not Poisson in general), and a work law that does not depend on the
split.  Nothing here bounds a step engine's TPOT: the step-engine
comparison is simulated, not proved (`validation/src/checks.py`).
-/
import Mathlib.Tactic
import ServingQueueTheory.BatchServer

namespace ServingQueueTheory

open Finset

/-! ### The stationary weights and their invariance under scaling. -/

/-- The unnormalised stationary weight of `n` turns at a PS station with
capacity `φ`, arrival rate `lam` and mean work `ES`:
`(lam ES)^n / (φ 1 ⋯ φ n)`. -/
noncomputable def psWeight (φ : ℕ → ℝ) (lam ES : ℝ) (n : ℕ) : ℝ :=
  (lam * ES) ^ n / ∏ k ∈ range n, φ (k + 1)

/-- Scaling the arrival rate and the capacity by the same `c ≠ 0` leaves
every weight unchanged: `(c lam ES)^n / ((c φ 1) ⋯ (c φ n))
= (lam ES)^n / (φ 1 ⋯ φ n)`. -/
theorem psWeight_scale (φ : ℕ → ℝ) (lam ES : ℝ) {c : ℝ} (hc : c ≠ 0) (n : ℕ) :
    psWeight (fun k => c * φ k) (c * lam) ES n = psWeight φ lam ES n := by
  unfold psWeight
  rw [Finset.prod_mul_distrib, Finset.prod_const, Finset.card_range,
    show (c * lam * ES) ^ n = c ^ n * (lam * ES) ^ n by rw [mul_assoc, mul_pow],
    mul_div_mul_left _ _ (pow_ne_zero n hc)]

theorem psWeight_scale_fun (φ : ℕ → ℝ) (lam ES : ℝ) {c : ℝ} (hc : c ≠ 0) :
    psWeight (fun k => c * φ k) (c * lam) ES = psWeight φ lam ES :=
  funext (psWeight_scale φ lam ES hc)

/-- The law is normalisable (the station is stable) before the scaling iff
it is after. -/
theorem psWeight_summable_scale_iff (φ : ℕ → ℝ) (lam ES : ℝ) {c : ℝ} (hc : c ≠ 0) :
    Summable (psWeight (fun k => c * φ k) (c * lam) ES) ↔ Summable (psWeight φ lam ES) := by
  rw [psWeight_scale_fun φ lam ES hc]

/-- The stationary law on `ℕ` (meaningful when the weights are summable). -/
noncomputable def psLaw (φ : ℕ → ℝ) (lam ES : ℝ) (n : ℕ) : ℝ :=
  psWeight φ lam ES n / ∑' m, psWeight φ lam ES m

/-- The stationary law is unchanged by the scaling, state by state. -/
theorem psLaw_scale (φ : ℕ → ℝ) (lam ES : ℝ) {c : ℝ} (hc : c ≠ 0) (n : ℕ) :
    psLaw (fun k => c * φ k) (c * lam) ES n = psLaw φ lam ES n := by
  unfold psLaw
  rw [psWeight_scale_fun φ lam ES hc]

/-- Mean number of turns decoding, read off the truncation `{0, …, N}`
(the paper's proof of `prop:decode` takes `N → ∞`). -/
noncomputable def psMeanNumber (φ : ℕ → ℝ) (lam ES : ℝ) (N : ℕ) : ℝ :=
  (∑ n ∈ range (N + 1), (n : ℝ) * psWeight φ lam ES n) /
    (∑ n ∈ range (N + 1), psWeight φ lam ES n)

/-- The truncated mean is `BatchServer.lean`'s `stationaryMean` with the
weights `a n = 1 / (φ 1 ⋯ φ n)` and the load `ρ = lam ES`, so
`stationaryMean_mono` applies to it. -/
theorem psMeanNumber_eq_stationaryMean (φ : ℕ → ℝ) (lam ES : ℝ) (N : ℕ) :
    psMeanNumber φ lam ES N
      = stationaryMean (fun n => 1 / ∏ k ∈ range n, φ (k + 1)) N (lam * ES) := by
  unfold psMeanNumber stationaryMean psWeight
  congr 1 <;> refine Finset.sum_congr rfl fun n _ => ?_ <;> ring

/-- **The identity.**  The number decoding at the station does not change
when the arrival rate and the capacity are multiplied by the same `c`. -/
theorem psMeanNumber_scale (φ : ℕ → ℝ) (lam ES : ℝ) {c : ℝ} (hc : c ≠ 0) (N : ℕ) :
    psMeanNumber (fun k => c * φ k) (c * lam) ES N = psMeanNumber φ lam ES N := by
  unfold psMeanNumber
  rw [psWeight_scale_fun φ lam ES hc]

/-! ### Little's law: the sojourn is divided by the scale. -/

/-- Little's law: the mean sojourn of a request is `L / lam`. -/
noncomputable def meanSojourn (L lam : ℝ) : ℝ := L / lam

theorem sojourn_scale (L lam c : ℝ) : meanSojourn L (c * lam) = meanSojourn L lam / c := by
  unfold meanSojourn
  rw [div_div, mul_comm]

/-- Same number decoding, `c` times the arrivals: each request decodes in
`1 / c` of the time. -/
theorem decode_sojourn_scale (φ : ℕ → ℝ) (lam ES : ℝ) {c : ℝ} (hc : c ≠ 0) (N : ℕ) :
    meanSojourn (psMeanNumber (fun k => c * φ k) (c * lam) ES N) (c * lam)
      = meanSojourn (psMeanNumber φ lam ES N) lam / c := by
  rw [psMeanNumber_scale φ lam ES hc N, sojourn_scale]

/-! ### One colocated engine against one dedicated decode engine. -/

/-- A dedicated decode engine `(lam / f, φ)` is the colocated engine
`(lam, f φ)` scaled by `c = 1 / f`. -/
theorem dedicated_is_scaled_unified (φ : ℕ → ℝ) (lam : ℝ) {f : ℝ} (hf : f ≠ 0) :
    (fun k => (1 / f) * (f * φ k)) = φ ∧ (1 / f) * lam = lam / f := by
  refine ⟨funext fun k => ?_, by rw [one_div_mul_eq_div]⟩
  field_simp

/-- Same number of turns decoding at a dedicated decode engine as at one
colocated engine whose decodes get the fraction `f` of its time. -/
theorem dedicated_mean_number_eq (φ : ℕ → ℝ) (lam ES : ℝ) {f : ℝ} (hf : f ≠ 0) (N : ℕ) :
    psMeanNumber φ (lam / f) ES N = psMeanNumber (fun k => f * φ k) lam ES N := by
  obtain ⟨hφ, hlam⟩ := dedicated_is_scaled_unified φ lam hf
  have h := psMeanNumber_scale (fun k => f * φ k) lam ES (one_div_ne_zero hf) N
  rw [hφ, hlam] at h
  exact h

/-- The dedicated engine's mean decode sojourn is `f` times the colocated
engine's: with `f = 1/4`, a quarter. -/
theorem dedicated_sojourn (φ : ℕ → ℝ) (lam ES : ℝ) {f : ℝ} (hf : f ≠ 0) (N : ℕ) :
    meanSojourn (psMeanNumber φ (lam / f) ES N) (lam / f)
      = f * meanSojourn (psMeanNumber (fun k => f * φ k) lam ES N) lam := by
  rw [dedicated_mean_number_eq φ lam ES hf N]
  unfold meanSojourn
  field_simp

/-! ### What the identity says about TPOT, and what it does not. -/

/-- TPOT of a request that decodes `o ≥ 2` tokens in `T` seconds:
`T / (o - 1)`, the first-to-last span over the gaps. -/
noncomputable def tpot (T : ℝ) (o : ℕ) : ℝ := T / ((o : ℝ) - 1)

/-- With a fixed output length, the request-weighted TPOT scales with the
sojourn. -/
theorem tpot_fixed_output_scale (T c : ℝ) (o : ℕ) : tpot (T / c) o = tpot T o / c := by
  unfold tpot; ring

/-- Token-weighted TPOT: all decode time over all gaps, which by Little's
law is `E[T] / E[o - 1]`. -/
noncomputable def tpotTokenWeighted (ET Egaps : ℝ) : ℝ := ET / Egaps

/-- The token-weighted TPOT scales with the mean sojourn, for any output
law. -/
theorem tpot_token_weighted_scale (ET Egaps c : ℝ) :
    tpotTokenWeighted (ET / c) Egaps = tpotTokenWeighted ET Egaps / c := by
  unfold tpotTokenWeighted; ring

/-- The request-weighted TPOT `E[T / (o - 1)]` is not a function of `E[T]`
and `E[o - 1]`: two two-point laws, one request of `o = 2` and one of
`o = 4`, with sojourns `(1, 3)` or `(3, 1)`, have the same `E[T] = 2` and
`E[o - 1] = 2` and request-weighted TPOTs `1` and `5/3`.  So the
scaling of `E[T]` alone says nothing about it. -/
theorem request_weighted_tpot_not_from_means :
    ((1 : ℚ) + 3) / 2 = ((3 : ℚ) + 1) / 2 ∧
    (1 / ((2 : ℚ) - 1) + 3 / ((4 : ℚ) - 1)) / 2 ≠ (3 / ((2 : ℚ) - 1) + 1 / ((4 : ℚ) - 1)) / 2 := by
  norm_num

/-! ### The limit of the identity: a capacity that the miss takes. -/

/-- At the same demand, a smaller constant capacity leaves more turns at
the PS station: `ρ / (C - ρ) ≤ ρ / (C' - ρ)` for `ρ < C' ≤ C`. -/
theorem psNum_anti_capacity {C C' ρ : ℝ} (hρ : 0 ≤ ρ) (hC' : ρ < C') (hCC : C' ≤ C) :
    psNum C ρ ≤ psNum C' ρ := by
  unfold psNum
  exact div_le_div_of_nonneg_left hρ (by linarith) (by linarith)

/-- A decode share `f' ≤ f` of the same device at the same demand: the
mean number does not fall.  This is what an exclusive prefill step does to
the decodes of a colocated engine, although the miss that caused it adds
no decode demand. -/
theorem decode_share_loss {C f f' ρ : ℝ} (hρ : 0 ≤ ρ) (hC : 0 ≤ C) (hf' : ρ < f' * C)
    (hff : f' ≤ f) :
    psNum (f * C) ρ ≤ psNum (f' * C) ρ :=
  psNum_anti_capacity hρ hf' (by nlinarith)

end ServingQueueTheory
