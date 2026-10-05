/-
# The step engine and the FIFO prefill queue

The replica is serQ's step engine (`SerqLang.Exec`): it runs iterations;
each serves some tokens of the requests that have arrived and lasts at least
the cost of those tokens. This module derives the FIFO prefill queue from
that engine instead of assuming it (research/step-engine-theory.md): the
proof starts from serQ's definition of an iteration.

* `chunk_cost_telescopes`, `chunks_cost_sum` : the cost of a chunk of `x`
  tokens at position `p` of a request with cached prefix `K`,
  `a x + b x (K + p + x/2)`, is an increment of `cumCost a b K`, so the
  chunks of a request cost `a m + b m (K + m/2)` however it is split.
* `packed_le`, `window_work_le` : iterations do not overlap, so the work of
  requests served only inside `[A, D]` is at most `D - A`.
* `lindley_attained`, `lindley_ge` : the FIFO (Lindley) recursion is
  `max_{i ≤ k} (A i + Σ_{l=i}^{k} S l)`.
* `fifo_lower`, `engine_lower` : a schedule that serves only arrived
  requests, never more than they need, in arrival order, spending at least
  the work's cost in each iteration, finishes request `k` no earlier than
  the FIFO single server.
* `tokensIn_fillIter`, `amountOf_le_want`, `amountOf_fifo` : serQ's iteration
  (`SerqLang.Exec.fillIter`, which `Exec.assign` builds,
  `SerqLang.Exec.assign_eq_fillIter`) gives each request its job's amount of
  the greedy fill, no more than it wants, in serving order.
* `serq_engine_lower`, `serq_machines_lower` : hence serQ's engine without a
  chunk cap, read off its machines (`startIteration`'s `assign`), completes
  every request no earlier than the FIFO prefill server with work
  `a m + b m (K + m/2)`, given what is still assumed about the run: nobody
  waits for the engine, no growth past an allocation, the residents are the
  arrived unfinished requests in arrival order (`hres`, `hjob`), and each
  iteration lasts at least its chunks' cost (`hdur`, which `D.cost` must
  dominate). Those are invariants of `Exec.step` to prove next.

The paper does not cite this module yet; its `prop:price` assumes the FIFO
queue this module derives.
-/
import Mathlib.Tactic
import Serq.Fill

namespace ServingQueueTheory
namespace StepEngine

open Finset

/-! ### The cost of a request does not depend on how it is chunked -/

/-- Cost of the first `p` tokens of a request whose cached prefix is `K`:
`a p` for the dense layers, `b (K p + p²/2)` for attention. -/
noncomputable def cumCost (a b K p : ℝ) : ℝ := a * p + b * (K * p + p ^ 2 / 2)

theorem cumCost_zero (a b K : ℝ) : cumCost a b K 0 = 0 := by
  simp [cumCost]

/-- A chunk of `x` tokens at position `p` costs an increment of `cumCost`. -/
theorem chunk_cost_telescopes (a b K p x : ℝ) :
    a * x + b * x * (K + p + x / 2) = cumCost a b K (p + x) - cumCost a b K p := by
  unfold cumCost; ring

/-- Chunks `x 0, x 1, …` served one after the other cost `cumCost` of their total. -/
theorem chunks_cost_sum (a b K : ℝ) (x : ℕ → ℝ) (n : ℕ) :
    ∑ j ∈ range n, (a * x j + b * x j * (K + (∑ i ∈ range j, x i) + x j / 2))
      = cumCost a b K (∑ j ∈ range n, x j) := by
  induction n with
  | zero => simp [cumCost_zero]
  | succ n ih =>
    rw [sum_range_succ, ih, sum_range_succ, chunk_cost_telescopes]
    ring

/-! ### Iterations do not overlap -/

