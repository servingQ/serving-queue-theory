/-
# Program-aware routing: myopic vs. lookahead decisions, and the limit of
# affinity

Proposition (paper `prop:routing` and `prop:append`, §3.3 and App. B).  For a program `p` and candidate node `j`:

  myopic     `C_j = W_j + S_j`
  lookahead  `C_j = W_j + S_j + M_j + F_j`

where `M_j` is the state-migration (KV transfer) cost and `F_j` the
expected future cost.  We prove:

* `lookahead_prefers_iff`   : the exact disagreement condition between the
  two rules.
* `affinity_example`        : the worked example (300 vs 100+500).
* `kv_aware_example`        : KV-aware routing (300+100 vs 50+500).
* `affinity_not_always_optimal` : for *any* finite migration + future
  benefit, there is a stable load at which the affinity node's M/M/1 wait
  exceeds it, so migrating away becomes optimal.  Pure session affinity
  is therefore not an optimal policy.
* `append_prefill_rule`     : the PPD-style choice between prefill-node and
  decode-local append-prefill is the same comparison.
-/
import Mathlib.Tactic
import ServingQueueTheory.MM1

namespace ServingQueueTheory

def myopicCost (W S : ℝ) : ℝ := W + S
def lookaheadCost (W S M F : ℝ) : ℝ := W + S + M + F

/-- Node 1 (current, holds state) vs node 2 (candidate).  Lookahead prefers
node 1 iff the migration + future penalty of node 2 exceeds its myopic
advantage. -/
theorem lookahead_prefers_iff (W₁ S₁ F₁ W₂ S₂ M₂ F₂ : ℝ) :
    lookaheadCost W₁ S₁ 0 F₁ < lookaheadCost W₂ S₂ M₂ F₂ ↔
      myopicCost W₁ S₁ - myopicCost W₂ S₂ < M₂ + (F₂ - F₁) := by
  unfold lookaheadCost myopicCost
  constructor <;> intro h <;> linarith

/-- Myopic says node 2 (100 < 300); lookahead with a 500 ms KV transfer and
equal futures says node 1. -/
theorem affinity_example (F : ℝ) :
    myopicCost 100 0 < myopicCost 300 0 ∧
    lookaheadCost 300 0 0 F < lookaheadCost 100 0 500 F := by
  unfold myopicCost lookaheadCost
  constructor <;> norm_num

/-- KV-aware routing: A has a longer queue but a hit. -/
theorem kv_aware_example :
    myopicCost 300 100 < myopicCost 50 500 := by
  unfold myopicCost; norm_num

/-- **Affinity is not always optimal.**  Fix any migration cost `M ≥ 0` and
future benefit `F ≥ 0` of staying.  For an M/M/1 affinity node with service
rate `mu`, there is a stable load `lam < mu` such that waiting there costs
more than migrating to an idle node (wait `1/mu`) plus `M + F`. -/
theorem affinity_not_always_optimal {mu : ℝ} (hmu : 0 < mu) (M F : ℝ) :
    ∃ lam, 0 ≤ lam ∧ lam < mu ∧
      mm1Wait mu 0 + M + F < mm1Wait mu lam := by
  obtain ⟨lam, h0, hlt, hW⟩ := mm1Wait_unbounded hmu (mm1Wait mu 0 + M + F)
  exact ⟨lam, h0, hlt, hW⟩

/-! ### The inversion load: where affinity starts to lose

`prop:routing` (ii).  Moving to an idle node of the same speed costs
`1/mu + M + F`.  The affinity node's M/M/1 response time `1/(mu - lam)`
exceeds that exactly when `lam` is above the *inversion load*
`lam* = mu - 1/(1/mu + M + F)`, i.e. when its utilisation exceeds
`rho* = mu (M+F) / (1 + mu (M+F))`.  `lam*` is nondecreasing in `M` and
`F`, so a shared KV store, which replaces a recompute by a cheaper fetch,
lowers the load at which affinity loses. -/

/-- The arrival rate above which the affinity node's M/M/1 response time
exceeds the cost `1/mu + M + F` of moving to an idle node. -/
noncomputable def inversionLoad (mu M F : ℝ) : ℝ := mu - 1 / (1 / mu + M + F)

