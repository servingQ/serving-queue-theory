/-
# Miss feedback: the hit rate depends on the wait, and the wait on the hit rate

Analytic extension suggested by the testbed replays (research/analytic-memory.md):
a returning turn finds its prefix with a probability that falls with its
absence, the think time plus its own wait, because the admissions ahead of it
evict least recently used blocks; the wait in turn falls with the hit rate.
With `W h` the mean wait at hit rate `h` (nonincreasing) and `G T` the
probability that a prefix survives an absence `T` (nonincreasing), the
realised hit rate is `H h = G (Z + W h)`, and an equilibrium is a fixed point
`H h = h` on `[0, 1]`.

Key theorems (the order-theoretic ones need no continuity):
* `feedback_extremal`, `unit_feedback_extremal` — a monotone feedback map has a
  least and a greatest equilibrium (Knaster–Tarski); on `[0,1]` every
  equilibrium lies between them.
* `feedback_gfp_mono`, `feedback_lfp_mono`, `unit_feedback_greatest_mono` — a
  map that is pointwise higher has higher least and greatest equilibria.
* `feedback_bistable`, `unit_feedback_bistable` — if all-miss maps to all-miss
  and some `a > 0` has `H a ≥ a`, the least equilibrium is 0 and the greatest
  is at least `a`: two distinct equilibria.
* `pkFeedback`, `pkFeedback_monotoneOn`, `pkFeedback_zero_of_overload`,
  `pkFeedback_collapse`, `pkFeedback_absorbing` — the prefill-bound instance: survival of the absence
  `Z + W(h)` with the PK wait of the hit/miss mixture, and 0 where the stage is
  overloaded; it is monotone on `[0,1]`, and it vanishes at `h = 0` when the
  all-miss load `λ S_miss` is at least 1.
* `feedback_map_monotone`, `feedback_map_monotone_two_channel` — `H` is
  monotone, also when survival depends on the pool state (the pool channel).
* `feedback_equilibrium_exists` — a continuous `H` from `[0,1]` to `[0,1]` has
  an equilibrium.
* `feedback_equilibrium_above` — if `H a ≥ a`, there is an equilibrium in
  `[a, 1]` (used for bistability and comparative statics).
* `feedback_comparative_statics` — a change that raises `H` pointwise leaves an
  equilibrium at or above any equilibrium of the old map.
* `forced_miss_equilibrium`, `forced_miss_amplified` — for an affine `H` with
  slope `k ∈ [0,1)`, forcing a fraction `δ` of turns to miss moves the
  equilibrium by `δ c / ((1-k)(1-(1-δ)k))`, at least `δ` times the old hit rate.
-/
import Mathlib.Tactic
import Mathlib.Topology.Order.IntermediateValue
import Mathlib.Topology.Algebra.Order.Field
import Mathlib.Order.FixedPoints
import Mathlib.Order.CompleteLatticeIntervals
import ServingQueueTheory.CacheReuse

open Set

namespace ServingQueueTheory

/-- The realised hit rate is monotone in the hit rate when the wait falls with
the hit rate and survival falls with the absence. -/
theorem feedback_map_monotone (W G : ℝ → ℝ) (Z : ℝ)
    (hW : Antitone W) (hG : Antitone G) :
    Monotone (fun h => G (Z + W h)) := by
  intro x y hxy
  exact hG (by linarith [hW hxy])

/-- Both channels: survival `G T h` falls with the absence `T` (the wait
channel) and rises with the hit rate `h` (the pool channel: fewer misses insert
fewer tokens, so the eviction horizon is longer). The map is still monotone. -/
theorem feedback_map_monotone_two_channel (W : ℝ → ℝ) (G : ℝ → ℝ → ℝ) (Z : ℝ)
    (hW : Antitone W) (hGT : ∀ h, Antitone (fun T => G T h)) (hGh : ∀ T, Monotone (G T)) :
    Monotone (fun h => G (Z + W h) h) := by
  intro x y hxy
  calc G (Z + W x) x ≤ G (Z + W y) x := hGT x (by linarith [hW hxy])
    _ ≤ G (Z + W y) y := hGh _ hxy

/-- An equilibrium exists in `[a, 1]` when `H a ≥ a` and `H 1 ≤ 1`. -/
theorem feedback_equilibrium_above (H : ℝ → ℝ) (a : ℝ) (ha : a ≤ 1)
    (hc : ContinuousOn H (Icc a 1)) (hHa : a ≤ H a) (hH1 : H 1 ≤ 1) :
    ∃ h ∈ Icc a 1, H h = h := by
  have hf : ContinuousOn (fun h => h - H h) (Icc a 1) :=
    (continuousOn_id.sub hc)
  have h0 : (0 : ℝ) ∈ Icc ((fun h => h - H h) a) ((fun h => h - H h) 1) := by
    constructor <;> simp only <;> linarith
  obtain ⟨h, hmem, hval⟩ := intermediate_value_Icc ha hf h0
  exact ⟨h, hmem, by simp only at hval; linarith⟩

