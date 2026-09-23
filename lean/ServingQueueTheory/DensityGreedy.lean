/-
# Guarded density greedy for priced eviction

Proposition (paper `prop:guarded`, §3.1).  Evicting suspended program `i`
frees `c i` tokens and costs its price `w i ≥ 0` (Prop. price).  The
eviction problem is the covering knapsack

  minimise `Σ_{i∈S} w i`  subject to  `Σ_{i∈S} c i ≥ ΔC`.

* `densityFirst_unbounded` : taking programs in increasing `w / c` until
  `ΔC` is freed has no constant approximation ratio (Prop. guarded (i)).
* `threshold_prefix_le` : a set whose members all have density `≤ θ` costs
  no more than any set that frees at least as much and whose other members
  have density `≥ θ` (the exchange step of the fractional greedy).
* `guardedGreedy_two_approx` : guessing the most expensive member `e` of a
  feasible set `O`, dropping heavier programs and filling by density gives
  cost at most `2 · w(O)` (Prop. guarded (ii)).
* `threshold_rule_optimal` : dropping the states with price per byte `≤ θ`
  is optimal among choices freeing at least as much (Prop. memory (i)).
* `density_prefix_plus_one` : with block-level eviction, density order is
  optimal up to one block (Prop. memory (ii)).
-/
import Mathlib.Tactic

namespace ServingQueueTheory

open Finset

/-! ### Without the guard: no constant ratio. -/

/-- Density-first on a list already sorted by `w / c`: take `(w, c)` pairs
until the target is met. -/
def densityFirst : List (ℚ × ℚ) → ℚ → List (ℚ × ℚ)
  | [], _ => []
  | x :: rest, ΔC => if ΔC ≤ x.2 then [x] else x :: densityFirst rest (ΔC - x.2)

/-- Total price of a list of `(w, c)` pairs. -/
def priceOf (S : List (ℚ × ℚ)) : ℚ := (S.map Prod.fst).sum

/-- Tokens freed by a list of `(w, c)` pairs. -/
def freedOf (S : List (ℚ × ℚ)) : ℚ := (S.map Prod.snd).sum

/-- **Prop. guarded (i).**  For every `R` there is an instance, sorted by
density (`0 ≤ 1 ≤ 2`), on which density-first pays more than `R` times a
feasible alternative: programs `(w, c) = (0, 1), (K, K), (2, 1)` and
`ΔC = 2`.  Density-first takes the first two (price `K`); the first and
third also free `2` at price `2`. -/
theorem densityFirst_unbounded (R : ℚ) :
    ∃ K : ℚ, 1 ≤ K ∧
      densityFirst [(0, 1), (K, K), (2, 1)] 2 = [(0, 1), (K, K)] ∧
      priceOf [(0, 1), (K, K)] = K ∧
      2 ≤ freedOf [(0, 1), (2, 1)] ∧ priceOf [(0, 1), (2, 1)] = 2 ∧
      R * 2 < K := by
  refine ⟨max 1 (2 * |R| + 1), le_max_left _ _, ?_, ?_, ?_, ?_, ?_⟩
  · have hK : (1 : ℚ) ≤ max 1 (2 * |R| + 1) := le_max_left _ _
    have h1 : ¬ ((2 : ℚ) ≤ 1) := by norm_num
    have h2 : (2 : ℚ) - 1 ≤ max 1 (2 * |R| + 1) := by linarith
    simp only [densityFirst, h1, ite_false, h2, ite_true]
  · simp [priceOf]
  · simp [freedOf]; norm_num
  · simp [priceOf]
  · have : 2 * |R| + 1 ≤ max 1 (2 * |R| + 1) := le_max_right _ _
    have : R ≤ |R| := le_abs_self R
    linarith

/-! ### With the guard: a 2-approximation. -/

variable {ι : Type*} [DecidableEq ι]

