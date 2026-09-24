/-
# The price of a miss

Proposition (paper `prop:price`, §2.5).  At the prefill queue, modelled as an M/G/1 FIFO server, with arrival
rate `lam`, load `rho < 1` and service second moment `m2`, the mean number
of turns in the system is (Little + Pollaczek–Khinchine)

  `L = lam · E[Wq] + rho`,   `E[Wq] = lam · m2 / (2 (1 - rho))`.

Turn a fraction `q i` of all arrivals from a hit (service `sh i`) into a
miss (service `sm i ≥ sh i`).  The load rises by `lam · Σ q i (sm i - sh i)`
and `m2` by `Σ q i (sm i² - sh i²)`.  With the per-miss price

  `Φ i = ΔS i + lam (sm i² - sh i²) / (2 (1 - rho)) + lam · E[Wq] · ΔS i / (1 - rho)`

the increase of `L` is bracketed by the linear price:

  `lam Σ q i Φ i ≤ ΔL ≤ (1 - rho) / (1 - rho') · lam Σ q i Φ i`.

Key theorems:
* `missPrice_lower`, `missPrice_upper` : the bracket (Prop. price (i)).
* `missPrice_own_vs_queue_ratio`, `missPrice_queue_terms_ratio` : the
  wait-behind term is `lam (sm + sh) / (2 (1 - rho))` times the first term
  and `(sm + sh) / (2 E[Wq])` times the load term (Prop. price (ii)).
* `missPrice_unbounded` : at fixed service times the price is unbounded as
  the arrival rate approaches capacity (Prop. price (iii)).
* `missPrice_aggregate_*` : the same bracket for aggregate changes `A`, `B`.
-/
import ServingQueueTheory.PollaczekKhinchine

namespace ServingQueueTheory

open Finset

/-- Mean number of turns in the system, `lam · E[Wq] + rho` (Little's law
applied to the queue and to the server). -/
noncomputable def numInSystem (lam m2 rho : ℝ) : ℝ := lam * pkWait lam m2 rho + rho

/-- The price of one miss: extra time summed over all turns when a turn of
service `sh` is served as a miss of service `sm`, to first order. -/
noncomputable def missPrice (lam m2 rho sh sm : ℝ) : ℝ :=
  (sm - sh) + lam * (sm ^ 2 - sh ^ 2) / (2 * (1 - rho))
    + lam * pkWait lam m2 rho * (sm - sh) / (1 - rho)

/-! ### Aggregate form: added mean service `A`, added second moment `B`. -/

/-- The linear price of aggregate changes `A = Σ q ΔS`, `B = Σ q Δ(S²)`. -/
noncomputable def linearPrice (lam m2 rho A B : ℝ) : ℝ :=
  lam * (A + lam * B / (2 * (1 - rho)) + lam * pkWait lam m2 rho * A / (1 - rho))

/-- Exact change of `L` equals the linear price plus a nonnegative
second-order term. -/
theorem missPrice_aggregate_exact {lam m2 rho A B : ℝ} (hrho : rho < 1)
    (hstab : rho + lam * A < 1) :
    numInSystem lam (m2 + B) (rho + lam * A) - numInSystem lam m2 rho
      = linearPrice lam m2 rho A B
        + lam * A * (lam ^ 2 * ((1 - rho) * B + lam * m2 * A))
            / (2 * (1 - rho) ^ 2 * (1 - rho - lam * A)) := by
  unfold numInSystem linearPrice pkWait
  have hu : (1 - rho) ≠ 0 := by linarith
  have hv : (1 - (rho + lam * A)) ≠ 0 := by linarith
  have hv' : (1 - rho - lam * A) ≠ 0 := by linarith
  field_simp
  ring

theorem missPrice_aggregate_lower {lam m2 rho A B : ℝ} (hlam : 0 ≤ lam) (hm2 : 0 ≤ m2)
    (hrho : rho < 1) (hA : 0 ≤ A) (hB : 0 ≤ B) (hstab : rho + lam * A < 1) :
    linearPrice lam m2 rho A B
      ≤ numInSystem lam (m2 + B) (rho + lam * A) - numInSystem lam m2 rho := by
  rw [missPrice_aggregate_exact hrho hstab]
  have hu : 0 < 1 - rho := by linarith
  have hv : 0 < 1 - rho - lam * A := by linarith
  have : 0 ≤ lam * A * (lam ^ 2 * ((1 - rho) * B + lam * m2 * A))
      / (2 * (1 - rho) ^ 2 * (1 - rho - lam * A)) := by positivity
  linarith

