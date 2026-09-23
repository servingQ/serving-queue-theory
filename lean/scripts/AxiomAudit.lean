/-
Axiom audit.  Prints the axioms each paper-facing theorem depends on.
CI fails if anything other than the three standard axioms
(`propext`, `Classical.choice`, `Quot.sound`) appears — in particular
`sorryAx` (an unfinished proof) or any custom axiom.
-/
import ServingQueueTheory

open ServingQueueTheory

-- prop:mm1 (§3): M/M/1
#print axioms mm1Wait_eq_rho_form
#print axioms mm1Wait_strictMono
#print axioms mm1Wait_unbounded
#print axioms mm1Wait_example_ratio
-- prop:pk (§3): Pollaczek–Khinchine
#print axioms DiscreteService.secondMoment_eq_variance_add_sq
#print axioms pkWait_strictMono_secondMoment
#print axioms pkWait_lt_of_variance_lt
#print axioms workloadB_wait_ratio
-- prop:cache (§3): cache reuse
#print axioms meanService_antitone
#print axioms utilization_antitone
#print axioms secondMomentService_antitone
#print axioms pkWait_mixture_antitone
#print axioms utilization_example_hit80
#print axioms pkWait_ratio_to_exponential
#print axioms mixtureCV2_agentic_example
#print axioms mixtureCV2_cheap_miss_example
-- prop:option (§4.1): option value
#print axioms optimal_cost_antitone_in_actions
#print axioms enabling_offload_never_hurts
#print axioms always_offload_can_be_worse
-- prop:pd (§5): PD disaggregation
#print axioms pd_le_agg
#print axioms pd_eq_agg_at_rate_match
#print axioms rate_match_optimal
#print axioms pd_beats_agg_iff
#print axioms pdCompute_eq_agg_of_no_gain
#print axioms pd_wins_example
#print axioms pd_loses_example
-- prop:evict (§4.2): eviction
#print axioms shortestFirst_not_optimal
#print axioms shortestFirst_optimality_claim_false
#print axioms shortestFirst_wrong_with_resume_prob
#print axioms shortestFirst_feasible
#print axioms shortestFirst_two_approx
#print axioms shortestFirst_two_approx_tight
#print axioms shortestFirst_unbounded_with_resume_prob
-- prop:routing, prop:append (§6): routing
#print axioms lookahead_prefers_iff
#print axioms affinity_example
#print axioms affinity_not_always_optimal
#print axioms append_prefill_rule
#print axioms append_prefill_example
