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
#print axioms price_blind_rule_unbounded_cost
#print axioms tailRecompute_marginal_antitone
#print axioms tailRecompute_subadditive
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
#print axioms prefillWork_miss_delta
#print axioms missPrice_mono_context
#print axioms price_order_flips_with_load
-- prop:finite (§2.4): the prefill queue with a finite population (M/M/1//N)
#print axioms mvaQ_mono
#print axioms mvaQ_anti_c
#print axioms mvaQ_le_card
#print axioms finite_source_rho_lt_one
#print axioms finite_source_wait_le_open
#print axioms closed_price_cap
#print axioms finite_source_two_sessions_example
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
#print axioms threshold_rule_optimal_byte_seconds
#print axioms density_prefix_plus_one
-- research/analytic-memory.md: miss feedback (not yet in the paper)
#print axioms feedback_map_monotone
#print axioms feedback_equilibrium_above
#print axioms feedback_equilibrium_exists
#print axioms feedback_comparative_statics
#print axioms forced_miss_equilibrium
#print axioms forced_miss_amplified
#print axioms feedback_extremal
#print axioms feedback_gfp_mono
#print axioms feedback_lfp_mono
#print axioms feedback_bistable
#print axioms unit_feedback_extremal
#print axioms unit_feedback_greatest_mono
#print axioms unit_feedback_bistable
#print axioms pkFeedback_monotoneOn
#print axioms pkFeedback_zero_of_overload
#print axioms pkFeedback_collapse
#print axioms feedback_map_monotone_two_channel
#print axioms pkFeedback_absorbing
-- metastability, lecture 7 (Metastability.lean; research/metastability.md)
#print axioms bd_detailed_balance
#print axioms bd_weight_le_iff
#print axioms bd_local_mode_iff
#print axioms passTime_top
#print axioms passTime_first_step
#print axioms passTime_unique
#print axioms passTime_congr
#print axioms recoveryTime_congr
#print axioms passTime_mono
#print axioms recoveryTime_mono
#print axioms passTime_ge_barrier
#print axioms recovery_ranking_flip
#print axioms openWeight_eq_bdWeight
#print axioms open_wait_loss_stable_iff_ratio_test
#print axioms open_wait_loss_stability
#print axioms open_stability_tail_only
#print axioms bdWeight_pos_of
#print axioms closed_fcfs_lru_rises_iff
#print axioms closed_fcfs_lru_no_congested_mode
#print axioms admission_hold_service_le
#print axioms admission_hold_recovery_le
#print axioms admission_hold_no_trough
-- serving: what LRU keeps under FCFS (CacheOrder.lean)
#print axioms fcfs_lru_open_stable_iff
#print axioms round_hits_le_capacity
#print axioms lru_round_robin_all_miss
#print axioms lruRun_round_robin
#print axioms pinCache_card
#print axioms pinCache_step
#print axioms pinned_round_hits
#print axioms lruRun_eq_take
#print axioms recency_split
#print axioms mattson_lru_hit_iff
-- serQ's own theorems (syntax, pool semantics, executable semantics, the vLLM
-- oracle) are audited in serQ (`make lean`, lean/scripts/AxiomAudit.lean there).
-- The ones the paper cites (§2.2) are audited here too:
#print axioms SerqLang.Serve.serve_preserves_shape
#print axioms SerqLang.Serve.serve_eq_decode_first
#print axioms SerqLang.Serve.chunk_cap_breaks_shape
-- the paper's replicas as serQ programs (Deployments.lean)
#print axioms Deployments.disaggregatedReplica_wf
#print axioms Deployments.colocatedReplica_wf
#print axioms Deployments.colocatedReplica'_eq