theorem missPrice_aggregate_upper {lam m2 rho A B : ℝ}
    (hrho : rho < 1) (hstab : rho + lam * A < 1) :
    numInSystem lam (m2 + B) (rho + lam * A) - numInSystem lam m2 rho
      ≤ (1 - rho) / (1 - rho - lam * A) * linearPrice lam m2 rho A B := by
  have hu : 0 < 1 - rho := by linarith
  have hv : 0 < 1 - rho - lam * A := by linarith
  -- the gap is exactly `(lam A)² / (1 - rho - lam A)`
  have hgap : (1 - rho) / (1 - rho - lam * A) * linearPrice lam m2 rho A B
      - (numInSystem lam (m2 + B) (rho + lam * A) - numInSystem lam m2 rho)
      = (lam * A) ^ 2 / (1 - rho - lam * A) := by
    rw [missPrice_aggregate_exact hrho hstab]
    unfold linearPrice pkWait
    field_simp
    ring
  have : 0 ≤ (lam * A) ^ 2 / (1 - rho - lam * A) := by positivity
  linarith

/-! ### Per-program form (the statement in the paper). -/

variable {ι : Type*}

/-- Summing the per-miss prices gives the aggregate linear price. -/
theorem sum_missPrice_eq_linearPrice (s : Finset ι) (q sh sm : ι → ℝ)
    (lam m2 rho : ℝ) :
    lam * ∑ i ∈ s, q i * missPrice lam m2 rho (sh i) (sm i)
      = linearPrice lam m2 rho (∑ i ∈ s, q i * (sm i - sh i))
          (∑ i ∈ s, q i * (sm i ^ 2 - sh i ^ 2)) := by
  unfold linearPrice missPrice
  congr 1
  simp only [mul_add, Finset.sum_add_distrib, Finset.mul_sum, Finset.sum_div]
  congr 1
  · congr 1
    refine Finset.sum_congr rfl fun i _ => ?_
    ring
  · refine Finset.sum_congr rfl fun i _ => ?_
    ring

/-- **Prop. price (i), lower bound.**  Turning a fraction `q i` of arrivals
into misses raises the mean number in system by at least
`lam Σ q i Φ i`. -/
theorem missPrice_lower (s : Finset ι) (q sh sm : ι → ℝ) {lam m2 rho : ℝ}
    (hlam : 0 ≤ lam) (hm2 : 0 ≤ m2) (hrho : rho < 1)
    (hq : ∀ i ∈ s, 0 ≤ q i) (hsh : ∀ i ∈ s, 0 ≤ sh i) (hs : ∀ i ∈ s, sh i ≤ sm i)
    (hstab : rho + lam * ∑ i ∈ s, q i * (sm i - sh i) < 1) :
    lam * ∑ i ∈ s, q i * missPrice lam m2 rho (sh i) (sm i)
      ≤ numInSystem lam (m2 + ∑ i ∈ s, q i * (sm i ^ 2 - sh i ^ 2))
          (rho + lam * ∑ i ∈ s, q i * (sm i - sh i)) - numInSystem lam m2 rho := by
  rw [sum_missPrice_eq_linearPrice]
  apply missPrice_aggregate_lower hlam hm2 hrho _ _ hstab
  · exact Finset.sum_nonneg fun i hi => mul_nonneg (hq i hi) (by linarith [hs i hi])
  · refine Finset.sum_nonneg fun i hi => mul_nonneg (hq i hi) ?_
    have := hs i hi; have := hsh i hi; nlinarith

