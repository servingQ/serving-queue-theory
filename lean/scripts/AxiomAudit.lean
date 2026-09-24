/-
Axiom audit.  Prints the axioms each paper-facing theorem depends on.
CI fails if anything other than the three standard axioms
(`propext`, `Classical.choice`, `Quot.sound`) appears — in particular
`sorryAx` (an unfinished proof) or any custom axiom.
-/
import ServingQueueTheory

open ServingQueueTheory

-- prop:mm1 (§1, §3.3): M/M/1
#print axioms mm1Wait_eq_rho_form
#print axioms mm1Wait_strictMono
#print axioms mm1Wait_unbounded
#print axioms mm1Wait_example_ratio
-- prop:pk (§2.2): Pollaczek–Khinchine
#print axioms DiscreteService.secondMoment_eq_variance_add_sq
#print axioms pkWait_strictMono_secondMoment
#print axioms pkWait_lt_of_variance_lt
#print axioms workloadB_wait_ratio
-- prop:cache (§2.2): cache reuse
#print axioms meanService_antitone
#print axioms utilization_antitone
#print axioms secondMomentService_antitone
#print axioms pkWait_mixture_antitone
#print axioms utilization_example_hit80
#print axioms pkWait_ratio_to_exponential
#print axioms mixtureCV2_agentic_example
#print axioms mixtureCV2_cheap_miss_example
-- prop:option (§3.2): option value
#print axioms optimal_cost_antitone_in_actions
#print axioms enabling_offload_never_hurts
#print axioms always_offload_can_be_worse
-- prop:pd (App. B): PD disaggregation
#print axioms pd_le_agg
#print axioms pd_eq_agg_at_rate_match
#print axioms rate_match_optimal
#print axioms pd_beats_agg_iff
#print axioms pdCompute_eq_agg_of_no_gain
#print axioms pd_wins_example
#print axioms pd_loses_example
-- prop:blind (§3.1): eviction; price-blind keys and shortest-first
#print axioms shortestFirst_not_optimal
#print axioms shortestFirst_optimality_claim_false
#print axioms shortestFirst_wrong_with_resume_prob
#print axioms shortestFirst_feasible
#print axioms shortestFirst_two_approx
#print axioms shortestFirst_two_approx_tight
#print axioms shortestFirst_unbounded_with_resume_prob
#print axioms price_blind_rule_unbounded
-- prop:routing, prop:append (§3.3, App. B): routing
#print axioms lookahead_prefers_iff
#print axioms affinity_example
#print axioms affinity_not_always_optimal
#print axioms affinity_loses_iff
#print axioms inversionLoad_stable
#print axioms inversionLoad_mono
#print axioms inversionLoad_utilization
#print axioms inversionLoad_examples
#print axioms append_prefill_rule
#print axioms append_prefill_example
-- prop:price (§2.5): the price of a miss at the prefill queue
#print axioms missPrice_aggregate_exact
#print axioms missPrice_lower
#print axioms missPrice_upper
#print axioms missPrice_own_vs_queue_ratio
#print axioms missPrice_queue_terms_ratio
#print axioms missPrice_unbounded
-- prop:guarded (§3.1): guarded density greedy
#print axioms densityFirst_unbounded
#print axioms threshold_prefix_le
#print axioms guardedGreedy_two_approx
-- prop:decode (§2.5): the decode stage as a bandwidth PS
#print axioms stationaryMean_mono
#print axioms ps_eviction_rank_by_work
#print axioms psNum_diff_exact
#print axioms psPrice_lower
#print axioms psPrice_upper
#print axioms psPrice_unbounded
-- prop:footprint (§2.2): KV footprint and batch size
#print axioms footprint_variance_hurts
#print axioms footprint_variance_helps
-- prop:memory (§3.1): memory shadow price and block-level eviction
#print axioms threshold_rule_optimal
#print axioms density_prefix_plus_one
