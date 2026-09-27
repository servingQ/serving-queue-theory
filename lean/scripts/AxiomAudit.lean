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
-- docs/analytic-memory.md: miss feedback (not yet in the paper)
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
-- ROUTE (docs/route-language.md): the deployment language and its pool semantics
#print axioms RouteLang.Step.invariant
#print axioms RouteLang.Step.nonneg
#print axioms RouteLang.total_evictUntil_le
#print axioms RouteLang.sharedRate_sum
#print axioms RouteLang.serialRate_sum
#print axioms RouteLang.disaggregatedReplica_wf
#print axioms RouteLang.colocatedReplica_wf
#print axioms RouteLang.colocatedReplica'_eq
#print axioms RouteLang.admit_guard_units_only

-- ROUTE executable semantics: the vLLM scheduler scenarios (RouteOracle.lean, generated)
#print axioms RouteLang.Exec.makeRoom_used
#print axioms RouteLang.Exec.makeRoom_room
#print axioms RouteLang.Exec.evictOne_lt
#print axioms RouteLang.Oracle.vllmRequest_wf
#print axioms RouteLang.Oracle.vllm_chunked
#print axioms RouteLang.Oracle.vllm_hol
#print axioms RouteLang.Oracle.vllm_longchunk
#print axioms RouteLang.Oracle.vllm_mixed
#print axioms RouteLang.Oracle.vllm_preempt
#print axioms RouteLang.Oracle.vllm_seqcap
#print axioms RouteLang.Oracle.vllm_cache_trace
-- ROUTE: serving order of a step engine (admission order is decode-first without a chunk cap)
#print axioms RouteLang.Serve.serve_preserves_shape
#print axioms RouteLang.Serve.serve_eq_decode_first
#print axioms RouteLang.Serve.shape_append_prefill
#print axioms RouteLang.Serve.chunk_cap_breaks_shape
