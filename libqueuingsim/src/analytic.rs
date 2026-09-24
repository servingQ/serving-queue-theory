//! Closed forms, one function per Lean definition.
//!
//! Each function carries the name of its Lean counterpart so a reader can
//! check the correspondence. `tests/lean_examples.rs` evaluates them at the
//! numeric instances proved in Lean, so a transcription error here fails CI.

/// `mm1Wait mu lam = 1/(mu - lam)`: M/M/1 mean response time (MM1.lean).
pub fn mm1_wait(mu: f64, lam: f64) -> f64 {
    1.0 / (mu - lam)
}

/// `utilization mu lam = lam/mu` (MM1.lean).
pub fn utilization(mu: f64, lam: f64) -> f64 {
    lam / mu
}

/// `pkWait lam m2 rho = lam m2 / (2(1-rho))`: M/G/1 mean wait in queue
/// (PollaczekKhinchine.lean).
pub fn pk_wait(lam: f64, m2: f64, rho: f64) -> f64 {
    lam * m2 / (2.0 * (1.0 - rho))
}

/// `meanService p sHit sMiss` (CacheReuse.lean).
pub fn mean_service(p: f64, s_hit: f64, s_miss: f64) -> f64 {
    p * s_hit + (1.0 - p) * s_miss
}

/// `secondMomentService p sHit sMiss` (CacheReuse.lean).
pub fn second_moment_service(p: f64, s_hit: f64, s_miss: f64) -> f64 {
    p * s_hit * s_hit + (1.0 - p) * s_miss * s_miss
}

/// `mixtureUtilization lam p sHit sMiss = lam * meanService` (CacheReuse.lean).
pub fn mixture_utilization(lam: f64, p: f64, s_hit: f64, s_miss: f64) -> f64 {
    lam * mean_service(p, s_hit, s_miss)
}

/// `mixtureWait`: PK wait of the hit/miss mixture (CacheReuse.lean).
pub fn mixture_wait(lam: f64, p: f64, s_hit: f64, s_miss: f64) -> f64 {
    pk_wait(
        lam,
        second_moment_service(p, s_hit, s_miss),
        mixture_utilization(lam, p, s_hit, s_miss),
    )
}

/// `mixtureCV2` (CacheReuse.lean).
pub fn mixture_cv2(p: f64, s_hit: f64, s_miss: f64) -> f64 {
    second_moment_service(p, s_hit, s_miss) / mean_service(p, s_hit, s_miss).powi(2) - 1.0
}

/// `numInSystem lam m2 rho = lam·pkWait + rho`: M/G/1 mean number of turns
/// in the system (MissPrice.lean).
pub fn num_in_system(lam: f64, m2: f64, rho: f64) -> f64 {
    lam * pk_wait(lam, m2, rho) + rho
}

/// `missPrice lam m2 rho sh sm`: the price of one miss (paper Prop. price,
/// MissPrice.lean), the first-order increase of total delay summed over
/// all turns when a turn of service `sh` is served as a miss of service
/// `sm`: `ΔS + λ(sm²-sh²)/(2(1-ρ)) + λ·W·ΔS/(1-ρ)`, `W` the PK wait.
pub fn miss_price(lam: f64, m2: f64, rho: f64, s_h: f64, s_m: f64) -> f64 {
    miss_price_given_wait(lam, pk_wait(lam, m2, rho), rho, s_h, s_m)
}

/// [`miss_price`] with the mean wait `w` supplied directly (e.g. measured)
/// instead of computed from `m2` by PK.
pub fn miss_price_given_wait(lam: f64, w: f64, rho: f64, s_h: f64, s_m: f64) -> f64 {
    let ds = s_m - s_h;
    ds + lam * (s_m * s_m - s_h * s_h) / (2.0 * (1.0 - rho)) + lam * w * ds / (1.0 - rho)
}

/// Kingman's GI/G/1 upper bound on the mean wait (paper §2, cited).
/// Not formalised in Lean; cited as a classical result.
pub fn kingman_bound(lam: f64, var_a: f64, var_s: f64, rho: f64) -> f64 {
    lam * (var_a + var_s) / (2.0 * (1.0 - rho))
}

/// Interactive response-time law `R = N/X - Z` (paper §2, cited).
pub fn irtl_response(n: f64, throughput: f64, think: f64) -> f64 {
    n / throughput - think
}

/// `aggCapacity N sP sD = N/(sP+sD)` (PDDisaggregation.lean).
pub fn agg_capacity(n: f64, s_p: f64, s_d: f64) -> f64 {
    n / (s_p + s_d)
}

/// `pdCapacity NP ND sP sD = min(NP/sP, ND/sD)` (PDDisaggregation.lean).
pub fn pd_capacity(n_p: f64, n_d: f64, s_p: f64, s_d: f64) -> f64 {
    (n_p / s_p).min(n_d / s_d)
}

/// `aggCapacityI N sP sD I = N/(sP+sD+I)` (PDDisaggregation.lean).
pub fn agg_capacity_i(n: f64, s_p: f64, s_d: f64, i: f64) -> f64 {
    n / (s_p + s_d + i)
}