/-- **Prop. price (i), upper bound.**  The increase is at most
`(1 - rho) / (1 - rho')` times the linear price, where `rho'` is the load
after the change. -/
theorem missPrice_upper (s : Finset ι) (q sh sm : ι → ℝ) {lam m2 rho : ℝ}
    (hrho : rho < 1) (hstab : rho + lam * ∑ i ∈ s, q i * (sm i - sh i) < 1) :
    numInSystem lam (m2 + ∑ i ∈ s, q i * (sm i ^ 2 - sh i ^ 2))
        (rho + lam * ∑ i ∈ s, q i * (sm i - sh i)) - numInSystem lam m2 rho
      ≤ (1 - rho) / (1 - (rho + lam * ∑ i ∈ s, q i * (sm i - sh i)))
          * (lam * ∑ i ∈ s, q i * missPrice lam m2 rho (sh i) (sm i)) := by
  rw [sum_missPrice_eq_linearPrice, sub_add_eq_sub_sub]
  exact missPrice_aggregate_upper hrho hstab

/-- **Prop. price (ii), first comparison.**  The term for the wait behind
the miss is `lam (sm + sh) / (2 (1 - rho))` times the miss penalty (the
first term). -/
theorem missPrice_own_vs_queue_ratio {lam rho sh sm : ℝ} (hrho : rho < 1) :
    lam * (sm ^ 2 - sh ^ 2) / (2 * (1 - rho))
      = lam * (sm + sh) / (2 * (1 - rho)) * (sm - sh) := by
  have hu : (1 - rho) ≠ 0 := by linarith
  field_simp
  ring

/-- **Prop. price (ii), second comparison.**  The term for the miss's own length is
`(sm + sh) / (2 E[Wq])` times the term for the load it adds. -/
theorem missPrice_queue_terms_ratio {lam m2 rho sh sm : ℝ} (hrho : rho < 1)
    (hW : pkWait lam m2 rho ≠ 0) :
    lam * (sm ^ 2 - sh ^ 2) / (2 * (1 - rho))
      = (sm + sh) / (2 * pkWait lam m2 rho)
          * (lam * pkWait lam m2 rho * (sm - sh) / (1 - rho)) := by
  have hu : (1 - rho) ≠ 0 := by linarith
  field_simp
  ring

/-- **Prop. price (iii).**  Fix the service times (`m1 = E[S] > 0`,
`m2 = E[S²] > 0`) and a miss with `sh < sm`.  As the arrival rate `lam`
approaches capacity `1 / m1`, the price of a miss is unbounded, while the
miss penalty `sm - sh` stays fixed. -/
theorem missPrice_unbounded {m1 m2 sh sm : ℝ} (hm1 : 0 < m1) (hm2 : 0 < m2)
    (hsh : 0 ≤ sh) (hs : sh < sm) (M : ℝ) :
    ∃ lam, 0 < lam ∧ lam * m1 < 1 ∧ M < missPrice lam m2 (lam * m1) sh sm := by
  set d := sm - sh with hd
  have hdpos : 0 < d := by rw [hd]; linarith
  set k : ℝ := (1 / (2 * m1)) ^ 2 * m2 * d / 2 with hk
  have hkpos : 0 < k := by positivity
  set eps : ℝ := min (1 / 2) (k / (|M| + 1)) with heps
  have hM1 : 0 < |M| + 1 := by positivity
  have heps_pos : 0 < eps := lt_min (by norm_num) (by positivity)
  have heps_half : eps ≤ 1 / 2 := min_le_left _ _
  have heps_le : eps ≤ k / (|M| + 1) := min_le_right _ _
  set lam := (1 - eps) / m1 with hlam
  have hlam_pos : 0 < lam := by rw [hlam]; apply div_pos <;> linarith
  have hrho : lam * m1 = 1 - eps := by rw [hlam]; field_simp
  have hlam_ge : 1 / (2 * m1) ≤ lam := by
    rw [hlam, div_le_div_iff₀ (by positivity) hm1]; nlinarith
  refine ⟨lam, hlam_pos, by linarith, ?_⟩
  unfold missPrice pkWait
  rw [hrho]
  have hu : 1 - (1 - eps) = eps := by ring
  rw [hu, ← hd]
  -- the second term is nonnegative
  have h2 : 0 ≤ lam * (sm ^ 2 - sh ^ 2) / (2 * eps) := by
    apply div_nonneg _ (by positivity)
    apply mul_nonneg hlam_pos.le; nlinarith
  -- the third term is at least `k / eps² ≥ k / eps ≥ |M| + 1`
  have h3eq : lam * (lam * m2 / (2 * eps)) * d / eps = lam ^ 2 * m2 * d / 2 / eps ^ 2 := by
    field_simp
  have hlam2 : (1 / (2 * m1)) ^ 2 ≤ lam ^ 2 := by
    apply pow_le_pow_left₀ (by positivity) hlam_ge
  have hnum : k ≤ lam ^ 2 * m2 * d / 2 := by
    rw [hk]
    have := mul_le_mul_of_nonneg_right hlam2 (le_of_lt (mul_pos hm2 hdpos))
    nlinarith
  have heps2 : eps ^ 2 ≤ eps := by nlinarith
  have h3 : k / eps ≤ lam * (lam * m2 / (2 * eps)) * d / eps := by
    rw [h3eq]
    calc k / eps ≤ k / eps ^ 2 := by
          apply div_le_div_of_nonneg_left hkpos.le (by positivity) heps2
      _ ≤ lam ^ 2 * m2 * d / 2 / eps ^ 2 := by
          apply div_le_div_of_nonneg_right hnum (by positivity)
  have hkeps : |M| + 1 ≤ k / eps := by
    rw [le_div_iff₀ heps_pos]
    have := (le_div_iff₀ hM1).mp heps_le
    linarith
  have hMabs : M ≤ |M| := le_abs_self M
  linarith

