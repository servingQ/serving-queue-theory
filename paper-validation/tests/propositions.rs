//! One test per validation check (see `src/validation.rs`). A failure
//! prints the claim, the prediction and what was observed.

use paper_validation::validation::{self, Check};

fn assert_pass(c: Check) {
    assert!(
        c.pass,
        "\n{} ({}) FAILED\n  claim:    {}\n  expected: {}\n  observed: {}\n",
        c.id, c.paper, c.claim, c.expected, c.observed
    );
}

macro_rules! checks {
    ($($name:ident),* $(,)?) => {
        $(#[test] fn $name() { assert_pass(validation::$name()); })*

        /// Guard against adding a check to `all()` without a test here.
        #[test]
        fn every_check_has_a_test() {
            let tested = [$(stringify!($name)),*];
            for c in validation::all() {
                assert!(tested.contains(&c.id), "no test for check {}", c.id);
            }
        }
    };
}

checks!(
    mm1_response_time,
    mm1_blowup,
    pk_formula,
    variance_orders_delay,
    cache_reuse_lowers_delay,
    cv2_ratio,
    miss_price_bracket,
    prefill_pays_the_miss,
    ps_insensitivity,
    bcmp_feedback,
    ps_price_bracket,
    footprint_batch_size,
    lps_vs_saturating_phi,
    kingman_bursty_arrivals,
    little_law,
    closed_throughput_falls_with_concurrency,
    closed_throughput_nondecreasing_fixed_demand,
    interactive_response_time_law,
    always_offload_can_be_worse,
    selective_offload_never_worse,
    shortest_first_counterexample,
    shortest_first_two_approx,
    shortest_first_tightness,
    shortest_first_unbounded_with_resume_prob,
    guarded_density_two_approx,
    memory_threshold_rule,
    pd_capacity_matches,
    pd_no_gain,
    pd_win_condition_decisions,
    affinity_breaks_at_high_load,
    lookahead_not_worse_than_affinity,
    trace_replay_variance_sources,
    inversion_load_closed_form,
    inversion_load_rises_with_move_cost,
    finite_source_wait_below_open,
);