/// `pdComputeCapacity N sP sD gP gD = N/(sP/gP + sD/gD)` (PDDisaggregation.lean).
pub fn pd_compute_capacity(n: f64, s_p: f64, s_d: f64, g_p: f64, g_d: f64) -> f64 {
    n / (s_p / g_p + s_d / g_d)
}

/// `pdFullCapacity`: min of compute, `Bnet/EK` and the two memory caps
/// (PDDisaggregation.lean).
#[allow(clippy::too_many_arguments)]
pub fn pd_full_capacity(
    n: f64,
    s_p: f64,
    s_d: f64,
    g_p: f64,
    g_d: f64,
    b_net: f64,
    e_k: f64,
    mu_p_mem: f64,
    mu_d_mem: f64,
) -> f64 {
    pd_compute_capacity(n, s_p, s_d, g_p, g_d)
        .min(b_net / e_k)
        .min(mu_p_mem.min(mu_d_mem))
}

/// `myopicCost W S = W + S` (Routing.lean).
pub fn myopic_cost(w: f64, s: f64) -> f64 {
    w + s
}

/// `lookaheadCost W S M F = W + S + M + F` (Routing.lean).
pub fn lookahead_cost(w: f64, s: f64, m: f64, f: f64) -> f64 {
    w + s + m + f
}

/// `viaPrefillPool WP SP TKV WD` (Routing.lean).
pub fn via_prefill_pool(w_p: f64, s_p: f64, t_kv: f64, w_d: f64) -> f64 {
    w_p + s_p + t_kv + w_d
}

/// `decodeLocal WD SD I` (Routing.lean).
pub fn decode_local(w_d: f64, s_d: f64, i: f64) -> f64 {
    w_d + s_d + i
}

/// `psNum C ρ = ρ/(C-ρ)`: mean number at an M/G/1-PS station of constant
/// capacity `C` (BatchServer.lean).
pub fn ps_num(c: f64, rho: f64) -> f64 {
    rho / (c - rho)
}

/// `psPrice C ρ dS = C·dS/(C-ρ)²`: the price of one miss at a PS server of
/// capacity `C` (paper Prop. decode, BatchServer.lean).
pub fn ps_price(c: f64, rho: f64, ds: f64) -> f64 {
    c * ds / (c - rho).powi(2)
}

/// `stationaryMean a N ρ`: mean of `π(n) ∝ a(n)ρⁿ` on `{0, …, N}`, with
/// `a.len() = N + 1` (BatchServer.lean). With `a(n) = 1/(φ(1)⋯φ(n))` this is
/// the mean number at a PS station of capacity `φ`, truncated at `N`.
pub fn stationary_mean(a: &[f64], rho: f64) -> f64 {
    let (mut num, mut den, mut pow) = (0.0, 0.0, 1.0);
    for (n, &an) in a.iter().enumerate() {
        num += n as f64 * an * pow;
        den += an * pow;
        pow *= rho;
    }
    num / den
}

/// `expFit d fuel M` with enough fuel: expected number of requests
/// admitted, in arrival order, into `M` free tokens until the first that
/// does not fit, footprints i.i.d. from `d = [(tokens, prob)]`, tokens > 0
/// (Footprint.lean).
pub fn exp_fit(d: &[(f64, f64)], m: f64) -> f64 {
    assert!(d.iter().all(|x| x.0 > 0.0));
    d.iter()
        .filter(|x| x.0 <= m)
        .map(|x| x.1 * (1.0 + exp_fit(d, m - x.0)))
        .sum()
}

/// Finite-source (machine-repair) M/M/1//N queue: `n` sources, each
/// thinking for an exponential time of rate `nu` and then submitting a job
/// of exponential service rate `mu` to one FIFO server. Returns
/// `(L, X, W_q)`: mean number at the server (queue and service),
/// throughput, and mean wait in queue (Little: `W_q = L/X - 1/mu`).
/// `π_k ∝ N!/(N-k)! (ν/μ)^k` for `k = 0..N` (Kleinrock 1975, §3.8).
pub fn finite_source_mm1(n: usize, nu: f64, mu: f64) -> (f64, f64, f64) {
    let r = nu / mu;
    let mut w = 1.0;
    let mut z = 1.0;
    let mut l = 0.0;
    for k in 1..=n {
        w *= (n - k + 1) as f64 * r;
        z += w;
        l += k as f64 * w;
    }
    let l = l / z;
    let p0 = 1.0 / z;
    let x = mu * (1.0 - p0);
    (l, x, l / x - 1.0 / mu)
}

/// Think rate `nu` at which the M/M/1//N server has utilisation `rho`
/// (bisection on `1 - π_0`).
pub fn finite_source_nu_for_utilization(n: usize, mu: f64, rho: f64) -> f64 {
    let (mut lo, mut hi): (f64, f64) = (1e-9, 1e6);
    for _ in 0..200 {
        let mid = (lo * hi).sqrt();
        let (_, x, _) = finite_source_mm1(n, mid, mu);
        if x / mu < rho {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    (lo * hi).sqrt()
}
