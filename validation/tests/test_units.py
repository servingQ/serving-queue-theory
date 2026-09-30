"""Unit tests of the library pieces that do not run serQ."""

import math
import tomllib
from pathlib import Path

import pyserq
from pyserq import Rng

import fmt
from sim import laws, serq
from sim.stats import Welford, batch_means, quantile
from sim.workload import TraceCorpus, weka
from theory import eviction
from theory.dist import (
    Deterministic,
    Erlang,
    HitMiss,
    Uniform,
    discrete,
    exp,
    hyperexp_balanced,
)
from theory.eviction import Item, Weighted

# ---------------------------------------------------------------- rng ----


def test_pyserq_is_the_pinned_release():
    """pyserq (PyPI) and the serQ checkout (examples, oracle IR) are one
    version: the checkout's workspace version, and the tag when one is pinned."""
    pin = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    cargo = tomllib.loads((serq.SERQ_HOME / "src" / "Cargo.toml").read_text())
    version = cargo["workspace"]["package"]["version"]
    assert pyserq.__version__ == version
    assert f"pyserq=={version}" in pin["project"]["dependencies"]
    if "tag" in pin["tool"]["serq"]:
        assert pin["tool"]["serq"]["tag"] == f"v{version}"


def test_rng_is_rand_0_9_std_rng():
    # The draws the port of rand 0.9's StdRng made (theory/rng.py, removed
    # with serQ rc8): the offline eviction instances and the footprint
    # Monte Carlo depend on this stream.
    r = Rng(5)
    assert r.next_u64() == 6311119817046432122
    assert r.random_f64() == 0.006618081401074782
    assert (r.range_u64(1, 200), r.range_u32(4, 12)) == (91, 11)
    assert r.range_f64(0.1, 0.6) == 0.2257269152734617


# --------------------------------------------------------------- dist ----


def test_moments_are_exact():
    cases = [
        (Deterministic(3.0), 3.0, 9.0),
        (exp(2.0), 2.0, 8.0),
        (Erlang(4, 2.0), 2.0, 5.0),
        (hyperexp_balanced(1.0, 4.0), 1.0, 5.0),
        (Uniform(1.0, 3.0), 2.0, 13.0 / 3.0),
        (discrete([1.0, 3.0], [0.25, 0.75]), 2.5, 7.0),
        (HitMiss(0.8, 0.05, 0.5), 0.14, 0.052),
    ]
    for d, mean, m2 in cases:
        assert abs(d.mean() - mean) < 1e-12, d
        assert abs(d.second_moment() - m2) < 1e-12, d


def test_seeded_sampling_matches_moments():
    for d in [exp(2.0), Uniform(1.0, 3.0), discrete([100.0, 3700.0], [0.75, 0.25])]:
        rng = Rng(7)
        xs = [d.sample(rng) for _ in range(100_000)]
        assert abs(sum(xs) / len(xs) - d.mean()) < 0.03 * max(abs(d.mean()), 1.0)


def test_expr_of_discrete():
    assert laws.expr(discrete([1.0, 2.0, 3.0], [0.5, 0.25, 0.25])) == (
        "(~bernoulli(5e-1) ? 1e0 : (~bernoulli(5e-1) ? 2e0 : 3e0))"
    )


# ---------------------------------------------------------------- fmt ----


def test_rust_float_formatting():
    assert [fmt.fixed(x, d) for x, d in [(0.5, 0), (2.5, 0), (0.25, 1), (0.125, 2), (math.nan, 3)]] == [
        "0", "2", "0.2", "0.12", "NaN",
    ]  # fmt: skip
    assert [fmt.disp(x) for x in [1e15, 1e-7, 2.0, 0.0005, math.inf]] == [
        "1000000000000000", "0.0000001", "2", "0.0005", "inf",
    ]  # fmt: skip
    assert [fmt.sci(x) for x in [0.0005, 5e3, 1.5e-3, math.inf]] == ["5e-4", "5e3", "1.5e-3", "inf"]
    assert [fmt.sci_fixed(x, d) for x, d in [(4.0e6, 1), (5e3, 0), (2e7, 2), (12345.678, 4)]] == [
        "4.0e6", "5e3", "2.00e7", "1.2346e4",
    ]  # fmt: skip
    assert fmt.signed(-0.3, 0) == "-0"
    assert fmt.dbg(1.0) == "1.0" and fmt.dbg(1e-7) == "1e-7" and fmt.dbg(1e17) == "1e17"
    assert (
        fmt.rround(2.5) == 3.0
        and fmt.rround(-2.5) == -3.0
        and fmt.rround(0.49999999999999994) == 0.0
    )


# -------------------------------------------------------------- stats ----


def test_welford_matches_direct():
    w = Welford()
    for x in [1.0, 2.0, 4.0, 7.0]:
        w.push(x)
    assert abs(w.mean() - 3.5) < 1e-12
    assert abs(w.variance() - 5.25) < 1e-12
    assert abs(w.second_moment() - 17.5) < 1e-12
    assert Welford([1.0, 2.0, 4.0, 7.0]).variance() == w.variance()