/-- Staying beats moving iff the load is below the inversion load. -/
theorem affinity_loses_iff {mu lam M F : ℝ} (hmu : 0 < mu) (hM : 0 ≤ M) (hF : 0 ≤ F)
    (hlam : lam < mu) :
    mm1Wait mu 0 + M + F < mm1Wait mu lam ↔ inversionLoad mu M F < lam := by
  unfold mm1Wait inversionLoad
  have hB : 0 < 1 / mu + M + F := by positivity
  have hd : 0 < mu - lam := by linarith
  rw [sub_zero, lt_div_iff₀ hd]
  constructor
  · intro h
    have h' : mu - lam < 1 / (1 / mu + M + F) := by
      rw [lt_div_iff₀ hB]
      linarith [mul_comm (mu - lam) (1 / mu + M + F)]
    linarith
  · intro h
    have h' : mu - lam < 1 / (1 / mu + M + F) := by linarith
    rw [lt_div_iff₀ hB] at h'
    linarith [mul_comm (mu - lam) (1 / mu + M + F)]

/-- The inversion load is a stable load: `0 ≤ lam* < mu`. -/
theorem inversionLoad_stable {mu M F : ℝ} (hmu : 0 < mu) (hM : 0 ≤ M) (hF : 0 ≤ F) :
    0 ≤ inversionLoad mu M F ∧ inversionLoad mu M F < mu := by
  unfold inversionLoad
  have hB : 0 < 1 / mu + M + F := by positivity
  have hmu' : 0 < 1 / mu := by positivity
  constructor
  · have h1 : 1 / (1 / mu + M + F) ≤ 1 / (1 / mu) :=
      one_div_le_one_div_of_le hmu' (by linarith)
    rw [one_div_one_div] at h1
    linarith
  · have := one_div_pos.mpr hB
    linarith

/-- A cheaper move (smaller `M` or `F`) lowers the inversion load. -/
theorem inversionLoad_mono {mu M M' F F' : ℝ} (hmu : 0 < mu) (hM : 0 ≤ M) (hF : 0 ≤ F)
    (hMM : M ≤ M') (hFF : F ≤ F') :
    inversionLoad mu M F ≤ inversionLoad mu M' F' := by
  unfold inversionLoad
  have hB : 0 < 1 / mu + M + F := by positivity
  have := one_div_le_one_div_of_le hB (by linarith : 1 / mu + M + F ≤ 1 / mu + M' + F')
  linarith

/-- As a utilisation: `rho* = mu (M+F) / (1 + mu (M+F))`. -/
theorem inversionLoad_utilization {mu M F : ℝ} (hmu : 0 < mu) (hM : 0 ≤ M) (hF : 0 ≤ F) :
    utilization mu (inversionLoad mu M F) = mu * (M + F) / (1 + mu * (M + F)) := by
  unfold utilization inversionLoad
  have hmu' : mu ≠ 0 := ne_of_gt hmu
  have hB : 1 / mu + M + F ≠ 0 := by positivity
  have hC : 1 + mu * (M + F) ≠ 0 := by positivity
  field_simp
  ring

/-- A move costing four service times loses to affinity below 80 % load;
one costing a quarter of a service time already wins above 20 %. -/
theorem inversionLoad_examples :
    utilization 10 (inversionLoad 10 0.4 0) = 0.8 ∧
    utilization 10 (inversionLoad 10 0.025 0) = 0.2 := by
  unfold utilization inversionLoad
  constructor <;> norm_num

/-! ### Append-prefill (PPD-style) routing for turn `t ≥ 2`. -/

/-- Cost of routing the new tokens to the prefill pool: prefill-pool wait,
append-prefill service, KV transfer, decode-pool wait. -/
def viaPrefillPool (WP SP TKV WD : ℝ) : ℝ := WP + SP + TKV + WD

/-- Cost of decode-local append-prefill: decode-pool wait, append service on
the decode node, plus induced interference on co-located decodes. -/
def decodeLocal (WD SD I : ℝ) : ℝ := WD + SD + I

/-- Decode-local wins iff the prefill-pool detour (its own queue, service,
and the KV transfer) exceeds the local append service plus interference. -/
theorem append_prefill_rule (WP SP TKV WD SD I : ℝ) :
    decodeLocal WD SD I < viaPrefillPool WP SP TKV WD ↔ SD + I < WP + SP + TKV := by
  unfold decodeLocal viaPrefillPool
  constructor <;> intro h <;> linarith

/-- Turn-2+ example: 100K cached prefix + 500 new tokens.  Append service is
cheap on either side (20 ms), the transfer of the 100K KV is 400 ms. -/
theorem append_prefill_example :
    decodeLocal 50 20 30 < viaPrefillPool 10 20 400 50 := by
  unfold decodeLocal viaPrefillPool; norm_num

end ServingQueueTheory