/-- Iterations `j` occupy `[s j, e j]`, with `s j ≤ e j ≤ s (j+1)`. The
iterations before `J` that lie inside `[A, D]` last at most
`max 0 (min D (s J) - A)`. -/
theorem packed_le_aux (s e : ℕ → ℝ) (hse : ∀ j, s j ≤ e j) (hes : ∀ j, e j ≤ s (j + 1))
    (A D : ℝ) (J : ℕ) :
    ∑ j ∈ (range J).filter (fun j => A ≤ s j ∧ e j ≤ D), (e j - s j)
      ≤ max 0 (min D (s J) - A) := by
  induction J with
  | zero => simp
  | succ J ih =>
    rw [range_add_one, filter_insert]
    have hmono : s J ≤ s (J + 1) := (hse J).trans (hes J)
    by_cases hJ : A ≤ s J ∧ e J ≤ D
    · rw [if_pos hJ, sum_insert (by simp)]
      have h1 : max 0 (min D (s J) - A) = s J - A := by
        have : min D (s J) = s J := min_eq_right ((hse J).trans hJ.2)
        rw [this]; exact max_eq_right (by linarith [hJ.1])
      have h2 : e J ≤ min D (s (J + 1)) := le_min hJ.2 (hes J)
      have := ih
      rw [h1] at this
      calc e J - s J + ∑ j ∈ (range J).filter (fun j => A ≤ s j ∧ e j ≤ D), (e j - s j)
          ≤ e J - s J + (s J - A) := by linarith
        _ ≤ max 0 (min D (s (J + 1)) - A) := by
          apply le_max_of_le_right; linarith
    · rw [if_neg hJ]
      refine ih.trans (max_le_max le_rfl ?_)
      linarith [min_le_min (le_refl D) hmono]

/-- The iterations inside `[A, D]` last at most `max 0 (D - A)` in total. -/
theorem packed_le (s e : ℕ → ℝ) (hse : ∀ j, s j ≤ e j) (hes : ∀ j, e j ≤ s (j + 1))
    (A D : ℝ) (J : ℕ) :
    ∑ j ∈ (range J).filter (fun j => A ≤ s j ∧ e j ≤ D), (e j - s j) ≤ max 0 (D - A) :=
  (packed_le_aux s e hse hes A D J).trans (max_le_max le_rfl (by linarith [min_le_left D (s J)]))

/-! ### Work served inside a window -/

/-- A schedule of `J` iterations over the requests `R`: iteration `j` runs on
`[s j, e j]` and spends `w j l ≥ 0` seconds of work on request `l`, at most
its length in total. If every request of `I ⊆ R` is served only by
iterations inside `[A, D]`, its total work is at most `max 0 (D - A)`. -/
theorem window_work_le (J : ℕ) (R I : Finset ℕ) (hI : I ⊆ R) (s e : ℕ → ℝ)
    (hse : ∀ j, s j ≤ e j) (hes : ∀ j, e j ≤ s (j + 1)) (w : ℕ → ℕ → ℝ)
    (hw : ∀ j l, 0 ≤ w j l) (hdur : ∀ j ∈ range J, ∑ l ∈ R, w j l ≤ e j - s j)
    (A D : ℝ)
    (hin : ∀ j ∈ range J, ∀ l ∈ I, 0 < w j l → A ≤ s j ∧ e j ≤ D) :
    ∑ l ∈ I, ∑ j ∈ range J, w j l ≤ max 0 (D - A) := by
  rw [sum_comm]
  refine le_trans ?_ (packed_le s e hse hes A D J)
  rw [sum_filter]
  refine sum_le_sum fun j hj => ?_
  split_ifs with hwin
  · exact (sum_le_sum_of_subset_of_nonneg hI fun l _ _ => hw j l).trans (hdur j hj)
  · refine le_of_eq (sum_eq_zero fun l hl => ?_)
    rcases (hw j l).lt_or_eq with h | h
    · exact absurd (hin j hj l hl h) hwin
    · exact h.symm

/-! ### The FIFO recursion -/

/-- The FIFO single-server (Lindley) recursion: departure times of requests
arriving at `A k` with work `S k`, served in arrival order. -/
def lindley (A S : ℕ → ℝ) : ℕ → ℝ
  | 0 => A 0 + S 0
  | k + 1 => max (A (k + 1)) (lindley A S k) + S (k + 1)

/-- The recursion is attained by some busy-period start `i ≤ k`. -/
theorem lindley_attained (A S : ℕ → ℝ) (k : ℕ) :
    ∃ i ≤ k, lindley A S k = A i + ∑ l ∈ Icc i k, S l := by
  induction k with
  | zero => exact ⟨0, le_rfl, by simp [lindley]⟩
  | succ k ih =>
    obtain ⟨i, hik, hi⟩ := ih
    by_cases h : lindley A S k ≤ A (k + 1)
    · refine ⟨k + 1, le_rfl, ?_⟩
      simp [lindley, max_eq_left h]
    · refine ⟨i, by omega, ?_⟩
      have h : A (k + 1) < lindley A S k := lt_of_not_ge h
      have hs : Icc i (k + 1) = insert (k + 1) (Icc i k) := by
        ext x; simp only [mem_Icc, mem_insert]; omega
      rw [lindley, max_eq_right h.le, hi, hs, sum_insert (by simp)]
      ring

