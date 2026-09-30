/-
# The paper's replicas as serQ programs

The two deployments of the paper written in serQ (`Serq.lean`): the
disaggregated replica of the lecture (Lecture 1, Example L1:ex:program)
and the colocated two-resource replica of §2.2, both checked well formed;
the colocated one also in serQ's surface syntax, equal to the constructor
form by `rfl`.

Attribute slots: `0 = K` (prefix tokens), `1 = n` (new tokens), `2 = o`
(output tokens), `3 = Z` (tool time), `4 = cached` (the prefix found at
admission).

Key theorems: `disaggregatedReplica_wf`, `colocatedReplica_wf`,
`colocatedReplica'_eq`.
-/
import ServingQueueTheory.Serq

namespace ServingQueueTheory
namespace Deployments

open SerqLang

/-- Prefill cost `P(n, K) = a n + b n (K + n/2)` of Definition L1:def:costs. -/
noncomputable def prefillCost (a b n K : ℝ) : ℝ := a * n + b * n * (K + n / 2)

/-- The prefill work of a turn given the prefix found at admission: the new
tokens on the cached prefix, plus the missing prefix recomputed
(Eq. L1:eq:work with the hit indicator `cached ≥ K`). -/
noncomputable def prefillWork (a b : ℝ) (x : Attr) : ℝ :=
  if x 4 ≥ x 0 then prefillCost a b (x 1) (x 0)
  else prefillCost a b (x 0 + x 1) 0

/-- The disaggregated replica of Example L1:ex:program: pools `0 = mem_P`,
`1 = mem_D`; stages `0 = prefill`, `1 = link`, `2 = decode`, `3 = tool`.
Memory is `κ T` for a context of `T = K + n` tokens, the link takes
`x₀ + κ T / B` seconds, decode `o` tokens; the session continues with
probability `p`. -/
noncomputable def disaggregatedReplica (a b κ x₀ B p : ℝ) : Route Attr ℝ :=
  .turn <| .loop <|
    hold1 0 (fun x => κ * (x 0 + x 1))
      (run1 0 (prefillWork a b) <| run1 1 (fun x => x₀ + κ * (x 0 + x 1) / B) .done)
      (fun x => κ * (x 0 + x 1)) <|
    hold1 1 (fun x => κ * (x 0 + x 1)) (run1 2 (fun x => x 2) .done) (fun _ => 0) <|
    .branch (fun _ => p) (run1 3 (fun x => x 3) (.turn .done)) .stop .done

/-- The colocated two-resource replica of the paper (§2.2): one pool
`0 = kv` and one engine `0 = engine` that prefills and decodes in the same
iterations (the prefill in the compute the decode step leaves), plus the
tool `1`. The hold covers the whole turn, prefill and decode, and the
context stays cached afterwards. -/
noncomputable def colocatedReplica (a b p : ℝ) : Route Attr ℝ :=
  .turn <| .loop <|
    hold1 0 (fun x => x 0 + x 1 + x 2)
      (.run 0 .prefill (prefillWork a b) none <| .run 0 .decode (fun x => x 2) none .done)
      (fun x => x 0 + x 1 + x 2) <|
    .branch (fun _ => p) (run1 1 (fun x => x 3) (.turn .done)) .stop .done

theorem disaggregatedReplica_wf (a b κ x₀ B p : ℝ) :
    (disaggregatedReplica a b κ x₀ B p).wf = true := by
  rfl

theorem colocatedReplica_wf (a b p : ℝ) : (colocatedReplica a b p).wf = true := by
  rfl

/-- The colocated replica written in the surface syntax (compare
`colocatedReplica`): pool 0 = kv, stage 0 = engine, stage 1 = tool. -/
noncomputable def colocatedReplica' (a b p : ℝ) : Route Attr ℝ :=
  [route|
    turn;
    loop {
      hold 0 (x 0 + x 1 + x 2) {
        run 0 prefill (prefillWork a b x);
        run 0 decode (x 2);
        done
      } cache (x 0 + x 1 + x 2);
      branch (p) { run 1 (x 3); turn; done } else { stop };
      done
    }]

/-- The surface form and the constructor form are the same term. -/
theorem colocatedReplica'_eq (a b p : ℝ) : colocatedReplica' a b p = colocatedReplica a b p := by
  rfl


end Deployments
end ServingQueueTheory
