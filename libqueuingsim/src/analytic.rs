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

/// Kingman's GI/G/1 upper bound on the mean wait (paper Thm. kingman).
/// Not formalised in Lean; cited as a classical result.
pub fn kingman_bound(lam: f64, var_a: f64, var_s: f64, rho: f64) -> f64 {
    lam * (var_a + var_s) / (2.0 * (1.0 - rho))
}

/// Interactive response-time law `R = N/X - Z` (paper Thm. irtl).
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