/-- A continuous map of `[0,1]` into itself has an equilibrium. -/
theorem feedback_equilibrium_exists (H : ℝ → ℝ)
    (hc : ContinuousOn H (Icc 0 1)) (hmaps : ∀ h ∈ Icc (0 : ℝ) 1, H h ∈ Icc (0 : ℝ) 1) :
    ∃ h ∈ Icc (0 : ℝ) 1, H h = h :=
  feedback_equilibrium_above H 0 (by norm_num) hc
    (hmaps 0 ⟨le_refl 0, by norm_num⟩).1 (hmaps 1 ⟨by norm_num, le_refl 1⟩).2

/-- Comparative statics via the intermediate value theorem: if `x` is an
equilibrium of `H`, `K x ≥ H x` and `K` is continuous on `[x, 1]` into `[., 1]`,
then `K` has an equilibrium at or above `x`. Which changes raise the map
depends on the loop being open or closed (research/analytic-memory.md); the
continuity-free version is `unit_feedback_greatest_mono`. -/
theorem feedback_comparative_statics (H K : ℝ → ℝ) (x : ℝ) (hx1 : x ≤ 1)
    (hfix : H x = x) (hle : H x ≤ K x) (hc : ContinuousOn K (Icc x 1)) (hK1 : K 1 ≤ 1) :
    ∃ y ∈ Icc x 1, K y = y :=
  feedback_equilibrium_above K x hx1 hc (by linarith) hK1

/-- Forced misses with an affine feedback map `H h = c + k h`: forcing a
fraction `δ` of turns to miss makes the realised hit rate `(1-δ) H h`, and the
equilibrium is `(1-δ) c / (1 - (1-δ) k)`. -/
theorem forced_miss_equilibrium (c k δ : ℝ) (hk0 : 0 ≤ k) (hk1 : k < 1) (hδ0 : 0 ≤ δ) :
    let h := (1 - δ) * c / (1 - (1 - δ) * k)
    h = (1 - δ) * (c + k * h) := by
  intro h
  have hpos : 0 < 1 - (1 - δ) * k := by nlinarith
  simp only [h]
  field_simp
  ring

/-- The equilibrium falls by `δ c / ((1-k)(1-(1-δ)k))`, which is at least `δ`
times the old equilibrium `c/(1-k)`: the direct misses plus those they induce. -/
theorem forced_miss_amplified (c k δ : ℝ) (hc : 0 ≤ c) (hk0 : 0 ≤ k) (hk1 : k < 1)
    (hδ0 : 0 ≤ δ) (hδ1 : δ ≤ 1) :
    c / (1 - k) - (1 - δ) * c / (1 - (1 - δ) * k)
        = δ * c / ((1 - k) * (1 - (1 - δ) * k)) ∧
      δ * (c / (1 - k)) ≤ c / (1 - k) - (1 - δ) * c / (1 - (1 - δ) * k) := by
  have h1 : 0 < 1 - k := by linarith
  have h2 : 0 < 1 - (1 - δ) * k := by nlinarith
  have heq : c / (1 - k) - (1 - δ) * c / (1 - (1 - δ) * k)
      = δ * c / ((1 - k) * (1 - (1 - δ) * k)) := by
    rw [div_sub_div _ _ (ne_of_gt h1) (ne_of_gt h2)]
    congr 1
    ring
  refine ⟨heq, ?_⟩
  rw [heq, ← mul_div_assoc]
  apply div_le_div_of_nonneg_left (mul_nonneg hδ0 hc) (mul_pos h1 h2)
  nlinarith [mul_nonneg hδ0 hk0, mul_nonneg (sub_nonneg.mpr hδ1) hk0]

/-! ### Knaster–Tarski: extremal equilibria without continuity -/

section Tarski
variable {α : Type*} [CompleteLattice α]

/-- A monotone feedback map has a least and a greatest equilibrium. -/
theorem feedback_extremal (f : α →o α) :
    IsLeast (Function.fixedPoints f) f.lfp ∧ IsGreatest (Function.fixedPoints f) f.gfp :=
  ⟨f.isLeast_lfp, f.isGreatest_gfp⟩

/-- A pointwise higher map has a higher greatest equilibrium. -/
theorem feedback_gfp_mono {f g : α →o α} (hfg : f ≤ g) : f.gfp ≤ g.gfp :=
  g.le_gfp (le_of_eq_of_le f.map_gfp.symm (hfg f.gfp))

