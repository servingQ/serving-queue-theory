/-
# KV footprint and batch size: no fixed sign

Proposition (paper `prop:footprint`, §2.2).  A replica holds at most `M`
tokens of KV.  Requests with i.i.d. footprints are admitted in arrival
order until the first one that does not fit.  The expected number admitted
depends on the footprint distribution, not only on its mean, and a more
variable footprint can lower or raise it.

* `expFit d fuel M` : expected number admitted into free memory `M` when
  footprints are drawn from the finite distribution `d` (pairs
  `(tokens, probability)`, tokens `≥ 1`; `fuel ≥ M + 1` suffices).
* `footprint_variance_hurts` : `M = 12`; footprint `6` admits `2`, while
  `5` or `7` (mean 6) admits `7/4` on average.
* `footprint_variance_helps` : `M = 12`; footprint `7` admits `1`, while
  `2` or `12` (mean 7) admits `95/64` on average.
-/
import Mathlib.Tactic

namespace ServingQueueTheory

/-- Expected number of requests admitted, in arrival order, into `M` free
tokens until the first request that does not fit. -/
def expFit (d : List (ℕ × ℚ)) : ℕ → ℕ → ℚ
  | 0, _ => 0
  | fuel + 1, M => (d.map fun x => if x.1 ≤ M then x.2 * (1 + expFit d fuel (M - x.1)) else 0).sum

theorem expFit_six : expFit [(6, 1)] 13 12 = 2 := by decide +kernel
theorem expFit_five_seven : expFit [(5, 1/2), (7, 1/2)] 13 12 = 7 / 4 := by decide +kernel
theorem expFit_seven : expFit [(7, 1)] 13 12 = 1 := by decide +kernel
theorem expFit_two_twelve : expFit [(2, 1/2), (12, 1/2)] 13 12 = 95 / 64 := by decide +kernel

/-- **Prop. footprint (i).**  Equal mean footprint (6), more variance,
fewer requests admitted. -/
theorem footprint_variance_hurts :
    expFit [(5, 1/2), (7, 1/2)] 13 12 < expFit [(6, 1)] 13 12 := by
  rw [expFit_five_seven, expFit_six]; norm_num

/-- **Prop. footprint (ii).**  Equal mean footprint (7), more variance,
more requests admitted. -/
theorem footprint_variance_helps :
    expFit [(7, 1)] 13 12 < expFit [(2, 1/2), (12, 1/2)] 13 12 := by
  rw [expFit_seven, expFit_two_twelve]; norm_num

end ServingQueueTheory
