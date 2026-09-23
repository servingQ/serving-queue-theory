/-
# Program-level KV eviction: shortest-context-first is not optimal

Proposition (Paper Prop. 6).  Consider suspended programs with context
lengths `c_i`, recompute cost `R(c) = c²`, and a memory target `ΔC`:

  minimise  Σ_{i∈S} c_i²   subject to  Σ_{i∈S} c_i ≥ ΔC.

The claim "evict shortest contexts first is optimal" is **false** in
general: with `c = {4,5,6}` and `ΔC = 6`, shortest-first evicts `{4,5}`
(cost 41) while `{6}` is feasible with cost 36.  The problem is a covering
knapsack.  With heterogeneous resume probabilities the ordering breaks
even for single evictions.
-/
import Mathlib.Tactic
import Mathlib.Data.List.Sort

namespace ServingQueueTheory

/-- Recompute cost of a set of evicted contexts (quadratic model). -/
def evictCost (S : List ℕ) : ℕ := (S.map fun c => c ^ 2).sum

/-- Memory freed. -/
def freed (S : List ℕ) : ℕ := S.sum

/-- Feasible: frees at least `ΔC`. -/
def feasible (S : List ℕ) (ΔC : ℕ) : Prop := ΔC ≤ freed S

instance (S : List ℕ) (ΔC : ℕ) : Decidable (feasible S ΔC) := by
  unfold feasible; infer_instance

/-- Shortest-first greedy on an *ascending-sorted* list: take contexts until
the target is met. -/
def shortestFirst : List ℕ → ℕ → List ℕ
  | [], _ => []
  | c :: rest, ΔC => if ΔC ≤ c then [c] else c :: shortestFirst rest (ΔC - c)

theorem shortestFirst_example : shortestFirst [4, 5, 6] 6 = [4, 5] := by decide

theorem shortestFirst_example_cost : evictCost (shortestFirst [4, 5, 6] 6) = 41 := by decide

theorem single_six_feasible : feasible [6] 6 := by decide

theorem single_six_cost : evictCost [6] = 36 := by decide

/-- **Counterexample.**  A feasible eviction set strictly cheaper than the
shortest-first choice. -/
theorem shortestFirst_not_optimal :
    ∃ S : List ℕ, feasible S 6 ∧ evictCost S < evictCost (shortestFirst [4, 5, 6] 6) :=
  ⟨[6], by decide, by decide⟩

/-- The general optimality claim is refuted. -/
theorem shortestFirst_optimality_claim_false :
    ¬ ∀ (ctx : List ℕ) (ΔC : ℕ), ctx.Pairwise (· ≤ ·) →
        ∀ S : List ℕ, (∀ c ∈ S, c ∈ ctx) → feasible S ΔC →
          evictCost (shortestFirst ctx ΔC) ≤ evictCost S := by
  intro h
  have := h [4, 5, 6] 6 (by decide) [6] (by decide) (by decide)
  -- 41 ≤ 36 is false
  have h41 : evictCost (shortestFirst [4, 5, 6] 6) = 41 := by decide
  have h36 : evictCost [6] = 36 := by decide
  rw [h41, h36] at this
  omega

/-! ### Resume probabilities: expected recompute cost `p_i c_i²`. -/

/-- Expected recompute cost of evicting a single program. -/
def expectedEvictCost (p : ℚ) (c : ℕ) : ℚ := p * (c : ℚ) ^ 2

/-- Cost per byte freed (the fractional-knapsack density): `p_i c_i`. -/
def evictDensity (p : ℚ) (c : ℕ) : ℚ := p * (c : ℚ)

theorem expectedEvictCost_eq_density_mul (p : ℚ) (c : ℕ) :
    expectedEvictCost p c = evictDensity p c * (c : ℚ) := by
  unfold expectedEvictCost evictDensity; ring

/-- Even for a *single* eviction, shortest-first is wrong once resume
probabilities differ: program A (`c=2, p=1`) costs 4 to evict; program B
(`c=10, p=0.01`) costs 1. -/
theorem shortestFirst_wrong_with_resume_prob :
    expectedEvictCost (1 / 100) 10 < expectedEvictCost 1 2 := by
  unfold expectedEvictCost; norm_num

end ServingQueueTheory
