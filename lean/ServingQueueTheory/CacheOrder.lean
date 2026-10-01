/-
# The order of service decides what a prefix cache can keep

Lecture 7 (`research/metastability.md`), not in the paper. A replica serves
turns of `N` sessions; its prefix cache holds at most `C` prefixes of equal
size (one per session), and a prefix enters the cache only when its session
is served. When the queue is saturated and turns are admitted in arrival
order (vLLM's FCFS admission), the sessions are served round-robin.

Key theorems:
* `round_hits_le_capacity` — whatever the eviction policy, in any `N`
  consecutive services of `N` distinct sessions at most `C` hit.
* `lru_round_robin_all_miss` — under LRU, round-robin service with `C < N`
  misses on every turn: the cyclic worst case.
* `pinned_round_hits` — pinning `C` sessions' prefixes and caching no other
  attains the bound: `C` hits per round.
* `mattson_lru_hit_iff` — Mattson's stack-distance criterion: a session finds
  its prefix under LRU exactly when fewer than `C` distinct sessions were
  served since its last turn. Under FCFS, a turn with `C` turns ahead misses.
* `lruRun_eq_take`, `recency_split` — the LRU cache is the head of the
  recency list.
-/
import Mathlib.Tactic

open Finset

namespace ServingQueueTheory

/-! ### Any policy -/

/-- `cache t` is the set of resident prefixes when the `t`-th turn is served
and `x t` its session. If the cache holds at most `C` prefixes and only the
served session's prefix can enter it, then among `N` consecutive services of
distinct sessions at most `C` find their prefix. -/
theorem round_hits_le_capacity (x : ℕ → ℕ) (cache : ℕ → Finset ℕ) (C N t0 : ℕ)
    (hcap : (cache t0).card ≤ C)
    (hstep : ∀ t, cache (t + 1) ⊆ cache t ∪ {x t})
    (hdist : ∀ i j, i < N → j < N → x (t0 + i) = x (t0 + j) → i = j) :
    ((range N).filter (fun i => x (t0 + i) ∈ cache (t0 + i))).card ≤ C := by
  -- the cache after `i` services of the round holds only the round's start or its first `i` sessions
  have hsub : ∀ i, cache (t0 + i) ⊆ cache t0 ∪ (range i).image (fun j => x (t0 + j)) := by
    intro i
    induction i with
    | zero => simp
    | succ i ih =>
      intro y hy
      have := hstep (t0 + i) hy
      rcases mem_union.1 this with h | h
      · rcases mem_union.1 (ih h) with h' | h'
        · exact mem_union_left _ h'
        · refine mem_union_right _ ?_
          obtain ⟨j, hj, rfl⟩ := mem_image.1 h'
          exact mem_image.2 ⟨j, mem_range.2 (by simp at hj; omega), rfl⟩
      · refine mem_union_right _ (mem_image.2 ⟨i, mem_range.2 (by omega), ?_⟩)
        simpa using (mem_singleton.1 h).symm
  -- a hit's session was already resident at the start of the round
  have hstart : ∀ i ∈ (range N).filter (fun i => x (t0 + i) ∈ cache (t0 + i)),
      x (t0 + i) ∈ cache t0 := by
    intro i hi
    rcases mem_filter.1 hi with ⟨hiN, hhit⟩
    rcases mem_union.1 (hsub i hhit) with h | h
    · exact h
    · obtain ⟨j, hj, hji⟩ := mem_image.1 h
      have := hdist j i (by simp at hj hiN; omega) (mem_range.1 hiN) hji
      simp at hj; omega
  calc ((range N).filter (fun i => x (t0 + i) ∈ cache (t0 + i))).card
      ≤ (cache t0).card := by
        apply card_le_card_of_injOn (fun i => x (t0 + i)) (fun i hi => hstart i hi)
        intro i hi j hj hij
        exact hdist i j (mem_range.1 (mem_filter.1 hi).1) (mem_range.1 (mem_filter.1 hj).1) hij
    _ ≤ C := hcap

/-- Pinning: sessions `0, …, C - 1` stay resident and no other prefix is
cached. -/
def pinCache (C : ℕ) : Finset ℕ := range C

theorem pinCache_card (C : ℕ) : (pinCache C).card ≤ C := by simp [pinCache]

/-- Only a served session's prefix may enter: here none ever does. -/
theorem pinCache_step (C s : ℕ) : pinCache C ⊆ pinCache C ∪ {s} := subset_union_left

/-- In round-robin order, session `k < N` is served at offset
`(k + N - t0 % N) % N` of the round that starts at `t0`. -/
theorem round_offset (N t0 k : ℕ) (hN : 0 < N) (hk : k < N) :
    (t0 + (k + N - t0 % N) % N) % N = k := by
  rw [Nat.add_mod_mod]
  have h1 := Nat.div_add_mod t0 N
  have h2 := Nat.mod_lt t0 hN
  have : t0 + (k + N - t0 % N) = k + N * (t0 / N + 1) := by
    rw [Nat.mul_add, Nat.mul_one]; omega
  rw [this, Nat.add_mul_mod_self_left, Nat.mod_eq_of_lt hk]

/-- With `C ≤ N` sessions pinned, every round of round-robin service has at
least `C` hits: the bound of `round_hits_le_capacity` is attained, while LRU
gets none (`lru_round_robin_all_miss`). -/
theorem pinned_round_hits (C N t0 : ℕ) (hCN : C ≤ N) :
    C ≤ ((range N).filter (fun i => (t0 + i) % N ∈ pinCache C)).card := by
  rcases Nat.eq_zero_or_pos N with hN | hN
  · omega
  let f : ℕ → ℕ := fun k => (k + N - t0 % N) % N
  have hf : ∀ k < C, f k ∈ (range N).filter (fun i => (t0 + i) % N ∈ pinCache C) := by
    intro k hk
    simp only [mem_filter, mem_range]
    refine ⟨Nat.mod_lt _ hN, ?_⟩
    rw [round_offset N t0 k hN (by omega)]
    simp [pinCache, hk]
  calc C = (range C).card := (card_range _).symm
    _ ≤ _ := by
      apply card_le_card_of_injOn f (fun k hk => hf k (mem_range.1 hk))
      intro a ha b hb hab
      have ha' : a < N := by have := mem_range.1 ha; omega
      have hb' : b < N := by have := mem_range.1 hb; omega
      rw [← round_offset N t0 a hN ha', ← round_offset N t0 b hN hb']
      exact congrArg (fun i => (t0 + i) % N) hab

/-! ### LRU -/

/-- One LRU step on a cache of at most `C` prefixes, most recent first: the
served session moves to the front, and the least recently used falls off. -/
def lruStep (C : ℕ) (L : List ℕ) (s : ℕ) : List ℕ := (s :: L.erase s).take C

/-- The LRU cache before the `t`-th service, when the `t`-th turn is session `x t`. -/
def lruRun (C : ℕ) (x : ℕ → ℕ) : ℕ → List ℕ
  | 0 => []
  | t + 1 => lruStep C (lruRun C x t) (x t)

/-- The session served now is not among the last `min t C < N` served. -/
theorem mod_not_mem_window (C N : ℕ) (hCN : C < N) (t : ℕ) :
    t % N ∉ (List.range (min t C)).map (fun j => (t - 1 - j) % N) := by
  simp only [List.mem_map, List.mem_range, not_exists, not_and]
  intro j hj heq
  have hjt : j < t := lt_of_lt_of_le hj (min_le_left _ _)
  have hjC : j < C := lt_of_lt_of_le hj (min_le_right _ _)
  -- (t - 1 - j) ≡ t (mod N) means N ∣ j + 1, impossible for 0 < j + 1 ≤ C < N
  have h0 : (t - (t - 1 - j)) % N = 0 := Nat.sub_mod_eq_zero_of_mod_eq heq.symm
  have he : t - (t - 1 - j) = j + 1 := by omega
  rw [he, Nat.mod_eq_of_lt (by omega)] at h0
  omega

/-- Round-robin order: before the `t`-th service the LRU cache holds the last
`min t C` sessions served, most recent first. -/
theorem lruRun_round_robin (C N : ℕ) (hCN : C < N) (t : ℕ) :
    lruRun C (· % N) t = (List.range (min t C)).map (fun j => (t - 1 - j) % N) := by
  induction t with
  | zero => simp [lruRun]
  | succ t ih =>
    simp only [lruRun, lruStep, ih]
    rw [List.erase_of_not_mem (mod_not_mem_window C N hCN t)]
    rcases C with _ | c
    · simp
    · have hmin : min (t + 1) (c + 1) = min t c + 1 := by omega
      rw [hmin, List.range_succ_eq_map, List.take_succ_cons, ← List.map_take,
        List.take_range]
      simp only [List.map_cons, List.map_map]
      congr 1
      have : min c (min t (c + 1)) = min t c := by omega
      rw [this]
      refine List.map_congr_left fun j hj => ?_
      simp only [Function.comp_apply]
      congr 1
      omega

/-- The cyclic worst case: under LRU with fewer slots than sessions, round-
robin service misses on every turn. -/
theorem lru_round_robin_all_miss (C N : ℕ) (hCN : C < N) (t : ℕ) :
    t % N ∉ lruRun C (· % N) t := by
  rw [lruRun_round_robin C N hCN t]
  exact mod_not_mem_window C N hCN t

/-! ### Mattson's stack-distance criterion -/

/-- The LRU recency list without truncation: every session served so far, most
recent first. -/
def recency (x : ℕ → ℕ) : ℕ → List ℕ
  | 0 => []
  | t + 1 => x t :: (recency x t).erase (x t)

theorem take_erase_take (l : List ℕ) (y n : ℕ) :
    ((l.take (n + 1)).erase y).take n = (l.erase y).take n := by
  induction l generalizing n with
  | nil => simp
  | cons a l ih =>
    by_cases h : a = y
    · subst h; simp
    · rw [List.take_succ_cons, List.erase_cons_tail (by simpa using h),
        List.erase_cons_tail (by simpa using h)]
      rcases n with _ | n
      · simp
      · rw [List.take_succ_cons, List.take_succ_cons, ih]

/-- The LRU cache of `C` prefixes is the first `C` entries of the recency list. -/
theorem lruRun_eq_take (C : ℕ) (x : ℕ → ℕ) (t : ℕ) :
    lruRun C x t = (recency x t).take C := by
  induction t with
  | zero => simp [lruRun, recency]
  | succ t ih =>
    simp only [lruRun, lruStep, recency, ih]
    rcases C with _ | c
    · simp
    · rw [List.take_succ_cons, List.take_succ_cons, take_erase_take]

/-- After session `s` is served at `t1`, the recency list is the sessions
served since, without repeats and most recent first, then `s`. -/
theorem recency_split (x : ℕ → ℕ) (s t1 : ℕ) (hs : x t1 = s) :
    ∀ d, (∀ u, t1 < u → u < t1 + 1 + d → x u ≠ s) →
      ∃ P Q, recency x (t1 + 1 + d) = P ++ s :: Q ∧ P.Nodup ∧ s ∉ P ∧
        P.toFinset = ((Finset.range d).image fun i => x (t1 + 1 + i)) := by
  intro d
  induction d with
  | zero =>
    intro _
    refine ⟨[], (recency x t1).erase s, ?_, by simp, by simp, by simp⟩
    simp [recency, hs]
  | succ d ih =>
    intro hne
    obtain ⟨P, Q, hR, hP, hsP, hD⟩ := ih fun u h1 h2 => hne u h1 (by omega)
    set y := x (t1 + 1 + d) with hy
    have hys : y ≠ s := hne _ (by omega) (by omega)
    have hR' : recency x (t1 + 1 + (d + 1)) = y :: (P ++ s :: Q).erase y := by
      rw [show t1 + 1 + (d + 1) = (t1 + 1 + d) + 1 by omega, recency, hR]
    by_cases hyP : y ∈ P
    · refine ⟨y :: P.erase y, Q, ?_, ?_, ?_, ?_⟩
      · rw [hR', List.erase_append_left _ hyP]; rfl
      · exact List.nodup_cons.2 ⟨fun h => (List.Nodup.not_mem_erase hP) h, hP.erase y⟩
      · simp only [List.mem_cons, not_or]
        exact ⟨hys.symm, fun h => hsP (List.mem_of_mem_erase h)⟩
      · have : (y :: P.erase y).toFinset = P.toFinset := by
          ext z
          simp only [List.toFinset_cons, Finset.mem_insert, List.mem_toFinset,
            hP.mem_erase_iff]
          constructor
          · rintro (rfl | ⟨_, h⟩) <;> assumption
          · intro h; by_cases hz : z = y
            · exact Or.inl hz
            · exact Or.inr ⟨hz, h⟩
        rw [this, hD, Finset.range_add_one, Finset.image_insert, ← hy,
          Finset.insert_eq_of_mem]
        rw [← hD]; simpa using hyP
    · refine ⟨y :: P, Q.erase y, ?_, List.nodup_cons.2 ⟨hyP, hP⟩, ?_, ?_⟩
      · rw [hR', List.erase_append_right _ hyP, List.erase_cons_tail (by simpa using hys.symm)]
        rfl
      · simp only [List.mem_cons, not_or]; exact ⟨hys.symm, hsP⟩
      · rw [List.toFinset_cons, hD, Finset.range_add_one, Finset.image_insert, ← hy]

/-- Mattson's stack-distance criterion for LRU: a session served at `t1` and not
since finds its prefix at `t` exactly when fewer than `C` distinct sessions were
served in between. -/
theorem mattson_lru_hit_iff (C : ℕ) (x : ℕ → ℕ) (s t1 d : ℕ) (hs : x t1 = s)
    (hne : ∀ u, t1 < u → u < t1 + 1 + d → x u ≠ s) :
    s ∈ lruRun C x (t1 + 1 + d) ↔
      ((Finset.range d).image fun i => x (t1 + 1 + i)).card < C := by
  obtain ⟨P, Q, hR, hP, hsP, hD⟩ := recency_split x s t1 hs d hne
  rw [lruRun_eq_take, hR, ← hD, List.toFinset_card_of_nodup hP]
  constructor
  · intro h
    by_contra hc
    push Not at hc
    rw [List.take_append_of_le_length hc] at h
    exact hsP (List.mem_of_mem_take h)
  · intro h
    rw [List.take_append, List.take_of_length_le (by omega)]
    apply List.mem_append_right
    rw [show C - P.length = (C - P.length - 1) + 1 by omega, List.take_succ_cons]
    simp

end ServingQueueTheory