def test_batch_means_of_constant_has_zero_width():
    e = batch_means([2.0] * 100, 10)
    assert e.mean == 2.0 and e.half_width == 0.0


def test_quantile_nearest_rank():
    xs = [5.0, 1.0, 3.0, 2.0, 4.0]
    assert quantile(xs, 0.5) == 3.0
    assert quantile(xs, 1.0) == 5.0
    assert quantile(xs, 0.0) == 1.0


# ----------------------------------------------------------- workload ----


def test_trace_parser_and_summaries(tmp_path):
    path = tmp_path / "trace.csv"
    path.write_text(
        "# c\nsession,turn,new,out,think,forced\n0,1,100,10,5,0\n0,2,20,10,0,1\n1,1,50,5,0,0\n"
    )
    c = TraceCorpus.load(path)
    assert len(c.sessions) == 2 and c.turns() == 3
    assert c.sessions[0][1] == (20.0, 10.0, 0.0, 1.0)
    assert abs(c.mean_turns() - 1.5) < 1e-12
    assert abs(c.mean_think() - 5.0) < 1e-12
    assert abs(c.resume_fraction() - 1.0 / 3.0) < 1e-12
    assert abs(c.mean_final_context() - 97.5) < 1e-12


def test_bundled_corpus_is_sane():
    c = weka()
    assert len(c.sessions) > 100 and c.mean_turns() > 5.0
    assert all(len(s) >= 2 for s in c.sessions)
    assert all(s[-1][2] == 0.0 for s in c.sessions)


# ----------------------------------------------------------- eviction ----


def _items(cs):
    return [Item.uniform(c) for c in cs]


def test_lean_definition_matches_greedy():
    assert eviction.shortest_first_lean([4, 5, 6], 6) == [4, 5]
    rng = Rng(0)
    for _ in range(2000):
        inst = eviction.random_instance(rng, 8, 30, eviction.UNIFORM)
        lean = eviction.shortest_first_lean(sorted(i.c for i in inst.items), inst.delta)
        ours = sorted(inst.items[i].c for i in eviction.shortest_first(inst.items, inst.delta))
        assert lean == ours


def _brute_force(items, delta):
    n, best = len(items), math.inf
    for mask in range(1 << n):
        s = [i for i in range(n) if mask >> i & 1]
        if eviction.weighted_freed(items, s) >= delta:
            best = min(best, eviction.weighted_cost(items, s))
    return best


def test_dp_matches_brute_force():
    rng = Rng(1)
    for resume in [eviction.UNIFORM, eviction.varied(0.05)]:
        for _ in range(200):
            inst = eviction.random_instance(rng, 10, 25, resume)
            w = [i.weighted() for i in inst.items]
            brute = _brute_force(w, inst.delta)
            opt, s = eviction.optimal(inst.items, inst.delta)
            assert abs(opt - brute) < 1e-9 * max(brute, 1.0)
            assert eviction.subset_freed(inst.items, s) >= inst.delta
            assert abs(eviction.subset_cost(inst.items, s) - opt) < 1e-9 * max(opt, 1.0)


def test_counterexample_of_prop_blind_i():
    it = _items([4, 5, 6])
    assert eviction.subset_cost(it, eviction.shortest_first(it, 6)) == 41.0
    opt, s = eviction.optimal(it, 6)
    assert opt == 36.0 and s == [2]


def test_guarded_is_two_approx_against_brute_force():
    rng = Rng(11)
    worst_plain = 0.0
    for _ in range(2000):
        n = rng.range_u32(1, 10)
        inst = eviction.random_weighted_instance(rng, n, 25)
        opt = _brute_force(inst.items, inst.delta)
        dp, _ = eviction.optimal_weighted(inst.items, inst.delta)
        assert abs(dp - opt) <= 1e-9 * max(opt, 1.0)
        g = eviction.guarded_density(inst.items, inst.delta)
        assert eviction.weighted_freed(inst.items, g) >= inst.delta
        assert eviction.weighted_cost(inst.items, g) <= 2.0 * opt * (1.0 + 1e-12)
        d = eviction.density_weighted(inst.items, inst.delta)
        worst_plain = max(worst_plain, fmt.div(eviction.weighted_cost(inst.items, d), opt))
    assert worst_plain > 2.0


def test_plain_density_has_no_constant_ratio():
    for k in [10, 100, 1000, 100_000]:
        it, delta = eviction.density_counterexample(k)
        assert eviction.weighted_cost(it, eviction.density_weighted(it, delta)) == float(k)
        assert eviction.optimal_weighted(it, delta)[0] == 2.0
        assert eviction.weighted_cost(it, eviction.guarded_density(it, delta)) == 2.0


def test_infeasible_is_none():
    it = [Weighted(1, 1.0), Weighted(2, 1.0)]
    assert eviction.guarded_density(it, 4) is None
    assert eviction.guarded_density(it, 0) == []
    assert eviction.optimal(_items([1, 2]), 4) is None