/-- Every busy-period start bounds the recursion from below. -/
theorem lindley_ge (A S : ℕ → ℝ) (k : ℕ) :
    ∀ i ≤ k, A i + ∑ l ∈ Icc i k, S l ≤ lindley A S k := by
  induction k with
  | zero => intro i hi; obtain rfl : i = 0 := by omega
            simp [lindley]
  | succ k ih =>
    intro i hi
    rcases Nat.lt_or_ge i (k + 1) with h | h
    · have hs : Icc i (k + 1) = insert (k + 1) (Icc i k) := by
        ext x; simp only [mem_Icc, mem_insert]; omega
      rw [hs, sum_insert (by simp), lindley]
      have := ih i (by omega)
      linarith [le_max_right (A (k + 1)) (lindley A S k)]
    · obtain rfl : i = k + 1 := by omega
      simp only [Icc_self, sum_singleton, lindley]
      linarith [le_max_left (A (k + 1)) (lindley A S k)]

/-! ### Any order-preserving schedule is no faster than the FIFO server -/

/-- **Lower bound.** Requests `0, …, n-1` arrive at nondecreasing times `A`.
A schedule of `J` iterations (`s j ≤ e j ≤ s (j+1)`) spends `w j l ≥ 0`
seconds of work on request `l` in iteration `j`, and at most the iteration's
length on all requests together. Suppose it serves a request only after it
arrives (`w j l > 0 → A l ≤ s j`), and that every request `l ≤ k` receives
its whole work `S l` in iterations that end by `D ≥ A k`. Then
`D ≥ lindley A S k`: request `k` cannot be done before the FIFO single
server with work `S` would finish it. -/
theorem fifo_lower (n J : ℕ) (A S : ℕ → ℝ) (hA : Monotone A)
    (s e : ℕ → ℝ) (hse : ∀ j, s j ≤ e j) (hes : ∀ j, e j ≤ s (j + 1))
    (w : ℕ → ℕ → ℝ) (hw : ∀ j l, 0 ≤ w j l)
    (hdur : ∀ j ∈ range J, ∑ l ∈ range n, w j l ≤ e j - s j)
    (harr : ∀ j ∈ range J, ∀ l ∈ range n, 0 < w j l → A l ≤ s j)
    (k : ℕ) (hk : k < n) (D : ℝ) (hDA : A k ≤ D)
    (hS : ∀ l ≤ k, S l = ∑ j ∈ range J, w j l)
    (hdone : ∀ j ∈ range J, ∀ l ≤ k, 0 < w j l → e j ≤ D) :
    lindley A S k ≤ D := by
  obtain ⟨i, hik, hi⟩ := lindley_attained A S k
  have hsub : Icc i k ⊆ range n := fun l hl => by
    have := mem_Icc.mp hl; simp only [mem_range]; omega
  have hwin := window_work_le J (range n) (Icc i k) hsub s e hse hes w hw hdur (A i) D
    (fun j hj l hl hpos => by
      have hl' := mem_Icc.mp hl
      exact ⟨(hA hl'.1).trans (harr j hj l (hsub hl) hpos), hdone j hj l hl'.2 hpos⟩)
  have hAi : A i ≤ D := (hA hik).trans hDA
  rw [max_eq_right (by linarith)] at hwin
  have hsum : ∑ l ∈ Icc i k, S l = ∑ l ∈ Icc i k, ∑ j ∈ range J, w j l :=
    sum_congr rfl fun l hl => hS l (mem_Icc.mp hl).2
  linarith

/-! ### The engine that fills its budget in arrival order -/

/-- Monotone iteration ends. -/
theorem ends_mono (s e : ℕ → ℝ) (hse : ∀ j, s j ≤ e j) (hes : ∀ j, e j ≤ s (j + 1)) :
    Monotone e :=
  monotone_nat_of_le_succ fun j => (hes j).trans (hse (j + 1))

/-- **The step engine is no faster than the FIFO prefill server.**
Iteration `j` (on `[s j, e j]`) gives `x j l` tokens to request `l`, which
has `m l` tokens to prefill on a cached prefix of `K l`; its chunk costs
`a x + b x (K + p + x/2)` at position `p` (the tokens it already had), and
the iteration lasts at least the cost of its chunks. The scheduler

* serves only requests that have arrived (`x j l > 0 → A l ≤ s j`),
* never serves more than a request needs, and
* fills the budget in arrival order: if it gives tokens to `l'` it first
  gives every earlier request `l < l'` all it still needs.

This is vLLM v1's rule without a per-request chunk cap (running requests
first, then the waiting queue, in arrival order, while budget is left), and
serQ's `step` stage with `serve admission` and `chunk 0`. If request `k`
receives its last tokens in iteration `jk`, then
`e jk ≥ lindley A S k` with `S l = a m l + b m l (K l + m l / 2)`: the
FIFO single server whose work is the request's prefill cost, with the
per-iteration cost fully shared. -/
theorem engine_lower (n J : ℕ) (A : ℕ → ℝ) (hA : Monotone A) (a b : ℝ)
    (ha : 0 ≤ a) (hb : 0 ≤ b) (K : ℕ → ℝ) (hK : ∀ l, 0 ≤ K l)
    (m : ℕ → ℕ) (x : ℕ → ℕ → ℕ)
    (s e : ℕ → ℝ) (hse : ∀ j, s j ≤ e j) (hes : ∀ j, e j ≤ s (j + 1))
    (hdur : ∀ j ∈ range J, ∑ l ∈ range n,
      (a * x j l + b * x j l * (K l + (∑ i ∈ range j, (x i l : ℝ)) + x j l / 2)) ≤ e j - s j)
    (harr : ∀ j ∈ range J, ∀ l ∈ range n, 0 < x j l → A l ≤ s j)
    (hfeas : ∀ j ∈ range J, ∀ l ∈ range n, ∑ i ∈ range (j + 1), x i l ≤ m l)
    (hfifo : ∀ j ∈ range J, ∀ l l', l < l' → l' < n → 0 < x j l' →
      ∑ i ∈ range (j + 1), x i l = m l)
    (k : ℕ) (hk : k < n) (jk : ℕ) (hjk : jk < J) (hlast : 0 < x jk k)
    (hcomp : ∑ i ∈ range (jk + 1), x i k = m k) :
    lindley A (fun l => cumCost a b (K l) (m l)) k ≤ e jk := by
  -- every request `l ≤ k` is complete after iteration `jk`
  have hcompl : ∀ l ≤ k, ∑ i ∈ range (jk + 1), x i l = m l := fun l hl => by
    rcases hl.lt_or_eq with h | rfl
    · exact hfifo jk (mem_range.mpr hjk) l k h hk hlast
    · exact hcomp
  -- and receives nothing afterwards
  have hafter : ∀ l ≤ k, ∀ j ∈ range J, jk < j → x j l = 0 := fun l hl j hj hjj => by
    have hf := hfeas j hj l (mem_range.mpr (by omega))
    have hsplit : ∑ i ∈ range (j + 1), x i l
        = ∑ i ∈ range (jk + 1), x i l + ∑ i ∈ Ico (jk + 1) (j + 1), x i l := by
      rw [sum_range_add_sum_Ico _ (by omega)]
    have hmem : j ∈ Ico (jk + 1) (j + 1) := mem_Ico.mpr ⟨by omega, by omega⟩
    have := single_le_sum (f := fun i => x i l) (fun _ _ => Nat.zero_le _) hmem
    rw [hsplit, hcompl l hl] at hf
    omega
  have hemono := ends_mono s e hse hes
  -- the work of a chunk, and its positivity
  set w : ℕ → ℕ → ℝ := fun j l =>
    a * x j l + b * x j l * (K l + (∑ i ∈ range j, (x i l : ℝ)) + x j l / 2) with hwdef
  have hw : ∀ j l, 0 ≤ w j l := fun j l => by
    simp only [hwdef]
    have : (0 : ℝ) ≤ ∑ i ∈ range j, (x i l : ℝ) := sum_nonneg fun _ _ => Nat.cast_nonneg _
    have := hK l
    positivity
  have hwpos : ∀ j l, 0 < w j l → 0 < x j l := fun j l h => by
    by_contra h0
    have : x j l = 0 := by omega
    simp [hwdef, this] at h
  refine fifo_lower n J A _ hA s e hse hes w hw hdur
    (fun j hj l hl h => harr j hj l hl (hwpos j l h)) k hk (e jk)
    ((harr jk (mem_range.mpr hjk) k (mem_range.mpr hk) hlast).trans (hse jk)) ?_ ?_
  · -- the request's work is its prefill cost however it was chunked
    intro l hl
    have hJ : ∑ j ∈ range J, (x j l : ℝ) = m l := by
      have hsplit : ∑ j ∈ range J, (x j l : ℝ)
          = ∑ j ∈ range (jk + 1), (x j l : ℝ) + ∑ j ∈ Ico (jk + 1) J, (x j l : ℝ) :=
        (sum_range_add_sum_Ico _ (by omega)).symm
      have hz : ∑ j ∈ Ico (jk + 1) J, (x j l : ℝ) = 0 := sum_eq_zero fun j hj => by
        have := mem_Ico.mp hj
        simp [hafter l hl j (mem_range.mpr this.2) (by omega)]
      rw [hsplit, hz, add_zero]
      exact_mod_cast hcompl l hl
    have := chunks_cost_sum a b (K l) (fun j => (x j l : ℝ)) J
    simp only at this
    rw [hJ] at this
    simp only [hwdef]
    exact this.symm
  · intro j hj l hl hpos
    have hx := hwpos j l hpos
    have : j ≤ jk := by
      by_contra hc
      have := hafter l hl j hj (by omega)
      omega
    exact hemono this