/-- A pointwise higher map has a higher least equilibrium. -/
theorem feedback_lfp_mono {f g : α →o α} (hfg : f ≤ g) : f.lfp ≤ g.lfp :=
  f.lfp_le (le_of_le_of_eq (hfg g.lfp) g.map_lfp)

/-- Bistability: if the bottom (all-miss) is mapped to itself and some `a ≠ ⊥`
has `a ≤ f a`, the least equilibrium is `⊥` and the greatest is at least `a`. -/
theorem feedback_bistable (f : α →o α) (hbot : f ⊥ = ⊥) {a : α} (ha : a ≤ f a) (hne : a ≠ ⊥) :
    f.lfp = ⊥ ∧ a ≤ f.gfp ∧ f.lfp < f.gfp := by
  have hl : f.lfp = ⊥ := le_antisymm (f.lfp_le (le_of_eq hbot)) bot_le
  have hg : a ≤ f.gfp := f.le_gfp ha
  exact ⟨hl, hg, hl ▸ lt_of_lt_of_le (bot_lt_iff_ne_bot.mpr hne) hg⟩

end Tarski

/-! ### The unit interval of hit rates -/

section Unit

instance fact_zero_le_one_real : Fact ((0 : ℝ) ≤ 1) := ⟨zero_le_one⟩

/-- A monotone map of `[0,1]` into itself, as an order homomorphism of the
complete lattice `Icc 0 1`. -/
noncomputable def unitFeedback (H : ℝ → ℝ) (hmono : MonotoneOn H (Icc 0 1))
    (hmaps : ∀ h ∈ Icc (0 : ℝ) 1, H h ∈ Icc (0 : ℝ) 1) : Icc (0 : ℝ) 1 →o Icc (0 : ℝ) 1 where
  toFun x := ⟨H x, hmaps x x.2⟩
  monotone' x y hxy := hmono x.2 y.2 hxy

/-- Least and greatest equilibria of a monotone feedback map on `[0,1]`: every
equilibrium lies between them. No continuity is needed. -/
theorem unit_feedback_extremal (H : ℝ → ℝ) (hmono : MonotoneOn H (Icc 0 1))
    (hmaps : ∀ h ∈ Icc (0 : ℝ) 1, H h ∈ Icc (0 : ℝ) 1) :
    ∃ hl ∈ Icc (0 : ℝ) 1, ∃ hg ∈ Icc (0 : ℝ) 1, H hl = hl ∧ H hg = hg ∧
      ∀ h ∈ Icc (0 : ℝ) 1, H h = h → hl ≤ h ∧ h ≤ hg := by
  set f := unitFeedback H hmono hmaps
  obtain ⟨hlfix, hlmin⟩ := f.isLeast_lfp
  obtain ⟨hgfix, hgmax⟩ := f.isGreatest_gfp
  refine ⟨f.lfp, f.lfp.2, f.gfp, f.gfp.2, congrArg Subtype.val hlfix, congrArg Subtype.val hgfix, ?_⟩
  intro h hh hfix
  have hmem : (⟨h, hh⟩ : Icc (0 : ℝ) 1) ∈ Function.fixedPoints f := Subtype.ext hfix
  exact ⟨hlmin hmem, hgmax hmem⟩

/-- A pointwise higher monotone map on `[0,1]` (a larger pool, a lower load)
has a greatest equilibrium at least as high. -/
theorem unit_feedback_greatest_mono (H K : ℝ → ℝ) (hH : MonotoneOn H (Icc 0 1))
    (hK : MonotoneOn K (Icc 0 1)) (hHm : ∀ h ∈ Icc (0 : ℝ) 1, H h ∈ Icc (0 : ℝ) 1)
    (hKm : ∀ h ∈ Icc (0 : ℝ) 1, K h ∈ Icc (0 : ℝ) 1) (hle : ∀ h ∈ Icc (0 : ℝ) 1, H h ≤ K h) :
    ((unitFeedback H hH hHm).gfp : ℝ) ≤ (unitFeedback K hK hKm).gfp :=
  feedback_gfp_mono (f := unitFeedback H hH hHm) (g := unitFeedback K hK hKm) (fun x => hle x x.2)