/-! ### The price within a replica: monotone in the context

Under the prefill cost `P(n, K) = a n + b n (K + n/2)` of `eq:prefill`, the
miss penalty of a program with context `K` and append `n` is
`ΔS = P(K + n, 0) - P(n, K) = a K + b K² / 2`, increasing in `K`; both
`S^miss - S^hit` and `S^miss + S^hit` grow with `K`, so at one replica and
one load `Φ` orders programs by context length. The load changes the
*ratios* between programs, not their order, until `p_i` and `τ_i` enter
(`price_order_flips_with_load`). -/

/-- Prefill work of `eq:prefill`: `a n + b n (K + n/2)`. -/
noncomputable def prefillWork (a b n K : ℝ) : ℝ := a * n + b * n * (K + n / 2)

/-- `ΔS = P(K+n, 0) - P(n, K) = a K + b K² / 2`. -/
theorem prefillWork_miss_delta (a b n K : ℝ) :
    prefillWork a b (K + n) 0 - prefillWork a b n K = a * K + b * K ^ 2 / 2 := by
  unfold prefillWork; ring

theorem prefillWork_nonneg {a b n K : ℝ} (ha : 0 ≤ a) (hb : 0 ≤ b) (hn : 0 ≤ n) (hK : 0 ≤ K) :
    0 ≤ prefillWork a b n K := by
  unfold prefillWork; positivity

