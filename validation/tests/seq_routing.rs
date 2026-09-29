//! Adapter coverage for `models::routing`, which delegates to seQ's
//! `programs/routing.seq`.

use seq::run_program;
use validation::Dist;
use validation::models::routing::{self, RoutePolicy, RoutingConfig};

#[test]
fn affinity_and_myopic_match_hand_written_model() {
    for (policy, pol) in [
        (0, RoutePolicy::Affinity),
        (3, RoutePolicy::Myopic),
        (4, RoutePolicy::Lookahead),
    ] {
        for rate in [0.6, 1.2] {
            let theirs = routing::simulate(&RoutingConfig::example(rate, pol));
            let ours = run_program(
                "routing",
                &[&format!("policy={policy}"), &format!("rate={rate}")],
                Some(1),
                None,
            );
            let (a, b) = (ours.observe("response").unwrap().mean, theirs.response.mean);
            let (ha, hb) = (ours.observe("hitrate").unwrap().mean, theirs.hit_rate);
            eprintln!(
                "policy {policy} rate {rate}: response {a:.3} vs {b:.3}, hit {ha:.3} vs {hb:.3}"
            );
            assert!(
                (a - b).abs() / b < 0.12,
                "policy {policy} rate {rate}: {a} vs {b}"
            );
            assert!(
                (ha - hb).abs() < 0.05,
                "policy {policy} rate {rate}: hit {ha} vs {hb}"
            );
        }
    }
}

/// `affinity_breaks_at_high_load`: affinity's response rises with load and
/// at 1.8/s is far above lookahead's.
#[test]
fn affinity_breaks_at_high_load() {
    let aff: Vec<f64> = [0.6, 1.2, 1.6, 1.8]
        .iter()
        .map(|r| {
            run_program(
                "routing",
                &["policy=0", &format!("rate={r}")],
                Some(2),
                None,
            )
            .observe("response")
            .unwrap()
            .mean
        })
        .collect();
    let look = run_program("routing", &["policy=4", "rate=1.8"], Some(2), None)
        .observe("response")
        .unwrap()
        .mean;
    assert!(aff.windows(2).all(|w| w[1] > w[0]), "{aff:?}");
    assert!(aff[3] > 10.0 * look, "{aff:?} vs lookahead {look}");
}

#[test]
fn routing_adapter_renders_distribution_samples_in_seq() {
    let mut cfg = RoutingConfig::example(0.6, RoutePolicy::Lookahead);
    cfg.class.initial_tokens = Dist::discrete(vec![5_000.0, 15_000.0], vec![0.25, 0.75]);
    cfg.class.new_tokens = Dist::HitMiss {
        p_hit: 0.8,
        hit: 100.0,
        miss: 1_000.0,
    };
    cfg.class.output_tokens = Dist::Bernoulli { p: 0.5 };
    cfg.class.tool_time = Dist::HyperExp {
        p: 0.25,
        mean1: 0.5,
        mean2: 4.5,
    };
    let r = routing::simulate(&cfg);
    assert_eq!(r.utilization.len(), cfg.replicas);
    assert!(r.turns > 0);
    assert!(r.response.mean.is_finite());
    assert!(r.service.mean().is_finite());
    assert!(r.mean_context > 0.0);
}
