/-
# Program-level KV eviction: shortest-context-first is not optimal

Proposition (paper `prop:evict`, §3.1).  Consider suspended programs with context
lengths `c_i`, recompute cost `R(c) = c²`, and a memory target `ΔC`:

  minimise  Σ_{i∈S} c_i²   subject to  Σ_{i∈S} c_i ≥ ΔC.

The claim "evict shortest contexts first is optimal" is **false** in
general: with `c = {4,5,6}` and `ΔC = 6`, shortest-first evicts `{4,5}`
(cost 41) while `{6}` is feasible with cost 36.  The problem is a covering
knapsack.  With heterogeneous resume probabilities the ordering breaks
even for single evictions.

What *is* true: on an ascending-sorted pool, shortest-first always frees
enough memory and costs at most twice the optimum, and the factor 2 is
tight.  Once resume probabilities enter, no constant factor survives.

Key theorems:
* `shortestFirst_not_optimal`, `shortestFirst_optimality_claim_false`:
  the `{4,5,6}`, `ΔC = 6` counterexample.
* `shortestFirst_feasible`: the greedy frees at least `ΔC` whenever the
  pool holds `ΔC`.
* `shortestFirst_two_approx`: greedy cost `≤ 2 ·` cost of any feasible
  sub-list of the sorted pool (proved via the LP-style slack
  `evictSlack L x = L·x − x²`, helpers `shortestFirst_lp_bound`,
  `shortestFirst_invariant`).
* `shortestFirst_two_approx_tight`: `[K, K+1]`, `ΔC = K+1` gives ratio
  `(K² + (K+1)²)/(K+1)² → 2`.
* `shortestFirst_wrong_with_resume_prob`,
  `shortestFirst_unbounded_with_resume_prob`: with expected cost `p·c²`
  the shortest-first choice can be worse by any factor `R`.
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

/-! ### Shortest-first is a 2-approximation (quadratic cost, sorted input). -/

/-- Shortest-first frees at least `ΔC` whenever the pool holds `ΔC`. -/
theorem shortestFirst_feasible (ctx : List ℕ) (ΔC : ℕ) (h : ΔC ≤ ctx.sum) :
    feasible (shortestFirst ctx ΔC) ΔC := by
  induction ctx generalizing ΔC with
  | nil => simp [shortestFirst, feasible, freed] at h ⊢; omega
  | cons c rest ih =>
    simp only [List.sum_cons] at h
    unfold shortestFirst
    split_ifs with hc
    · simp [feasible, freed, hc]
    · have := ih (ΔC - c) (by omega)
      simp only [feasible, freed, List.sum_cons] at this ⊢
      omega

/-- LP slack used in the 2-approximation proof: `L·x − x²` (truncated; zero
when `x ≥ L`). -/
def evictSlack (L x : ℕ) : ℕ := L * x - x ^ 2

theorem evictSlack_le_add (L x : ℕ) : L * x ≤ x ^ 2 + evictSlack L x := by
  unfold evictSlack; omega

theorem evictSlack_eq_zero {L x : ℕ} (h : L ≤ x) : evictSlack L x = 0 := by
  unfold evictSlack
  have : L * x ≤ x ^ 2 := by rw [sq]; exact Nat.mul_le_mul_right x h
  omega

theorem evictSlack_add_sq {L x : ℕ} (h : x ≤ L) : x ^ 2 + evictSlack L x = L * x := by
  unfold evictSlack
  have : x ^ 2 ≤ L * x := by rw [sq]; exact Nat.mul_le_mul_right x h
  omega

/-- LP lower bound: `L · freed S ≤ evictCost S + Σ_S slack`. -/
theorem shortestFirst_lp_bound (L : ℕ) (S : List ℕ) :
    L * S.sum ≤ evictCost S + (S.map (evictSlack L)).sum := by
  induction S with
  | nil => simp [evictCost]
  | cons x xs ih =>
    have := evictSlack_le_add L x
    simp only [evictCost, List.map_cons, List.sum_cons] at ih ⊢
    rw [Nat.mul_add]
    omega

/-- Inductive invariant of the greedy.  With `L` the last element taken:
the greedy cost plus the total slack over the pool is at most `L·ΔC + L²`,
and the pool elements shorter than `L` free strictly less than `ΔC`. -/
theorem shortestFirst_invariant (ctx : List ℕ) (hs : ctx.Pairwise (· ≤ ·)) (ΔC : ℕ)
    (hpos : 0 < ΔC) (h : ΔC ≤ ctx.sum) :
    ∃ L ∈ ctx,
      evictCost (shortestFirst ctx ΔC) + (ctx.map (evictSlack L)).sum ≤ L * ΔC + L ^ 2 ∧
      (ctx.filter (· < L)).sum < ΔC := by
  induction ctx generalizing ΔC with
  | nil => simp at h; omega
  | cons c rest ih =>
    rw [List.pairwise_cons] at hs
    simp only [List.sum_cons] at h
    by_cases hc : ΔC ≤ c
    · refine ⟨c, List.mem_cons_self, ?_, ?_⟩
      · have hz : (rest.map (evictSlack c)).sum = 0 := by
          rw [List.sum_eq_zero_iff]
          intro y hy
          obtain ⟨x, hx, rfl⟩ := List.mem_map.mp hy
          exact evictSlack_eq_zero (hs.1 x hx)
        have h0 : evictSlack c c = 0 := evictSlack_eq_zero le_rfl
        simp only [shortestFirst, hc, ite_true, evictCost, List.map_cons, List.map_nil,
          List.sum_cons, List.sum_nil, h0, hz]
        nlinarith
      · have hf : (c :: rest).filter (· < c) = [] := by
          rw [List.filter_eq_nil_iff]
          intro x hx
          rcases List.mem_cons.mp hx with rfl | hx
          · simp
          · simpa using hs.1 x hx
        rw [hf]; simpa using hpos
    · obtain ⟨L, hLmem, h1, h2⟩ := ih hs.2 (ΔC - c) (by omega) (by omega)
      have hcL : c ≤ L := hs.1 L hLmem
      refine ⟨L, List.mem_cons_of_mem c hLmem, ?_, ?_⟩
      · have hk := evictSlack_add_sq hcL
        simp only [shortestFirst, hc, ite_false, evictCost, List.map_cons, List.sum_cons] at h1 ⊢
        have hd : L * ΔC = L * c + L * (ΔC - c) := by
          rw [← Nat.mul_add]; congr 1; omega
        have hLc : L * c = c * L := Nat.mul_comm L c
        omega
      · rw [List.filter_cons]
        split_ifs with hlt
        · simp only [List.sum_cons]; omega
        · omega