/-! ### The engine of serQ

From here on the engine is serQ's, not a model of it: an iteration of
`SerqLang.Exec` is `fillIter` of its residents (`SerqLang.Exec.assign_eq_fillIter`,
with nothing growing past its allocation and nobody waiting for the engine),
and a request's tokens in it are what `Exec.endIteration` subtracts. -/

open SerqLang.Exec in
/-- The tokens an iteration (a list of (owner, tokens), `Exec.Machine.iter`)
gives request `l`: what `Exec.endIteration` subtracts from its job. -/
def tokensIn (it : List (ℕ × ℕ)) (l : ℕ) : ℕ := ((it.filter (·.1 = l)).map (·.2)).sum

open SerqLang.Exec in
/-- What the greedy fill of `js` from `left` gives the job owned by `l` (its
first job; 0 if it has none). -/
def amountOf (D : Deployment) : List Job → ℕ → ℕ → ℕ
  | [], _, _ => 0
  | j :: js, left, l =>
    if j.owner = l then min (wantOf D j) left
    else amountOf D js (left - min (wantOf D j) left) l

open SerqLang.Exec in
theorem amountOf_zero (D : Deployment) : ∀ (js : List Job) (l : ℕ), amountOf D js 0 l = 0
  | [], _ => rfl
  | j :: js, l => by unfold amountOf; split_ifs <;> simp [amountOf_zero D js l]