theorem prefillWork_mono_context {a b n : ℝ} (hb : 0 ≤ b) (hn : 0 ≤ n) {K K' : ℝ}
    (hKK : K ≤ K') : prefillWork a b n K ≤ prefillWork a b n K' := by
  unfold prefillWork; nlinarith [mul_nonneg hb hn]

theorem prefillWork_miss_mono_context {a b n : ℝ} (ha : 0 ≤ a) (hb : 0 ≤ b) (hn : 0 ≤ n)
    {K K' : ℝ} (hK : 0 ≤ K) (hKK : K ≤ K') :
    prefillWork a b (K + n) 0 ≤ prefillWork a b (K' + n) 0 := by
  unfold prefillWork
  have h1 : 0 ≤ (K' + n) - (K + n) := by linarith
  have h2 : 0 ≤ (K' + n) + (K + n) := by linarith
  nlinarith [mul_nonneg ha h1, mul_nonneg hb (mul_nonneg h1 h2)]

/-- **Within a replica the price of a miss is monotone in the context.** At
fixed `lam ≥ 0`, `m2 ≥ 0`, `rho < 1` and append `n ≥ 0`, a longer context
`K' ≥ K ≥ 0` has a price at least as high. -/
theorem missPrice_mono_context {a b n lam m2 rho : ℝ} (ha : 0 ≤ a) (hb : 0 ≤ b) (hn : 0 ≤ n)
    (hlam : 0 ≤ lam) (hm2 : 0 ≤ m2) (hrho : rho < 1) {K K' : ℝ} (hK : 0 ≤ K) (hKK : K ≤ K') :
    missPrice lam m2 rho (prefillWork a b n K) (prefillWork a b (K + n) 0)
      ≤ missPrice lam m2 rho (prefillWork a b n K') (prefillWork a b (K' + n) 0) := by
  have hK' : 0 ≤ K' := le_trans hK hKK
  -- the four service times and their order
  set sh := prefillWork a b n K with hsh
  set sm := prefillWork a b (K + n) 0 with hsm
  set sh' := prefillWork a b n K' with hsh'
  set sm' := prefillWork a b (K' + n) 0 with hsm'
  have hd : sm - sh = a * K + b * K ^ 2 / 2 := prefillWork_miss_delta a b n K
  have hd' : sm' - sh' = a * K' + b * K' ^ 2 / 2 := prefillWork_miss_delta a b n K'
  have hdd : sm - sh ≤ sm' - sh' := by
    rw [hd, hd']
    have h1 : 0 ≤ K' - K := by linarith
    nlinarith [mul_nonneg ha h1, mul_nonneg hb (mul_nonneg h1 (add_nonneg hK hK'))]
  have hd0 : 0 ≤ sm - sh := by rw [hd]; positivity
  have hsh0 : 0 ≤ sh := prefillWork_nonneg ha hb hn hK
  have hsm0 : 0 ≤ sm := prefillWork_nonneg ha hb (by linarith) le_rfl
  have hshm : sh ≤ sh' := prefillWork_mono_context hb hn hKK
  have hsmm : sm ≤ sm' := prefillWork_miss_mono_context ha hb hn hK hKK
  have hsum : sm + sh ≤ sm' + sh' := by linarith
  have hsum0 : 0 ≤ sm + sh := by linarith
  have hsq : sm ^ 2 - sh ^ 2 ≤ sm' ^ 2 - sh' ^ 2 := by
    have e1 : sm ^ 2 - sh ^ 2 = (sm - sh) * (sm + sh) := by ring
    have e2 : sm' ^ 2 - sh' ^ 2 = (sm' - sh') * (sm' + sh') := by ring
    rw [e1, e2]
    exact mul_le_mul hdd hsum hsum0 (by linarith)
  have hu : 0 < 1 - rho := by linarith
  have hw : 0 ≤ pkWait lam m2 rho := by unfold pkWait; positivity
  unfold missPrice
  have t2 : lam * (sm ^ 2 - sh ^ 2) / (2 * (1 - rho)) ≤ lam * (sm' ^ 2 - sh' ^ 2) / (2 * (1 - rho)) := by
    apply div_le_div_of_nonneg_right _ (by positivity)
    exact mul_le_mul_of_nonneg_left hsq hlam
  have t3 : lam * pkWait lam m2 rho * (sm - sh) / (1 - rho)
      ≤ lam * pkWait lam m2 rho * (sm' - sh') / (1 - rho) := by
    apply div_le_div_of_nonneg_right _ hu.le
    exact mul_le_mul_of_nonneg_left hdd (mul_nonneg hlam hw)
  linarith

/-- **The eviction order by price per byte can flip with the load.** Two
programs on one replica, `a = 2·10⁻⁵`, `b = 4·10⁻¹⁰`, appends of 1000
tokens: program 1 has a 200k context and resumes with probability 0.3,
program 2 a 20k context and probability 0.9; sizes are proportional to
context. At an idle queue (`lam = 0`) program 1 has the lower price per
byte and is evicted first; at `lam = 0.2`, `rho = 0.5`, `W = 2 s`
(`m2 = 10`) the order is reversed. -/
theorem price_order_flips_with_load :
    let P := fun n K : ℝ => prefillWork (1 / 50000) (1 / 2500000000) n K
    (3 / 10 : ℝ) * missPrice 0 0 0 (P 1000 200000) (P 201000 0) / 200000
        < (9 / 10) * missPrice 0 0 0 (P 1000 20000) (P 21000 0) / 20000 ∧
    (9 / 10 : ℝ) * missPrice (1 / 5) 10 (1 / 2) (P 1000 20000) (P 21000 0) / 20000
        < (3 / 10) * missPrice (1 / 5) 10 (1 / 2) (P 1000 200000) (P 201000 0) / 200000 := by
  intro P
  simp only [P]
  unfold missPrice pkWait prefillWork
  constructor <;> norm_num

end ServingQueueTheory
