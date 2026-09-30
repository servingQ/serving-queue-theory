"""Closed forms, one function per Lean definition.

Each function carries the name of its Lean counterpart so a reader can check
the correspondence. `tests/test_lean_examples.py` evaluates them at the
numeric instances proved in Lean, so a transcription error here fails CI.
"""

from __future__ import annotations

import math

from fmt import ssum


def mm1_wait(mu: float, lam: float) -> float:
    """`mm1Wait mu lam = 1/(mu - lam)`: M/M/1 mean response time (MM1.lean)."""
    return 1.0 / (mu - lam)


def utilization(mu: float, lam: float) -> float:
    """`utilization mu lam = lam/mu` (MM1.lean)."""
    return lam / mu


def pk_wait(lam: float, m2: float, rho: float) -> float:
    """`pkWait lam m2 rho = lam m2 / (2(1-rho))` (PollaczekKhinchine.lean)."""
    return lam * m2 / (2.0 * (1.0 - rho))


def mean_service(p: float, s_hit: float, s_miss: float) -> float:
    """`meanService p sHit sMiss` (CacheReuse.lean)."""
    return p * s_hit + (1.0 - p) * s_miss


def second_moment_service(p: float, s_hit: float, s_miss: float) -> float:
    """`secondMomentService p sHit sMiss` (CacheReuse.lean)."""
    return p * s_hit * s_hit + (1.0 - p) * s_miss * s_miss


def mixture_utilization(lam: float, p: float, s_hit: float, s_miss: float) -> float:
    """`mixtureUtilization lam p sHit sMiss = lam * meanService` (CacheReuse.lean)."""
    return lam * mean_service(p, s_hit, s_miss)


def mixture_wait(lam: float, p: float, s_hit: float, s_miss: float) -> float:
    """`mixtureWait`: PK wait of the hit/miss mixture (CacheReuse.lean)."""
    return pk_wait(
        lam,
        second_moment_service(p, s_hit, s_miss),
        mixture_utilization(lam, p, s_hit, s_miss),
    )


def mixture_cv2(p: float, s_hit: float, s_miss: float) -> float:
    """`mixtureCV2` (CacheReuse.lean)."""
    m = mean_service(p, s_hit, s_miss)
    return second_moment_service(p, s_hit, s_miss) / (m * m) - 1.0


def num_in_system(lam: float, m2: float, rho: float) -> float:
    """`numInSystem lam m2 rho = lam·pkWait + rho`: M/G/1 mean number in the
    system (MissPrice.lean)."""
    return lam * pk_wait(lam, m2, rho) + rho


def miss_price(lam: float, m2: float, rho: float, s_h: float, s_m: float) -> float:
    """`missPrice lam m2 rho sh sm`: the price of one miss (paper Prop. price,
    MissPrice.lean): `ΔS + λ(sm²-sh²)/(2(1-ρ)) + λ·W·ΔS/(1-ρ)`, `W` the PK wait."""
    return miss_price_given_wait(lam, pk_wait(lam, m2, rho), rho, s_h, s_m)


def miss_price_given_wait(lam: float, w: float, rho: float, s_h: float, s_m: float) -> float:
    """`miss_price` with the mean wait `w` supplied directly."""
    ds = s_m - s_h
    return ds + lam * (s_m * s_m - s_h * s_h) / (2.0 * (1.0 - rho)) + lam * w * ds / (1.0 - rho)


def kingman_bound(lam: float, var_a: float, var_s: float, rho: float) -> float:
    """Kingman's GI/G/1 upper bound on the mean wait (paper §2, cited; not
    formalised in Lean)."""
    return lam * (var_a + var_s) / (2.0 * (1.0 - rho))


def irtl_response(n: float, throughput: float, think: float) -> float:
    """Interactive response-time law `R = N/X - Z` (paper §2, cited)."""
    return n / throughput - think


def agg_capacity(n: float, s_p: float, s_d: float) -> float:
    """`aggCapacity N sP sD = N/(sP+sD)` (PDDisaggregation.lean)."""
    return n / (s_p + s_d)


def pd_capacity(n_p: float, n_d: float, s_p: float, s_d: float) -> float:
    """`pdCapacity NP ND sP sD = min(NP/sP, ND/sD)` (PDDisaggregation.lean)."""
    return min(n_p / s_p, n_d / s_d)