open SerqLang.Exec in
/-- A request with no job gets nothing. -/
theorem amountOf_not_mem (D : Deployment) :
    ∀ (js : List Job) (left l : ℕ), l ∉ js.map (·.owner) → amountOf D js left l = 0
  | [], _, _, _ => rfl
  | j :: js, left, l, h => by
    rw [List.map_cons, List.mem_cons, not_or] at h
    unfold amountOf
    rw [if_neg (fun e => h.1 e.symm)]
    exact amountOf_not_mem D js _ l h.2

open SerqLang.Exec in
/-- The iteration's tokens for `l` are its job's amount (owners distinct). -/
theorem tokensIn_fillIter (D : Deployment) :
    ∀ (js : List Job) (left l : ℕ), (js.map (·.owner)).Nodup →
      tokensIn (fillIter D js left) l = amountOf D js left l
  | [], _, _, _ => rfl
  | j :: js, left, l, hnd => by
    rw [List.map_cons, List.nodup_cons] at hnd
    have ih : ∀ left', tokensIn (fillIter D js left') l = amountOf D js left' l :=
      fun left' => tokensIn_fillIter D js left' l hnd.2
    unfold fillIter amountOf
    by_cases ho : j.owner = l
    · have hz : ∀ left', amountOf D js left' l = 0 := fun left' =>
        amountOf_not_mem D js left' l (ho ▸ hnd.1)
      rw [if_pos ho]
      by_cases h0 : min (wantOf D j) left = 0
      · rw [if_pos h0, ih, hz, h0]
      · rw [if_neg h0]
        by_cases h1 : left - min (wantOf D j) left = 0
        · rw [if_pos h1]
          simp [tokensIn, ho]
        · rw [if_neg h1]
          have := ih (left - min (wantOf D j) left)
          rw [hz] at this
          unfold tokensIn at this ⊢
          rw [List.filter_cons_of_pos (by simp [ho]), List.map_cons, List.sum_cons, this]
          rfl
    · rw [if_neg ho]
      by_cases h0 : min (wantOf D j) left = 0
      · rw [if_pos h0, ih, h0, Nat.sub_zero]
      · rw [if_neg h0]
        by_cases h1 : left - min (wantOf D j) left = 0
        · rw [if_pos h1, h1, amountOf_zero]
          simp [tokensIn, ho]
        · rw [if_neg h1]
          have := ih (left - min (wantOf D j) left)
          unfold tokensIn at this ⊢
          rw [List.filter_cons_of_neg (by simp [ho]), this]