/-- Two distinct extremal equilibria on `[0,1]`: if `H 0 = 0` and `H a ≥ a`
for some `a > 0`, the least equilibrium is 0 and the greatest is at least `a`.
This says nothing about attraction; for the prefill-bound instance see
`pkFeedback_absorbing`. -/
theorem unit_feedback_bistable (H : ℝ → ℝ) (hmono : MonotoneOn H (Icc 0 1))
    (hmaps : ∀ h ∈ Icc (0 : ℝ) 1, H h ∈ Icc (0 : ℝ) 1) (h0 : H 0 = 0)
    (a : ℝ) (ha : a ∈ Icc (0 : ℝ) 1) (hapos : 0 < a) (hHa : a ≤ H a) :
    ((unitFeedback H hmono hmaps).lfp : ℝ) = 0 ∧ a ≤ (unitFeedback H hmono hmaps).gfp := by
  set f := unitFeedback H hmono hmaps
  have hbot : f ⊥ = ⊥ := by
    apply Subtype.ext
    show H ((⊥ : Icc (0 : ℝ) 1) : ℝ) = ((⊥ : Icc (0 : ℝ) 1) : ℝ)
    rw [Set.Icc.coe_bot]
    exact h0
  have hne : (⟨a, ha⟩ : Icc (0 : ℝ) 1) ≠ ⊥ := by
    intro h; have := congrArg Subtype.val h; simp at this; linarith
  obtain ⟨hl, hg, -⟩ := feedback_bistable f hbot (a := ⟨a, ha⟩) hHa hne
  exact ⟨by rw [hl]; rfl, hg⟩

end Unit

/-! ### The prefill-bound instance -/

/-- The feedback map of the prefill-bound instance: survival `G` of the absence
`Z + W(h)` with the PK wait of the hit/miss mixture, and 0 where the prefill
stage is overloaded. -/
noncomputable def pkFeedback (G : ℝ → ℝ) (Z lam sHit sMiss : ℝ) (h : ℝ) : ℝ :=
  if mixtureUtilization lam h sHit sMiss < 1 then G (Z + mixtureWait lam h sHit sMiss) else 0

/-- The prefill-bound feedback map is monotone on `[0,1]`. -/
theorem pkFeedback_monotoneOn {G : ℝ → ℝ} {Z lam sHit sMiss : ℝ} (hG : Antitone G)
    (hG0 : ∀ t, 0 ≤ G t) (hlam : 0 < lam) (h0 : 0 ≤ sHit) (hsm : sHit ≤ sMiss) :
    MonotoneOn (pkFeedback G Z lam sHit sMiss) (Icc 0 1) := by
  intro p hp q hq hpq
  unfold pkFeedback
  by_cases hp' : mixtureUtilization lam p sHit sMiss < 1
  · have hq' : mixtureUtilization lam q sHit sMiss < 1 :=
      lt_of_le_of_lt (utilization_antitone hlam.le hsm hpq) hp'
    simp only [hp', hq', ↓reduceIte]
    exact hG (by linarith [pkWait_mixture_antitone hlam h0 hsm hpq hq.1 hq.2 hp'])
  · simp only [hp', ↓reduceIte]
    split_ifs
    · exact hG0 _
    · exact le_refl 0

/-- Where the prefill stage is overloaded the map vanishes. -/
theorem pkFeedback_zero_of_overload {G : ℝ → ℝ} {Z lam sHit sMiss h : ℝ}
    (hover : 1 ≤ mixtureUtilization lam h sHit sMiss) : pkFeedback G Z lam sHit sMiss h = 0 := by
  unfold pkFeedback
  simp only [not_lt.mpr hover, ↓reduceIte]

/-- Collapse: if the all-miss load `λ S_miss` is at least 1, all-miss maps to
all-miss. -/
theorem pkFeedback_collapse {G : ℝ → ℝ} {Z lam sHit sMiss : ℝ} (hover : 1 ≤ lam * sMiss) :
    pkFeedback G Z lam sHit sMiss 0 = 0 := by
  apply pkFeedback_zero_of_overload
  unfold mixtureUtilization meanService
  simpa using hover

/-- All-miss attracts the overloaded hit rates: if the stage is overloaded at
`h` and the all-miss load is at least 1, one step of the adjustment
`h ↦ H h` reaches 0 and the next stays there. -/
theorem pkFeedback_absorbing {G : ℝ → ℝ} {Z lam sHit sMiss h : ℝ}
    (hover0 : 1 ≤ lam * sMiss) (hover : 1 ≤ mixtureUtilization lam h sHit sMiss) :
    pkFeedback G Z lam sHit sMiss h = 0 ∧
      pkFeedback G Z lam sHit sMiss (pkFeedback G Z lam sHit sMiss h) = 0 := by
  have h1 := pkFeedback_zero_of_overload (G := G) (Z := Z) hover
  refine ⟨h1, ?_⟩
  rw [h1]
  exact pkFeedback_collapse hover0

end ServingQueueTheory
