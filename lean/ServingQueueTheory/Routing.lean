/-
# Program-aware routing: myopic vs. lookahead decisions, and the limit of
# affinity

Proposition (paper `prop:routing` and `prop:append`, §6).  For a program `p` and candidate node `j`:

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
