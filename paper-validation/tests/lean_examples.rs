//! The numeric instances proved in Lean, evaluated with `analytic`.
//! If a closed form was mistranscribed from Lean, one of these fails.
//! Test names are the Lean theorem names.

use paper_validation::Dist;
use paper_validation::analytic::*;
use paper_validation::models::eviction::{Item, evict_cost, shortest_first_lean};

fn close(a: f64, b: f64) -> bool {
    (a - b).abs() <= 1e-9 * b.abs().max(1.0)
}

#[test]
fn mm1_wait_examples() {
    // mm1Wait_example_9, _9_5, _9_9, _ratio
    assert!(close(mm1_wait(10.0, 9.0), 1.0));
    assert!(close(mm1_wait(10.0, 9.5), 2.0));
    assert!(close(mm1_wait(10.0, 9.9), 10.0));
    assert!(close(mm1_wait(10.0, 9.9), 10.0 * mm1_wait(10.0, 9.0)));
}

#[test]
fn mm1_wait_eq_rho_form() {
    for (mu, lam) in [(10.0, 3.0), (2.0, 1.5), (1.0, 0.99)] {
        let rho = utilization(mu, lam);
        assert!(close(mm1_wait(mu, lam), (1.0 / mu) / (1.0 - rho)));
    }
}

#[test]
fn workload_moments_and_wait_ratio() {
    // workloadA_mean, workloadB_mean, workloadA/B_secondMoment, workloadB_wait_ratio
    let a = Dist::discrete(vec![1000.0; 4], vec![0.25; 4]);
    let b = Dist::discrete(vec![100.0, 100.0, 100.0, 3700.0], vec![0.25; 4]);
    assert!(close(a.mean(), 1000.0) && close(b.mean(), 1000.0));
    assert!(close(a.second_moment(), 1.0e6));
    assert!(close(b.second_moment(), 3.43e6));
    for rho in [0.1, 0.5, 0.9] {
        let lam = rho / 1000.0;
        let r = pk_wait(lam, b.second_moment(), rho) / pk_wait(lam, a.second_moment(), rho);
        assert!(close(r, 3.43));
    }
}

#[test]
fn second_moment_eq_variance_add_sq() {
    let d = Dist::discrete(vec![1.0, 4.0, 9.0], vec![0.5, 0.3, 0.2]);
    assert!(close(d.second_moment(), d.variance() + d.mean().powi(2)));
}

#[test]
fn cache_reuse_examples() {
    // meanService_example, utilization_example_miss_only, utilization_example_hit80
    assert!(close(mean_service(0.8, 0.05, 0.5), 0.14));
    assert!(close(mixture_utilization(1.8, 0.0, 0.05, 0.5), 0.9));
    assert!(close(mixture_utilization(1.8, 0.8, 0.05, 0.5), 0.252));
}

#[test]
fn mixture_cv2_examples() {
    // mixtureCV2_agentic_example, mixtureCV2_cheap_miss_example
    assert!(mixture_cv2(0.96, 0.05, 5.0) > 15.0);
    assert!(mixture_cv2(0.96, 0.05, 0.1) < 0.05);
    let d = Dist::HitMiss {
        p_hit: 0.96,
        hit: 0.05,
        miss: 5.0,
    };
    assert!(close(d.cv2(), mixture_cv2(0.96, 0.05, 5.0)));
}

#[test]
fn pk_wait_ratio_to_exponential() {
    for (lam, mean, m2, rho) in [(0.5, 1.0, 3.0, 0.5), (2.0, 0.1, 0.05, 0.2)] {
        let r = pk_wait(lam, m2, rho) / pk_wait(lam, 2.0 * mean * mean, rho);
        assert!(close(r, (1.0 + (m2 / (mean * mean) - 1.0)) / 2.0));
    }
}

#[test]
fn pd_examples() {
    // pd_wins_example, pd_loses_example, pd_eq_agg_at_rate_match,
    // pdCompute_eq_agg_of_no_gain
    let agg = agg_capacity_i(32.0, 1.0, 1.0, 0.5);
    assert!(agg < pd_full_capacity(32.0, 1.0, 1.0, 2.0, 1.0, 1000.0, 1.0, 100.0, 100.0));
    assert!(agg >= pd_full_capacity(32.0, 1.0, 1.0, 2.0, 1.0, 10.0, 1.0, 100.0, 100.0));
    let (n, sp, sd) = (8.0, 1.0, 3.0);
    let np = n * sp / (sp + sd);
    assert!(close(
        pd_capacity(np, n - np, sp, sd),
        agg_capacity(n, sp, sd)
    ));
    assert!(close(
        pd_compute_capacity(n, sp, sd, 1.0, 1.0),
        agg_capacity_i(n, sp, sd, 0.0)
    ));
}

#[test]
fn routing_examples() {
    // affinity_example, kv_aware_example, append_prefill_example
    assert!(myopic_cost(100.0, 0.0) < myopic_cost(300.0, 0.0));
    assert!(lookahead_cost(300.0, 0.0, 0.0, 7.0) < lookahead_cost(100.0, 0.0, 500.0, 7.0));
    assert!(myopic_cost(300.0, 100.0) < myopic_cost(50.0, 500.0));
    assert!(decode_local(50.0, 20.0, 30.0) < via_prefill_pool(10.0, 20.0, 400.0, 50.0));
}

#[test]
fn eviction_examples() {
    // shortestFirst_example, shortestFirst_example_cost, single_six_cost,
    // shortestFirst_wrong_with_resume_prob
    assert_eq!(shortest_first_lean(&[4, 5, 6], 6), vec![4, 5]);
    assert_eq!(evict_cost(&shortest_first_lean(&[4, 5, 6], 6)), 41);
    assert_eq!(evict_cost(&[6]), 36);
    assert!(Item { c: 10, p: 0.01 }.cost() < Item { c: 2, p: 1.0 }.cost());
}

#[test]
fn ps_num_and_price() {
    // psNum_diff_exact: the change of psNum equals (C-ρ)/(C-ρ')·λ Σ q Φ.
    for (c, rho, lam, q, ds) in [(1.0, 0.6, 4.0, 0.05, 0.45), (2.0, 1.2, 3.0, 0.1, 0.5)] {
        let rho1 = rho + lam * q * ds;
        let lhs = ps_num(c, rho1) - ps_num(c, rho);
        let rhs = (c - rho) / (c - rho1) * lam * q * ps_price(c, rho, ds);
        assert!(close(lhs, rhs));
        // psPrice_lower
        assert!(lam * q * ps_price(c, rho, ds) <= lhs);
    }
    // stationaryMean with a(n) = 1 (φ ≡ 1) tends to psNum 1 ρ.
    let a = vec![1.0; 2000];
    assert!(close(stationary_mean(&a, 0.7), ps_num(1.0, 0.7)));
}

#[test]
fn footprint_exp_fit() {
    // expFit_six, expFit_five_seven, expFit_seven, expFit_two_twelve
    assert!(close(exp_fit(&[(6.0, 1.0)], 12.0), 2.0));
    assert!(close(exp_fit(&[(5.0, 0.5), (7.0, 0.5)], 12.0), 7.0 / 4.0));
    assert!(close(exp_fit(&[(7.0, 1.0)], 12.0), 1.0));
    assert!(close(
        exp_fit(&[(2.0, 0.5), (12.0, 0.5)], 12.0),
        95.0 / 64.0
    ));
}
