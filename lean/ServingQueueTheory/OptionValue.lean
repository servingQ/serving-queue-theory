/-
# Option value: enabling a mechanism never hurts an optimal controller

Proposition (paper `prop:option`, §4.1).  Let `A₀ ⊆ A₁` be action sets (e.g.
`A₀ = {keep, recompute}`, `A₁ = A₀ ∪ {offload}`).  For any cost `J`,
`min_{a ∈ A₁} J a ≤ min_{a ∈ A₀} J a`.

Consequence: an experiment showing that *always offloading* is worse
than never offloading does not show that *enabling* offloading is
harmful; it shows the controller was not selecting.  We also exhibit the
gap between "always offload" and "optimal with offload enabled".
-/
import Mathlib.Data.Finset.Lattice.Fold
import Mathlib.Order.ConditionallyCompleteLattice.Basic
import Mathlib.Tactic

namespace ServingQueueTheory

open Finset

variable {α : Type*}

/-- Adding actions can only lower the optimal cost. -/
theorem optimal_cost_antitone_in_actions (A₀ A₁ : Finset α) (h₀ : A₀.Nonempty)
    (hsub : A₀ ⊆ A₁) (J : α → ℝ) :
    A₁.inf' (h₀.mono hsub) J ≤ A₀.inf' h₀ J := by
  apply Finset.le_inf'
  intro a ha
  exact Finset.inf'_le J (hsub ha)

/-- Three actions of the memory controller for a suspended program. -/
inductive MemAction
  | keep
  | recompute
  | offload
  deriving DecidableEq, Repr

open MemAction

/-- The baseline action set (no offloading) and the extended set. -/
def baseActions : Finset MemAction := {keep, recompute}
def extendedActions : Finset MemAction := {keep, recompute, offload}

theorem baseActions_subset : baseActions ⊆ extendedActions := by
  decide

theorem baseActions_nonempty : baseActions.Nonempty := ⟨keep, by decide⟩

/-- Enabling offloading never increases the optimal cost, for *any* cost
function `J` (including ones where offloading is very expensive). -/
theorem enabling_offload_never_hurts (J : MemAction → ℝ) :
    extendedActions.inf' (baseActions_nonempty.mono baseActions_subset) J
      ≤ baseActions.inf' baseActions_nonempty J :=
  optimal_cost_antitone_in_actions _ _ baseActions_nonempty baseActions_subset J

/-- "Always offload" is a *different policy* from "offload enabled": it can
be strictly worse than the baseline optimum, while the enabled optimum is
never worse.  Witness: `J keep = 1, J recompute = 5, J offload = 10`. -/
theorem always_offload_can_be_worse :
    ∃ J : MemAction → ℝ,
      baseActions.inf' baseActions_nonempty J < J offload ∧
      extendedActions.inf' (baseActions_nonempty.mono baseActions_subset) J
        ≤ baseActions.inf' baseActions_nonempty J := by
  refine ⟨fun a => match a with | keep => 1 | recompute => 5 | offload => 10, ?_, ?_⟩
  · have : baseActions.inf' baseActions_nonempty
        (fun a => match a with | keep => (1:ℝ) | recompute => 5 | offload => 10) ≤ 1 :=
      Finset.inf'_le _ (by decide : keep ∈ baseActions)
    calc _ ≤ (1:ℝ) := this
      _ < 10 := by norm_num
  · exact enabling_offload_never_hurts _

end ServingQueueTheory
