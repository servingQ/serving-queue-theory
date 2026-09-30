"""The numeric instances proved in Lean, evaluated with `theory.analytic`. If a
closed form was mistranscribed from Lean, one of these fails. Test names
follow the Lean theorem names."""

from theory.analytic import (
    agg_capacity,
    agg_capacity_i,
    decode_local,
    exp_fit,
    lookahead_cost,
    mean_service,
    mixture_cv2,
    mixture_utilization,
    mm1_wait,
    myopic_cost,
    pd_capacity,
    pd_compute_capacity,
    pd_full_capacity,
    pk_wait,
    ps_num,
    ps_price,
    stationary_mean,
    utilization,
    via_prefill_pool,
)
from theory.dist import HitMiss, discrete
from theory.eviction import Item, evict_cost, shortest_first_lean


def close(a, b):
    return abs(a - b) <= 1e-9 * max(abs(b), 1.0)


def test_mm1_wait_examples():
    # mm1Wait_example_9, _9_5, _9_9, _ratio
    assert close(mm1_wait(10.0, 9.0), 1.0)
    assert close(mm1_wait(10.0, 9.5), 2.0)
    assert close(mm1_wait(10.0, 9.9), 10.0)
    assert close(mm1_wait(10.0, 9.9), 10.0 * mm1_wait(10.0, 9.0))


def test_mm1_wait_eq_rho_form():
    for mu, lam in [(10.0, 3.0), (2.0, 1.5), (1.0, 0.99)]:
        rho = utilization(mu, lam)
        assert close(mm1_wait(mu, lam), (1.0 / mu) / (1.0 - rho))


def test_workload_moments_and_wait_ratio():
    # workloadA_mean, workloadB_mean, workloadA/B_secondMoment, workloadB_wait_ratio
    a = discrete([1000.0] * 4, [0.25] * 4)
    b = discrete([100.0, 100.0, 100.0, 3700.0], [0.25] * 4)
    assert close(a.mean(), 1000.0) and close(b.mean(), 1000.0)
    assert close(a.second_moment(), 1.0e6)
    assert close(b.second_moment(), 3.43e6)
    for rho in [0.1, 0.5, 0.9]:
        lam = rho / 1000.0
        r = pk_wait(lam, b.second_moment(), rho) / pk_wait(lam, a.second_moment(), rho)
        assert close(r, 3.43)


def test_second_moment_eq_variance_add_sq():
    d = discrete([1.0, 4.0, 9.0], [0.5, 0.3, 0.2])
    assert close(d.second_moment(), d.variance() + d.mean() ** 2)


def test_cache_reuse_examples():
    # meanService_example, utilization_example_miss_only, utilization_example_hit80
    assert close(mean_service(0.8, 0.05, 0.5), 0.14)
    assert close(mixture_utilization(1.8, 0.0, 0.05, 0.5), 0.9)
    assert close(mixture_utilization(1.8, 0.8, 0.05, 0.5), 0.252)


def test_mixture_cv2_examples():
    # mixtureCV2_agentic_example, mixtureCV2_cheap_miss_example
    assert mixture_cv2(0.96, 0.05, 5.0) > 15.0
    assert mixture_cv2(0.96, 0.05, 0.1) < 0.05
    assert close(HitMiss(0.96, 0.05, 5.0).cv2(), mixture_cv2(0.96, 0.05, 5.0))


def test_pk_wait_ratio_to_exponential():
    for lam, mean, m2, rho in [(0.5, 1.0, 3.0, 0.5), (2.0, 0.1, 0.05, 0.2)]:
        r = pk_wait(lam, m2, rho) / pk_wait(lam, 2.0 * mean * mean, rho)
        assert close(r, (1.0 + (m2 / (mean * mean) - 1.0)) / 2.0)


def test_pd_examples():
    # pd_wins_example, pd_loses_example, pd_eq_agg_at_rate_match, pdCompute_eq_agg_of_no_gain
    agg = agg_capacity_i(32.0, 1.0, 1.0, 0.5)
    assert agg < pd_full_capacity(32.0, 1.0, 1.0, 2.0, 1.0, 1000.0, 1.0, 100.0, 100.0)
    assert agg >= pd_full_capacity(32.0, 1.0, 1.0, 2.0, 1.0, 10.0, 1.0, 100.0, 100.0)
    n, sp, sd = 8.0, 1.0, 3.0
    np_ = n * sp / (sp + sd)
    assert close(pd_capacity(np_, n - np_, sp, sd), agg_capacity(n, sp, sd))
    assert close(pd_compute_capacity(n, sp, sd, 1.0, 1.0), agg_capacity_i(n, sp, sd, 0.0))


def test_routing_examples():
    # affinity_example, kv_aware_example, append_prefill_example
    assert myopic_cost(100.0, 0.0) < myopic_cost(300.0, 0.0)
    assert lookahead_cost(300.0, 0.0, 0.0, 7.0) < lookahead_cost(100.0, 0.0, 500.0, 7.0)
    assert myopic_cost(300.0, 100.0) < myopic_cost(50.0, 500.0)
    assert decode_local(50.0, 20.0, 30.0) < via_prefill_pool(10.0, 20.0, 400.0, 50.0)


def test_eviction_examples():
    # shortestFirst_example, shortestFirst_example_cost, single_six_cost,
    # shortestFirst_wrong_with_resume_prob
    assert shortest_first_lean([4, 5, 6], 6) == [4, 5]
    assert evict_cost(shortest_first_lean([4, 5, 6], 6)) == 41
    assert evict_cost([6]) == 36
    assert Item(10, 0.01).cost() < Item(2, 1.0).cost()


def test_ps_num_and_price():
    # psNum_diff_exact: the change of psNum equals (C-ρ)/(C-ρ')·λ Σ q Φ; psPrice_lower
    for c, rho, lam, q, ds in [(1.0, 0.6, 4.0, 0.05, 0.45), (2.0, 1.2, 3.0, 0.1, 0.5)]:
        rho1 = rho + lam * q * ds
        lhs = ps_num(c, rho1) - ps_num(c, rho)
        rhs = (c - rho) / (c - rho1) * lam * q * ps_price(c, rho, ds)
        assert close(lhs, rhs)
        assert lam * q * ps_price(c, rho, ds) <= lhs
    # stationaryMean with a(n) = 1 (φ ≡ 1) tends to psNum 1 ρ.
    assert close(stationary_mean([1.0] * 2000, 0.7), ps_num(1.0, 0.7))


def test_footprint_exp_fit():
    # expFit_six, expFit_five_seven, expFit_seven, expFit_two_twelve
    assert close(exp_fit([(6.0, 1.0)], 12.0), 2.0)
    assert close(exp_fit([(5.0, 0.5), (7.0, 0.5)], 12.0), 7.0 / 4.0)
    assert close(exp_fit([(7.0, 1.0)], 12.0), 1.0)
    assert close(exp_fit([(2.0, 0.5), (12.0, 0.5)], 12.0), 95.0 / 64.0)