/-- **Exchange step.**  If every member of `P` has density at most `θ`,
every member of `S` outside `P` has density at least `θ`, and `S` frees at
least as much as `P`, then `P` costs no more than `S`. -/
theorem threshold_prefix_le (w c : ι → ℝ) (P S : Finset ι) {θ : ℝ} (hθ : 0 ≤ θ)
    (hP : ∀ i ∈ P, w i ≤ θ * c i) (hS : ∀ i ∈ S \ P, θ * c i ≤ w i)
    (hcap : ∑ i ∈ P, c i ≤ ∑ i ∈ S, c i) :
    ∑ i ∈ P, w i ≤ ∑ i ∈ S, w i := by
  have ew1 := Finset.sum_inter_add_sum_sdiff P S w
  have ew2 := Finset.sum_inter_add_sum_sdiff S P w
  have ec1 := Finset.sum_inter_add_sum_sdiff P S c
  have ec2 := Finset.sum_inter_add_sum_sdiff S P c
  rw [Finset.inter_comm] at ew2 ec2
  have h3 : ∑ i ∈ P \ S, w i ≤ θ * ∑ i ∈ P \ S, c i := by
    rw [Finset.mul_sum]
    exact Finset.sum_le_sum fun i hi => hP i (Finset.mem_sdiff.mp hi).1
  have h4 : θ * ∑ i ∈ S \ P, c i ≤ ∑ i ∈ S \ P, w i := by
    rw [Finset.mul_sum]
    exact Finset.sum_le_sum fun i hi => hS i hi
  have h5 : ∑ i ∈ P \ S, c i ≤ ∑ i ∈ S \ P, c i := by linarith
  have h6 := mul_le_mul_of_nonneg_left h5 hθ
  linarith

/-- **Prop. guarded (ii).**  Let `O` be any feasible eviction set and `e`
its most expensive member.  Among the programs no more expensive than `e`
(other than `e`), let `P` be those taken by density before the first one,
`x`, that completes the target, and `θ` the density of `x`.  Then the guess
`{e} ∪ P ∪ {x}` costs at most twice `O`.

Hypotheses (all hold because `e` is the most expensive member of `O`, so
`O \ {e}` lies inside the candidate pool): `x` costs at most `e`;
members of `P` have density `≤ θ`; members of `O \ {e}` outside
`P` have density `≥ θ` (they are candidates not yet taken); `P` frees less
than `O \ {e}` (it had not yet reached `ΔC - c e ≤ c(O \ {e})`). -/
theorem guardedGreedy_two_approx (w c : ι → ℝ) (O P : Finset ι) (e x : ι) {θ : ℝ}
    (hw : ∀ i, 0 ≤ w i) (he : e ∈ O) (hxw : w x ≤ w e)
    (hθ : 0 ≤ θ) (hP : ∀ i ∈ P, w i ≤ θ * c i)
    (hS : ∀ i ∈ O.erase e \ P, θ * c i ≤ w i)
    (hcap : ∑ i ∈ P, c i ≤ ∑ i ∈ O.erase e, c i) :
    w e + ∑ i ∈ P, w i + w x ≤ 2 * ∑ i ∈ O, w i := by
  have hPO := threshold_prefix_le w c P (O.erase e) hθ hP hS hcap
  have hsplit := Finset.add_sum_erase O w he
  have hrest : 0 ≤ ∑ i ∈ O.erase e, w i := Finset.sum_nonneg fun i _ => hw i
  linarith

/-- **Prop. memory (i): the threshold rule.**  Dropping exactly the states
whose price per byte is at most `θ` costs no more than any other choice
that frees at least as much memory.  (The exchange step above, read as a
statement about the shadow price `θ` of memory.) -/
theorem threshold_rule_optimal (w c : ι → ℝ) (S : Finset ι) (pool : Finset ι) {θ : ℝ}
    (hθ : 0 ≤ θ) (hS : S ⊆ pool)
    (hcap : ∑ i ∈ pool.filter (fun i => w i ≤ θ * c i), c i ≤ ∑ i ∈ S, c i) :
    ∑ i ∈ pool.filter (fun i => w i ≤ θ * c i), w i ≤ ∑ i ∈ S, w i := by
  apply threshold_prefix_le w c _ S hθ
  · intro i hi; exact (Finset.mem_filter.mp hi).2
  · intro i hi
    have hi' := Finset.mem_sdiff.mp hi
    have hnot : ¬ (w i ≤ θ * c i) := fun h =>
      hi'.2 (Finset.mem_filter.mpr ⟨hS hi'.1, h⟩)
    linarith [not_le.mp hnot]
  · exact hcap

/-- **Prop. memory (ii): block-level eviction.**  When state is evicted in
blocks, density order is optimal up to one block: the density prefix `P`
taken before the block `x` that completes the target costs at most any
feasible set `O`, so `P ∪ {x}` costs at most `w(O) + w x`. -/
theorem density_prefix_plus_one (w c : ι → ℝ) (O P : Finset ι) (x : ι) {θ : ℝ}
    (hθ : 0 ≤ θ) (hP : ∀ i ∈ P, w i ≤ θ * c i) (hO : ∀ i ∈ O \ P, θ * c i ≤ w i)
    (hcap : ∑ i ∈ P, c i ≤ ∑ i ∈ O, c i) :
    ∑ i ∈ P, w i + w x ≤ ∑ i ∈ O, w i + w x := by
  have := threshold_prefix_le w c P O hθ hP hO hcap
  linarith

end ServingQueueTheory