/-- **Shortest-first is a 2-approximation.**  On an ascending-sorted pool,
the greedy recompute cost is at most twice that of any feasible eviction
set drawn from the pool. -/
theorem shortestFirst_two_approx (ctx : List ℕ) (hs : ctx.Pairwise (· ≤ ·)) (ΔC : ℕ)
    (hpos : 0 < ΔC) (S : List ℕ) (hS : S.Sublist ctx) (hfeas : feasible S ΔC) :
    evictCost (shortestFirst ctx ΔC) ≤ 2 * evictCost S := by
  unfold feasible freed at hfeas
  have hSctx : S.sum ≤ ctx.sum := hS.sum_le_sum (fun _ _ => Nat.zero_le _)
  obtain ⟨L, -, h1, h2⟩ := shortestFirst_invariant ctx hs ΔC hpos (by omega)
  -- (b) LP bound
  have hlp := shortestFirst_lp_bound L S
  have hslack : (S.map (evictSlack L)).sum ≤ (ctx.map (evictSlack L)).sum :=
    (hS.map _).sum_le_sum (fun _ _ => Nat.zero_le _)
  have hLS : L * ΔC ≤ L * S.sum := Nat.mul_le_mul_left L hfeas
  -- (a) `S` contains an element `≥ L`
  have hbig : L ^ 2 ≤ evictCost S := by
    by_contra hcon
    have hall : ∀ x ∈ S, x < L := by
      intro x hx
      by_contra hxL
      apply hcon
      have hx2 : x ^ 2 ≤ evictCost S :=
        List.le_sum_of_mem (List.mem_map.mpr ⟨x, hx, rfl⟩)
      have : L ^ 2 ≤ x ^ 2 := Nat.pow_le_pow_left (by omega) 2
      omega
    have hfS : S.filter (· < L) = S := List.filter_eq_self.mpr (by simpa using hall)
    have hsub : (S.filter (· < L)).Sublist (ctx.filter (· < L)) := hS.filter _
    rw [hfS] at hsub
    have := hsub.sum_le_sum (fun _ _ => Nat.zero_le _)
    omega
  omega

/-- **Tightness.**  For `K > 0`, shortest-first on `[K, K+1]` with target
`K+1` evicts both (cost `K² + (K+1)²`) while `[K+1]` alone is feasible with
cost `(K+1)²`; the ratio tends to 2. -/
theorem shortestFirst_two_approx_tight (K : ℕ) (_hK : 0 < K) :
    shortestFirst [K, K + 1] (K + 1) = [K, K + 1] ∧
    evictCost [K, K + 1] = K ^ 2 + (K + 1) ^ 2 ∧
    feasible [K + 1] (K + 1) ∧ evictCost [K + 1] = (K + 1) ^ 2 := by
  refine ⟨?_, ?_, ?_, ?_⟩
  · have h1 : ¬ (K + 1 ≤ K) := by omega
    simp [shortestFirst, h1]
  · simp [evictCost]
  · simp [feasible, freed]
  · simp [evictCost]

/-- **With resume probabilities no constant factor survives.**  For every
`R`, some program `B` (`c = M ≥ 2`, `p = 1/M³`, expected cost `1/M`) is
more than `R` times cheaper to evict than program `A` (`c = 2`, `p = 1`),
which is what shortest-first evicts for `ΔC = 2`. -/
theorem shortestFirst_unbounded_with_resume_prob (R : ℚ) :
    ∃ M : ℕ, 2 ≤ M ∧ R * expectedEvictCost (1 / (M : ℚ) ^ 3) M < expectedEvictCost 1 2 := by
  refine ⟨⌈R⌉₊ + 2, by omega, ?_⟩
  set M : ℕ := ⌈R⌉₊ + 2 with hM
  have hRle : R ≤ (⌈R⌉₊ : ℚ) := Nat.le_ceil R
  have hMpos : (0 : ℚ) < M := by positivity
  have hRM : R < (M : ℚ) := by rw [hM]; push_cast; linarith
  have heq : R * expectedEvictCost (1 / (M : ℚ) ^ 3) M = R / M := by
    unfold expectedEvictCost; field_simp
  rw [heq]
  have : R / M < 1 := (div_lt_one hMpos).mpr hRM
  unfold expectedEvictCost; norm_num; linarith

end ServingQueueTheory