def agg_capacity_i(n: float, s_p: float, s_d: float, i: float) -> float:
    """`aggCapacityI N sP sD I = N/(sP+sD+I)` (PDDisaggregation.lean)."""
    return n / (s_p + s_d + i)


def pd_compute_capacity(n: float, s_p: float, s_d: float, g_p: float, g_d: float) -> float:
    """`pdComputeCapacity N sP sD gP gD = N/(sP/gP + sD/gD)` (PDDisaggregation.lean)."""
    return n / (s_p / g_p + s_d / g_d)


def pd_full_capacity(n, s_p, s_d, g_p, g_d, b_net, e_k, mu_p_mem, mu_d_mem) -> float:
    """`pdFullCapacity`: min of compute, `Bnet/EK` and the two memory caps
    (PDDisaggregation.lean)."""
    return min(
        min(pd_compute_capacity(n, s_p, s_d, g_p, g_d), b_net / e_k), min(mu_p_mem, mu_d_mem)
    )


def myopic_cost(w: float, s: float) -> float:
    """`myopicCost W S = W + S` (Routing.lean)."""
    return w + s


def lookahead_cost(w: float, s: float, m: float, f: float) -> float:
    """`lookaheadCost W S M F = W + S + M + F` (Routing.lean)."""
    return w + s + m + f


def via_prefill_pool(w_p: float, s_p: float, t_kv: float, w_d: float) -> float:
    """`viaPrefillPool WP SP TKV WD` (Routing.lean)."""
    return w_p + s_p + t_kv + w_d


def decode_local(w_d: float, s_d: float, i: float) -> float:
    """`decodeLocal WD SD I` (Routing.lean)."""
    return w_d + s_d + i


def ps_num(c: float, rho: float) -> float:
    """`psNum C ρ = ρ/(C-ρ)` (BatchServer.lean)."""
    return rho / (c - rho)


def ps_price(c: float, rho: float, ds: float) -> float:
    """`psPrice C ρ dS = C·dS/(C-ρ)²` (paper Prop. decode, BatchServer.lean)."""
    return c * ds / ((c - rho) * (c - rho))


def stationary_mean(a, rho: float) -> float:
    """`stationaryMean a N ρ`: mean of `π(n) ∝ a(n)ρⁿ` on `{0, …, N}`
    (BatchServer.lean)."""
    num, den, pw = 0.0, 0.0, 1.0
    for n, an in enumerate(a):
        num += n * an * pw
        den += an * pw
        pw *= rho
    return num / den


def exp_fit(d, m: float) -> float:
    """`expFit d fuel M`: expected number of requests admitted, in arrival
    order, into `M` free tokens until the first that does not fit,
    footprints i.i.d. from `d = [(tokens, prob)]` (Footprint.lean)."""
    assert all(x[0] > 0.0 for x in d)
    return ssum([x[1] * (1.0 + exp_fit(d, m - x[0])) for x in d if x[0] <= m])


def finite_source_mm1(n: int, nu: float, mu: float) -> tuple[float, float, float]:
    """M/M/1//N (Kleinrock 1975, §3.8): `(L, X, W_q)`."""
    r = nu / mu
    w, z, l = 1.0, 1.0, 0.0
    for k in range(1, n + 1):
        w *= (n - k + 1) * r
        z += w
        l += k * w
    l = l / z
    p0 = 1.0 / z
    x = mu * (1.0 - p0)
    return l, x, l / x - 1.0 / mu


def finite_source_nu_for_utilization(n: int, mu: float, rho: float) -> float:
    """Think rate at which the M/M/1//N server has utilisation `rho`."""
    lo, hi = 1e-9, 1e6
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        _, x, _ = finite_source_mm1(n, mid, mu)
        if x / mu < rho:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


def mva_q(c: float, n: int) -> float:
    """Mean number at the server of M/M/1//`n` by mean value analysis,
    `c = Z / E[S]` (the Lean `mvaQ`)."""
    q = 0.0
    for k in range(n):
        q = (k + 1.0) * (1.0 + q) / (c + 1.0 + q)
    return q


def finite_source_price(n: int, z: float, s0: float, s1: float) -> float:
    """Exact finite-source price of longer work (Lean `mvaQ_anti_c` gives its sign)."""
    return mva_q(z / s1, n) - mva_q(z / s0, n)