open SerqLang.Exec in
/-- No job gets more than it wants. -/
theorem amountOf_le_want (D : Deployment) :
    ∀ (js : List Job) (left l : ℕ) (j : Job), j ∈ js → j.owner = l →
      (js.map (·.owner)).Nodup → amountOf D js left l ≤ wantOf D j
  | [], _, _, _, h, _, _ => by simp at h
  | x :: xs, left, l, j, hj, hl, hnd => by
    rw [List.map_cons, List.nodup_cons] at hnd
    unfold amountOf
    rcases List.mem_cons.mp hj with rfl | hj'
    · rw [if_pos hl]; exact min_le_left _ _
    · have hx : x.owner ≠ l := by
        intro h
        exact hnd.1 (List.mem_map.mpr ⟨j, hj', hl.trans h.symm⟩)
      rw [if_neg hx]
      exact amountOf_le_want D xs _ l j hj' hl hnd.2

open SerqLang.Exec in
/-- **The fill serves in order, by owner.** In a job list whose owners
increase, if the job of `l'` gets a token, the job of every `l < l'` in the
list got all it wanted. -/
theorem amountOf_fifo (D : Deployment) :
    ∀ (js : List Job) (left : ℕ), (js.map (·.owner)).Pairwise (· < ·) →
      ∀ (l l' : ℕ) (j : Job), j ∈ js → j.owner = l → l < l' →
        0 < amountOf D js left l' → amountOf D js left l = wantOf D j
  | [], _, _, _, _, _, h, _, _, _ => by simp at h
  | x :: xs, left, hs, l, l', j, hj, hl, hll', hpos => by
    rw [List.map_cons, List.pairwise_cons] at hs
    unfold amountOf at hpos ⊢
    rcases List.mem_cons.mp hj with rfl | hj'
    · rw [if_pos hl]
      rw [if_neg (by omega)] at hpos
      by_contra hne
      have hm : min (wantOf D j) left = left := by
        rcases le_total (wantOf D j) left with h | h
        · exact absurd (min_eq_left h) hne
        · exact min_eq_right h
      rw [hm, Nat.sub_self, amountOf_zero] at hpos
      exact lt_irrefl 0 hpos
    · have hxl : x.owner < l := hs.1 l (List.mem_map.mpr ⟨j, hj', hl⟩)
      rw [if_neg (by omega)]
      rw [if_neg (by omega)] at hpos
      exact amountOf_fifo D xs _ hs.2 l l' j hj' hl hll' hpos

open SerqLang.Exec in
/-- **serQ's engine is no faster than the FIFO prefill server.** Requests
`0, …, n-1` arrive at nondecreasing times `A` with `m l` tokens to prefill
on a cached prefix of `K l`. In iteration `j` (on `[s j, e j]`, lasting at
least the cost of its chunks) the engine of `D` (no chunk cap) serves the
job list `js j` from its budget: the iteration is `fillIter D (js j) D.budget`,
which is what `Exec.assign` builds (`SerqLang.Exec.assign_eq_fillIter`), and
request `l` receives `tokensIn` of it (what `Exec.endIteration` subtracts).
Suppose the residents of iteration `j` are the requests that have arrived
and are not done, in arrival order, each a prefill job wanting what it has
left (`hres`, `hjob`). Then a request that receives its last tokens in
iteration `jk` is done no earlier than the FIFO single server with work
`a m + b m (K + m/2)` would finish it. -/
theorem serq_engine_lower (D : Deployment) (hchunk : D.chunk = 0) (n J : ℕ) (A : ℕ → ℝ)
    (hA : Monotone A) (a b : ℝ) (ha : 0 ≤ a) (hb : 0 ≤ b) (K : ℕ → ℝ) (hK : ∀ l, 0 ≤ K l)
    (m : ℕ → ℕ) (js : ℕ → List Job) (s e : ℕ → ℝ)
    (hse : ∀ j, s j ≤ e j) (hes : ∀ j, e j ≤ s (j + 1))
    (x : ℕ → ℕ → ℕ) (hx : ∀ j ∈ range J, ∀ l, x j l = tokensIn (fillIter D (js j) D.budget) l)
    (hres : ∀ j ∈ range J, (js j).map (·.owner) =
      (List.range n).filter fun l => decide (A l ≤ s j) && decide (∑ i ∈ range j, x i l < m l))
    (hjob : ∀ j ∈ range J, ∀ job ∈ js j, job.mode = .prefill ∧
      job.left = m job.owner - ∑ i ∈ range j, x i job.owner)
    (hdur : ∀ j ∈ range J, ∑ l ∈ range n,
      (a * x j l + b * x j l * (K l + (∑ i ∈ range j, (x i l : ℝ)) + x j l / 2)) ≤ e j - s j)
    (k : ℕ) (hk : k < n) (jk : ℕ) (hjk : jk < J) (hlast : 0 < x jk k)
    (hcomp : ∑ i ∈ range (jk + 1), x i k = m k) :
    lindley A (fun l => cumCost a b (K l) (m l)) k ≤ e jk := by
  have hsorted : ∀ j ∈ range J, ((js j).map (·.owner)).Pairwise (· < ·) := fun j hj => by
    rw [hres j hj]; exact List.Pairwise.filter _ List.pairwise_lt_range
  have hnodup : ∀ j ∈ range J, ((js j).map (·.owner)).Nodup := fun j hj =>
    (hsorted j hj).imp (fun h => ne_of_lt h)
  have hxa : ∀ j ∈ range J, ∀ l, x j l = amountOf D (js j) D.budget l := fun j hj l => by
    rw [hx j hj, tokensIn_fillIter D _ _ _ (hnodup j hj)]
  have hmemres : ∀ j ∈ range J, ∀ l, l ∈ (js j).map (·.owner) ↔
      l < n ∧ A l ≤ s j ∧ ∑ i ∈ range j, x i l < m l := fun j hj l => by
    rw [hres j hj, List.mem_filter, List.mem_range]; simp
  -- a request with tokens is a resident, with a job
  have hjobOf : ∀ j ∈ range J, ∀ l, 0 < x j l → ∃ job ∈ js j, job.owner = l := by
    intro j hj l hpos
    by_contra hno
    push_neg at hno
    have := amountOf_not_mem D (js j) D.budget l (by
      rw [List.mem_map]; rintro ⟨job, hjb, he⟩; exact hno job hjb he)
    rw [hxa j hj] at hpos; omega
  -- a prefill job without a chunk cap wants what it has left
  have hwant : ∀ j ∈ range J, ∀ job ∈ js j,
      wantOf D job = m job.owner - ∑ i ∈ range j, x i job.owner := fun j hj job hjb => by
    obtain ⟨hmode, hleft⟩ := hjob j hj job hjb
    unfold wantOf; rw [hmode]; simp [hchunk, hleft]
  -- never more than a request needs
  have hfeas : ∀ j ∈ range J, ∀ l ∈ range n, ∑ i ∈ range (j + 1), x i l ≤ m l := by
    intro j hj
    induction j with
    | zero =>
      intro l _
      simp only [zero_add, range_one, sum_singleton]
      rcases Nat.eq_zero_or_pos (x 0 l) with h | h
      · omega
      · obtain ⟨job, hjb, he⟩ := hjobOf 0 hj l h
        have := hxa 0 hj l
        have hle := amountOf_le_want D (js 0) D.budget l job hjb he (hnodup 0 hj)
        rw [hwant 0 hj job hjb, he] at hle
        simp at hle; omega
    | succ j ih =>
      intro l hl
      have hj' : j ∈ range J := mem_range.mpr (by have := mem_range.mp hj; omega)
      have hprev := ih hj' l hl
      rw [sum_range_succ]
      rcases Nat.eq_zero_or_pos (x (j + 1) l) with h | h
      · rw [h]; omega
      · obtain ⟨job, hjb, he⟩ := hjobOf (j + 1) hj l h
        have hle := amountOf_le_want D (js (j + 1)) D.budget l job hjb he (hnodup (j + 1) hj)
        rw [hwant (j + 1) hj job hjb, he, ← hxa (j + 1) hj l] at hle
        omega
  refine engine_lower n J A hA a b ha hb K hK m x s e hse hes hdur ?_ hfeas ?_ k hk jk hjk hlast hcomp
  · -- served only after arriving
    intro j hj l _ hpos
    obtain ⟨job, hjb, he⟩ := hjobOf j hj l hpos
    exact ((hmemres j hj l).mp (List.mem_map.mpr ⟨job, hjb, he⟩)).2.1
  · -- arrival order
    intro j hj l l' hll' hl' hpos
    obtain ⟨job', hjb', he'⟩ := hjobOf j hj l' hpos
    have hres' := (hmemres j hj l').mp (List.mem_map.mpr ⟨job', hjb', he'⟩)
    have hl : l < n := by omega
    have hfj := hfeas j hj l (mem_range.mpr hl)
    rw [sum_range_succ] at hfj ⊢
    by_cases hdone : ∑ i ∈ range j, x i l < m l
    · -- `l` is a resident too, and got all it wanted
      have hmem : l ∈ (js j).map (·.owner) :=
        (hmemres j hj l).mpr ⟨hl, (hA hll'.le).trans hres'.2.1, hdone⟩
      obtain ⟨job, hjb, he⟩ := List.mem_map.mp hmem
      have hfull := amountOf_fifo D (js j) D.budget (hsorted j hj) l l' job hjb he hll'
        (by rw [← hxa j hj]; exact hpos)
      rw [hwant j hj job hjb, he, ← hxa j hj l] at hfull
      omega
    · -- `l` was already done, so it is no resident and gets nothing
      have hz : x j l = 0 := by
        rw [hxa j hj]
        exact amountOf_not_mem D (js j) D.budget l (fun hmem => hdone ((hmemres j hj l).mp hmem).2.2)
      omega

open SerqLang.Exec in
/-- **The same, read off serQ's machines.** Iteration `j` starts from the
machine `ms j`, and its tokens are those of the iteration `startIteration`
builds, `assign D 100000 {ms j with iter := []} 0 D.budget`. With no
`serve only` filter (`honly`), if nobody waits
for the engine, the jobs' owners are distinct and every growing job's
allocation covers the position it will reach, that iteration is `fillIter`
of the machine's jobs (`SerqLang.Exec.assign_iter_eq_fillIter`), so
`serq_engine_lower` applies with the machine's job list as the residents.
What is still assumed about the run: `hres`, `hjob` (the residents are the
arrived unfinished requests in arrival order, as prefill jobs wanting what
they have left; arrival order is the jobs' serving order) and `hdur` (the
iteration lasts at least the cost of its chunks, which `D.cost` must
dominate). -/
theorem serq_machines_lower (D : Deployment) (honly : D.only = none) (hchunk : D.chunk = 0) (n J : ℕ) (A : ℕ → ℝ)
    (hA : Monotone A) (a b : ℝ) (ha : 0 ≤ a) (hb : 0 ≤ b) (K : ℕ → ℝ) (hK : ∀ l, 0 ≤ K l)
    (m : ℕ → ℕ) (ms : ℕ → Machine) (s e : ℕ → ℝ)
    (hse : ∀ j, s j ≤ e j) (hes : ∀ j, e j ≤ s (j + 1))
    (hq : ∀ j ∈ range J, engineQueuesEmpty D (ms j))
    (hown : ∀ j ∈ range J, ((ms j).jobs.map (·.owner)).Nodup)
    (hcov : ∀ j ∈ range J, ∀ jb ∈ (ms j).jobs, ∀ p, jb.growing = some p →
      ∃ a x, holdOn (getS (ms j) jb.owner) p = some (a, x) ∧ x + wantOf D jb ≤ a)
    (hfuel : ∀ j ∈ range J, (ms j).jobs.length < 100000)
    (x : ℕ → ℕ → ℕ)
    (hx : ∀ j ∈ range J, ∀ l,
      x j l = tokensIn (assign D 100000 { ms j with iter := [] } 0 D.budget (ms j).preempts).iter l)
    (hres : ∀ j ∈ range J, (ms j).jobs.map (·.owner) =
      (List.range n).filter fun l => decide (A l ≤ s j) && decide (∑ i ∈ range j, x i l < m l))
    (hjob : ∀ j ∈ range J, ∀ job ∈ (ms j).jobs, job.mode = .prefill ∧
      job.left = m job.owner - ∑ i ∈ range j, x i job.owner)
    (hdur : ∀ j ∈ range J, ∑ l ∈ range n,
      (a * x j l + b * x j l * (K l + (∑ i ∈ range j, (x i l : ℝ)) + x j l / 2)) ≤ e j - s j)
    (k : ℕ) (hk : k < n) (jk : ℕ) (hjk : jk < J) (hlast : 0 < x jk k)
    (hcomp : ∑ i ∈ range (jk + 1), x i k = m k) :
    lindley A (fun l => cumCost a b (K l) (m l)) k ≤ e jk := by
  refine serq_engine_lower D hchunk n J A hA a b ha hb K hK m (fun j => (ms j).jobs) s e hse hes x
    ?_ hres hjob hdur k hk jk hjk hlast hcomp
  intro j hj l
  rw [hx j hj l]
  congr 1
  have := assign_iter_eq_fillIter D honly (ms j).preempts 100000 { ms j with iter := [] } 0 D.budget
    (fun q hv => hq j hj q hv) (hown j hj) (fun jb hjb => hcov j hj jb (by simpa using hjb))
    (by have := hfuel j hj; simp; omega)
  simpa using this

end StepEngine
end ServingQueueTheory
