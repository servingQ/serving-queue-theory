//! Named checks of the paper's propositions by simulation.
//!
//! Each [`Check`] states which proposition and Lean theorems it exercises,
//! what the theory predicts, what the simulation observed, and whether they
//! agree. `tests/propositions.rs` asserts every check; `examples/validate.rs`
//! prints them as a report. Scenarios live here once so the two cannot drift.
//!
//! Two kinds of check:
//! * **in-model**: the simulation satisfies the proposition's assumptions,
//!   so disagreement means a bug (in the simulator or in the closed form);
//! * **beyond-model**: an assumption is dropped (non-Poisson arrivals,
//!   emergent hit rate, tandem pools, integer splits, heuristic control) and
//!   the check asks whether the *decision* the proposition implies survives.
//!
//! [`observations`] reports quantities with no prediction attached; they are
//! printed, never asserted.

use crate::analytic::*;
use crate::dist::Dist;
use crate::models::agentic::{
    self, AgenticConfig, CostModel, EvictionPolicy, FetchMode, OffloadPolicy, Population,
    ProgramClass,
};
use crate::models::batch::{self, BatchConfig, BatchReport, Phi, Server, Work, ps_mean_number};
use crate::models::eviction::{self, Item, ResumeModel};
use crate::models::pd::{self, Load, Mode, PdConfig};
use crate::models::queue::{self, QueueConfig};
use crate::models::routing::{self, RoutePolicy, RoutingConfig};
use crate::stats::{Estimate, Welford, batch_means, replications};
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    InModel,
    BeyondModel,
}

#[derive(Clone, Debug)]
pub struct Check {
    pub id: &'static str,
    /// Paper label, e.g. `prop:pk`.
    pub paper: &'static str,
    /// Lean theorems whose statement the check exercises.
    pub lean: &'static [&'static str],
    pub kind: Kind,
    pub claim: &'static str,
    pub expected: String,
    pub observed: String,
    pub pass: bool,
}

/// Every check, in paper order.
pub fn all() -> Vec<Check> {
    vec![
        mm1_response_time(),
        mm1_blowup(),
        pk_formula(),
        variance_orders_delay(),
        cache_reuse_lowers_delay(),
        cv2_ratio(),
        miss_price_bracket(),
        two_stage_prefill_price(),
        ps_insensitivity(),
        bcmp_feedback(),
        ps_price_bracket(),
        footprint_batch_size(),
        lps_vs_saturating_phi(),
        kingman_bursty_arrivals(),
        little_law(),
        closed_throughput_falls_with_concurrency(),
        closed_throughput_nondecreasing_fixed_demand(),
        interactive_response_time_law(),
        always_offload_can_be_worse(),
        selective_offload_never_worse(),
        shortest_first_counterexample(),
        shortest_first_two_approx(),
        shortest_first_tightness(),
        shortest_first_unbounded_with_resume_prob(),
        guarded_density_two_approx(),
        memory_threshold_rule(),
        pd_capacity_matches(),
        pd_no_gain(),
        pd_win_condition_decisions(),
        affinity_breaks_at_high_load(),
        lookahead_not_worse_than_affinity(),
    ]
}

fn rel(a: f64, b: f64) -> f64 {
    (a - b).abs() / b.abs()
}

// -------------------------------------------------------------- §2.2 ----

/// Prop. mm1 (i): M/M/1 response time equals `1/(μ-λ)`.
pub fn mm1_response_time() -> Check {
    let mu = 10.0;
    let mut obs = vec![];
    let mut pass = true;
    for (i, lam) in [5.0, 8.0, 9.0].into_iter().enumerate() {
        let r = queue::simulate(&QueueConfig::mg1(
            lam,
            Dist::exp(1.0 / mu),
            2_000_000,
            10 + i as u64,
        ));
        let w = mm1_wait(mu, lam);
        pass &= r.sojourn.agrees_with(w, 0.01);
        obs.push(format!("λ={lam}: {} vs {w:.4}", r.sojourn));
    }
    Check {
        id: "mm1_response_time",
        paper: "sec:intro (M/M/1)",
        lean: &["mm1Wait_eq_rho_form"],
        kind: Kind::InModel,
        claim: "M/M/1 mean response time is 1/(μ-λ)",
        expected: "simulated W within its 95% CI (+1%) of 1/(μ-λ), μ=10".into(),
        observed: obs.join("; "),
        pass,
    }
}

/// Prop. mm1 (ii)-(iii): W rises steeply toward μ; Ex. mm1's 10× ratio.
pub fn mm1_blowup() -> Check {
    let mu = 10.0;
    let w: Vec<f64> = [9.0, 9.5, 9.9]
        .iter()
        .map(|&lam| {
            queue::simulate(&QueueConfig::mg1(lam, Dist::exp(1.0 / mu), 4_000_000, 20))
                .sojourn
                .mean
        })
        .collect();
    let ratio = w[2] / w[0];
    Check {
        id: "mm1_blowup",
        paper: "sec:intro (M/M/1 example)",
        lean: &[
            "mm1Wait_strictMono",
            "mm1Wait_unbounded",
            "mm1Wait_example_ratio",
        ],
        kind: Kind::InModel,
        claim: "W is increasing and W(9.9)/W(9) = 10 at μ=10",
        expected: "W(9)<W(9.5)<W(9.9); ratio within 15% of 10 (ρ=0.99 converges slowly)".into(),
        observed: format!(
            "W = {:.3}, {:.3}, {:.3}; ratio {ratio:.2}",
            w[0], w[1], w[2]
        ),
        pass: w[0] < w[1] && w[1] < w[2] && rel(ratio, 10.0) < 0.15,
    }
}

/// Theorem pk, used by Prop. pk: the PK mean wait for several service laws.
pub fn pk_formula() -> Check {
    let lam = 0.7;
    let dists = [
        ("D", Dist::Deterministic(1.0)),
        ("E4", Dist::Erlang { k: 4, mean: 1.0 }),
        ("H2(cv²=4)", Dist::hyperexp_balanced(1.0, 4.0)),
        (
            "workloadB",
            Dist::discrete(vec![0.1, 0.1, 0.1, 3.7], vec![0.25; 4]),
        ),
    ];
    let mut pass = true;
    let mut obs = vec![];
    for (i, (name, d)) in dists.iter().enumerate() {
        let r = queue::simulate(&QueueConfig::mg1(lam, d.clone(), 2_000_000, 30 + i as u64));
        let pk = pk_wait(lam, d.second_moment(), lam * d.mean());
        pass &= r.wait.agrees_with(pk, 0.02);
        obs.push(format!("{name}: {} vs {pk:.4}", r.wait));
    }
    Check {
        id: "pk_formula",
        paper: "eq:pk, prop:pk",
        lean: &["secondMoment_eq_variance_add_sq"],
        kind: Kind::InModel,
        claim: "M/G/1 mean wait equals λE[S²]/(2(1-ρ))",
        expected: "simulated Wq within its 95% CI (+2%) of PK at ρ=0.7".into(),
        observed: obs.join("; "),
        pass,
    }
}

/// Prop. pk (ii)-(iii): equal mean, larger variance, longer wait.
pub fn variance_orders_delay() -> Check {
    let a = Dist::Deterministic(1.0);
    let b = Dist::discrete(vec![0.1, 0.1, 0.1, 3.7], vec![0.25; 4]);
    let mut pass = true;
    let mut obs = vec![];
    for rho in [0.3, 0.6, 0.9] {
        let wa = queue::simulate(&QueueConfig::mg1(rho, a.clone(), 1_000_000, 40)).wait;
        let wb = queue::simulate(&QueueConfig::mg1(rho, b.clone(), 1_000_000, 40)).wait;
        pass &= wa.hi() < wb.lo();
        obs.push(format!(
            "ρ={rho}: A {:.3} < B {:.3} (×{:.2}, PK ×3.43)",
            wa.mean,
            wb.mean,
            wb.mean / wa.mean
        ));
    }
    Check {
        id: "variance_orders_delay",
        paper: "prop:pk, ex:pk",
        lean: &[
            "pkWait_strictMono_secondMoment",
            "pkWait_lt_of_variance_lt",
            "workloadB_wait_ratio",
        ],
        kind: Kind::InModel,
        claim: "equal mean, Var[A] < Var[B] ⇒ Wq(A) < Wq(B) at every stable load",
        expected: "CI of Wq(A) entirely below CI of Wq(B) at ρ ∈ {0.3, 0.6, 0.9}".into(),
        observed: obs.join("; "),
        pass,
    }
}

/// Prop. cache: raising the hit rate lowers ρ and the PK delay.
pub fn cache_reuse_lowers_delay() -> Check {
    let (lam, hit, miss) = (1.8, 0.05, 0.5);
    let ps = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0];
    let mut waits = vec![];
    let mut pass = true;
    let mut obs = vec![];
    for (i, &p) in ps.iter().enumerate() {
        let d = Dist::HitMiss {
            p_hit: p,
            hit,
            miss,
        };
        let r = queue::simulate(&QueueConfig::mg1(lam, d, 1_000_000, 50 + i as u64));
        let pk = mixture_wait(lam, p, hit, miss);
        pass &= r.wait.agrees_with(pk, 0.03) || (pk < 1e-3 && r.wait.mean < 1e-3);
        pass &= rel(r.utilization, mixture_utilization(lam, p, hit, miss)) < 0.01;
        waits.push(r.wait.mean);
        obs.push(format!(
            "p={p}: ρ={:.3} Wq={:.4}",
            r.utilization, r.wait.mean
        ));
    }
    pass &= waits.windows(2).all(|w| w[1] < w[0]);
    Check {
        id: "cache_reuse_lowers_delay",
        paper: "prop:cache, ex:cache",
        lean: &[
            "utilization_antitone",
            "pkWait_mixture_antitone",
            "utilization_example_hit80",
        ],
        kind: Kind::InModel,
        claim: "ρ and the PK delay are non-increasing in the hit rate p",
        expected: "Wq strictly decreasing in p, each within CI (+3%) of mixtureWait; ρ(0)=0.9, ρ(0.8)=0.252".into(),
        observed: obs.join("; "),
        pass,
    }
}

/// Ex. cv2 / Eq. cv2: the M/G/1 to M/M/1 delay ratio is (1+CV²)/2.
pub fn cv2_ratio() -> Check {
    let d = Dist::HitMiss {
        p_hit: 0.96,
        hit: 0.05,
        miss: 5.0,
    };
    let lam = 0.5 / d.mean();
    let g = queue::simulate(&QueueConfig::mg1(lam, d.clone(), 4_000_000, 60)).wait;
    let m = queue::simulate(&QueueConfig::mg1(lam, Dist::exp(d.mean()), 4_000_000, 60)).wait;
    let want = (1.0 + d.cv2()) / 2.0;
    let got = g.mean / m.mean;
    Check {
        id: "cv2_ratio",
        paper: "ex:cv2, eq:cv2",
        lean: &["pkWait_ratio_to_exponential", "mixtureCV2_agentic_example"],
        kind: Kind::InModel,
        claim: "96% hits at 50 ms, misses at 5 s: CV² > 15, delay > 8× exponential",
        expected: format!("ratio (1+CV²)/2 = {want:.2} within 6%, at ρ=0.5"),
        observed: format!(
            "CV²={:.2}; Wq {:.4} / {:.4} = {got:.2}",
            d.cv2(),
            g.mean,
            m.mean
        ),
        pass: d.cv2() > 15.0 && rel(got, want) < 0.06,
    }
}

pub const MISS_PRICE_SH: f64 = 0.05;
pub const MISS_PRICE_SM: f64 = 0.5;

/// Outcome of the price-of-a-miss scenario for one `δ`.
#[derive(Clone, Copy, Debug)]
pub struct MissPriceRun {
    pub phi: f64,
    /// Simulated `ΔL = λΔT`, batch-means CI of per-turn differences.
    pub dl: crate::stats::Estimate,
    /// `λδΦ` and `(1-ρ)/(1-ρ')·λδΦ`.
    pub lo: f64,
    pub hi: f64,
    /// Exact PK difference of `L`.
    pub exact: f64,
}

/// M/G/1 with hit/miss service `s_h = 0.05`, `s_m = 0.5`, hit rate 0.8 at
/// `ρ = 0.6`, against the same system with hit rate `0.8 - δ` (common
/// random numbers, 4M turns).
pub fn miss_price_scenario(delta: f64) -> MissPriceRun {
    let (s_h, s_m, p) = (MISS_PRICE_SH, MISS_PRICE_SM, 0.8);
    let base = Dist::HitMiss {
        p_hit: p,
        hit: s_h,
        miss: s_m,
    };
    let lam = 0.6 / base.mean();
    let rho = lam * base.mean();
    let phi = miss_price(lam, base.second_moment(), rho, s_h, s_m);
    let d = Dist::HitMiss {
        p_hit: p - delta,
        hit: s_h,
        miss: s_m,
    };
    let r0 = queue::simulate(&QueueConfig::mg1(lam, base.clone(), 4_000_000, 150));
    let r1 = queue::simulate(&QueueConfig::mg1(lam, d.clone(), 4_000_000, 150));
    let diffs: Vec<f64> = r1
        .sojourns
        .iter()
        .zip(&r0.sojourns)
        .map(|(a, b)| lam * (a - b))
        .collect();
    let lo = lam * delta * phi;
    let rho1 = rho + lam * delta * (s_m - s_h);
    MissPriceRun {
        phi,
        dl: batch_means(&diffs, 20),
        lo,
        hi: (1.0 - rho) / (1.0 - rho1) * lo,
        exact: num_in_system(lam, d.second_moment(), rho1)
            - num_in_system(lam, base.second_moment(), rho),
    }
}

/// Prop. price (the prefill stage as an M/G/1 FIFO queue with Poisson
/// turns): turning a fraction `δ` of turns from hit to miss raises the mean
/// number in system `L` by between `λδΦ` and `(1-ρ)/(1-ρ')·λδΦ`,
/// `Φ = missPrice`. Common random numbers: both runs see the same arrivals
/// and the same uniforms deciding hit/miss, so the turns that become misses
/// are exactly those with `u ∈ [p-δ, p)`, and per-turn sojourn differences
/// give a tight batch-means CI for `ΔL = λΔT`.
pub fn miss_price_bracket() -> Check {
    let mut pass = true;
    let mut obs = vec![];
    let mut phi = 0.0;
    for delta in [0.01, 0.05] {
        let m = miss_price_scenario(delta);
        phi = m.phi;
        // The CI must overlap the bracket, and contain the exact PK
        // difference (to 1 %).
        pass &= m.dl.lo() <= m.hi && m.dl.hi() >= m.lo && m.dl.agrees_with(m.exact, 0.01);
        obs.push(format!(
            "δ={delta}: ΔL {} vs bracket [{:.4}, {:.4}], exact {:.4}",
            m.dl, m.lo, m.hi, m.exact
        ));
    }
    let (s_h, s_m) = (MISS_PRICE_SH, MISS_PRICE_SM);
    Check {
        id: "miss_price_bracket",
        paper: "prop:price",
        lean: &["missPrice_lower", "missPrice_upper"],
        kind: Kind::InModel,
        claim: "λδΦ ≤ ΔL ≤ (1-ρ)/(1-ρ')·λδΦ when a fraction δ of turns changes from hit to miss",
        expected: format!(
            "M/G/1, s_h={s_h}, s_m={s_m}, p=0.8, ρ=0.6, Φ={phi:.3}: 95% CI of ΔL overlaps the bracket and contains the exact PK difference (+1%)"
        ),
        observed: obs.join("; "),
        pass,
    }
}

/// Decode work per turn of the two-stage price scenario (seconds at an
/// idle device, i.e. `0.1/ω = 500` output tokens).
pub const TWO_STAGE_DECODE: f64 = 0.1;

/// Outcome of the two-stage price scenario for one `δ`.
#[derive(Clone, Debug)]
pub struct TwoStagePriceRun {
    /// Mean prefill availability of the baseline run, `r̄`.
    pub avail: f64,
    /// Effective prefill load `λE[P]/r̄` of the baseline.
    pub rho_p: f64,
    /// Baseline mean number in the prefill stage, `λ·TTFT`, and the M/G/1
    /// prediction `numInSystem` at service `P/r̄`.
    pub l_p: Estimate,
    pub l_p_theory: f64,
    /// Rise of the prefill-stage number, `λ·ΔTTFT` (paired, CRN).
    pub dl_p: Estimate,
    /// Bracket `[λδΦ, (1-ρ)/(1-ρ')·λδΦ]` with `Φ = missPrice` at service
    /// `P/r̄`.
    pub lo: f64,
    pub hi: f64,
    /// Change of the decode-stage number, `λ·Δ(R - TTFT)` (paired).
    pub dl_d: Estimate,
    /// Baseline decode-stage number `λ·E[R - TTFT]` and its PS prediction
    /// `Σ nπ(n)` for `φ_D(n) = min(n, ω/a)`.
    pub l_d: Estimate,
    pub l_d_theory: f64,
}

/// Poisson turns at a `TwoStage` replica: prefill work hit/miss
/// (`0.05`/`0.5` s, hit rate 0.8), decode `0.1` s (500 tokens) per turn,
/// `λ` such that `λE[P] = 0.6`, no memory limit, common random numbers
/// against hit rate `0.8 - δ`, 1M turns. Contexts are zero, so the decode
/// stage is `φ_D(n) = min(n, 10)` and the prefill stage runs at
/// availability `1 - n/10` while `n` turns decode.
pub fn two_stage_price_scenario(delta: f64) -> TwoStagePriceRun {
    let (s_h, s_m, p) = (MISS_PRICE_SH, MISS_PRICE_SM, 0.8);
    let base = Dist::HitMiss {
        p_hit: p,
        hit: s_h,
        miss: s_m,
    };
    let lam = 0.6 / base.mean();
    let d = Dist::HitMiss {
        p_hit: p - delta,
        hit: s_h,
        miss: s_m,
    };
    let cfg = |prefill: Dist| {
        let mut c =
            BatchConfig::poisson_turns(lam, prefill.clone(), Server::TwoStage, 1.0e6 / lam, 225);
        c.work = Work::Sampled {
            prefill,
            decode: Dist::Deterministic(TWO_STAGE_DECODE),
        };
        c
    };
    let r0 = batch::simulate(&cfg(base.clone()));
    let r1 = batch::simulate(&cfg(d.clone()));
    let scale = |xs: Vec<f64>| xs.into_iter().map(|x| lam * x).collect::<Vec<_>>();
    let dl_p = batch_means(&scale(batch::paired_differences(&r0.ttfts, &r1.ttfts)), 20);
    let decode = |r: &BatchReport| -> Vec<(u64, f64)> {
        r.responses
            .iter()
            .zip(&r.ttfts)
            .map(|(a, b)| {
                debug_assert_eq!(a.0, b.0);
                (a.0, a.1 - b.1)
            })
            .collect()
    };
    let (d0, d1) = (decode(&r0), decode(&r1));
    let dl_d = batch_means(&scale(batch::paired_differences(&d0, &d1)), 20);
    let l_d = batch_means(&scale(d0.iter().map(|x| x.1).collect()), 20);
    // Prefill stage as M/G/1 with service P/r̄.
    let r = r0.mean_availability;
    let rho = lam * base.mean() / r;
    let m2 = base.second_moment() / (r * r);
    let phi = miss_price(lam, m2, rho, s_h / r, s_m / r);
    let lo = lam * delta * phi;
    let rho1 = rho + lam * delta * (s_m - s_h) / r;
    let omega_over_a = 2.0e-4 / 2.0e-5;
    TwoStagePriceRun {
        avail: r,
        rho_p: rho,
        l_p: little_number_of(&r0.ttft_ci, lam),
        l_p_theory: num_in_system(lam, m2, rho),
        dl_p,
        lo,
        hi: (1.0 - rho) / (1.0 - rho1) * lo,
        dl_d,
        l_d,
        l_d_theory: ps_mean_number(
            &Phi::Saturating {
                beta: 0.0,
                cap: Some(omega_over_a as usize),
            },
            lam * TWO_STAGE_DECODE,
        ),
    }
}

fn little_number_of(e: &Estimate, lam: f64) -> Estimate {
    Estimate {
        mean: lam * e.mean,
        half_width: lam * e.half_width,
    }
}

/// Props. price and decode on the two-resource replica: forcing a fraction
/// `δ` of turns to miss raises the number in the *prefill* stage by an
/// amount bracketed by the M/G/1 price at the stage's effective service
/// `P/r̄` (`r̄` the measured mean availability), while the *decode* stage,
/// whose demand does not depend on hit or miss, is unchanged. Beyond the
/// model in one respect: the prefill rate fluctuates with the decode batch
/// (`1 - n/10`), so the stage is not exactly an M/G/1 at a fixed rate.
pub fn two_stage_prefill_price() -> Check {
    let mut pass = true;
    let mut obs = vec![];
    let mut head = String::new();
    for delta in [0.01, 0.05] {
        let m = two_stage_price_scenario(delta);
        if head.is_empty() {
            head = format!(
                "r̄={:.3}, ρ_P={:.3}, L_P {} vs M/G/1 {:.3}, L_D {} vs PS {:.3}",
                m.avail, m.rho_p, m.l_p, m.l_p_theory, m.l_d, m.l_d_theory
            );
            pass &= m.l_d.agrees_with(m.l_d_theory, 0.02);
        }
        // Prefill: the CI of ΔL_P must overlap the bracket (5% slack for
        // the fluctuating rate). Decode: the CI of ΔL_D must contain 0.
        pass &= m.dl_p.lo() <= 1.05 * m.hi && m.dl_p.hi() >= 0.95 * m.lo;
        pass &= m.dl_d.lo() <= 0.0 && m.dl_d.hi() >= 0.0;
        obs.push(format!(
            "δ={delta}: ΔL_P {} vs [{:.4}, {:.4}], ΔL_D {}",
            m.dl_p, m.lo, m.hi, m.dl_d
        ));
    }
    Check {
        id: "two_stage_prefill_price",
        paper: "prop:price, prop:decode",
        lean: &["missPrice_lower", "missPrice_upper", "stationaryMean"],
        kind: Kind::BeyondModel,
        claim: "on the two-resource replica the price of a miss is paid in the prefill queue (FIFO bracket at the stage's effective service) and not in the decode batch",
        expected: "TwoStage, hit/miss prefill 0.05/0.5, decode 0.1 s, λE[P]=0.6: 95% CI of λΔTTFT overlaps [λδΦ, (1-ρ)/(1-ρ')λδΦ] (5% slack) at service P/r̄; CI of λΔ(R-TTFT) contains 0; baseline decode L within CI (+2%) of Σnπ(n), φ_D(n)=min(n,10)".into(),
        observed: format!("{head}; {}", obs.join("; ")),
        pass,
    }
}

/// §2 Kingman's bound and §7 Limitations: bursty arrivals add delay beyond PK.
pub fn kingman_bursty_arrivals() -> Check {
    let s = Dist::HitMiss {
        p_hit: 0.96,
        hit: 0.05,
        miss: 5.0,
    };
    let rho = 0.7;
    let lam = rho / s.mean();
    let mut pass = true;
    let mut obs = vec![];
    for (i, ca2) in [2.0, 4.0, 8.0].into_iter().enumerate() {
        let ia = Dist::hyperexp_balanced(1.0 / lam, ca2);
        let cfg = QueueConfig {
            interarrival: ia.clone(),
            service: s.clone(),
            servers: 1,
            customers: 4_000_000,
            warmup: 200_000,
            seed: 70 + i as u64,
        };
        let w = queue::simulate(&cfg).wait;
        let bound = kingman_bound(lam, ia.variance(), s.variance(), rho);
        let pk = pk_wait(lam, s.second_moment(), rho);
        pass &= w.mean <= bound && w.lo() > pk;
        obs.push(format!(
            "c_a²={ca2}: PK {pk:.2} < Wq {:.2} ≤ Kingman {bound:.2}",
            w.mean
        ));
    }
    Check {
        id: "kingman_bursty_arrivals",
        paper: "sec:model (Kingman), sec:limits",
        lean: &[],
        kind: Kind::BeyondModel,
        claim: "with non-Poisson arrivals PK underestimates delay; Kingman still bounds it",
        expected: "PK < simulated Wq ≤ Kingman bound for H2 arrivals".into(),
        observed: obs.join("; "),
        pass,
    }
}

/// Thm. little: L = λW in the simulated queue.
pub fn little_law() -> Check {
    let r = queue::simulate(&QueueConfig::mg1(
        0.8,
        Dist::hyperexp_balanced(1.0, 6.0),
        1_000_000,
        80,
    ));
    Check {
        id: "little_law",
        paper: "sec:model (Little)",
        lean: &[],
        kind: Kind::InModel,
        claim: "L = λW",
        expected: "|L-λW|/L < 1%".into(),
        observed: format!(
            "L={:.4}, λW={:.4}",
            r.mean_in_system,
            r.arrival_rate * r.sojourn.mean
        ),
        pass: r.little_residual() < 0.01,
    }
}

// ------------------------------------------------ batching server -------

/// Load of the PS in-model scenarios.
pub const PS_RHO: f64 = 0.7;

/// Two turn-work laws with mean 0.14 s: deterministic, and the hit/miss
/// mixture (hit 0.05 s w.p. 0.8, miss 0.5 s).
pub fn ps_services() -> [(&'static str, Dist); 2] {
    [
        ("D", Dist::Deterministic(0.14)),
        (
            "hit/miss",
            Dist::HitMiss {
                p_hit: 0.8,
                hit: 0.05,
                miss: 0.5,
            },
        ),
    ]
}

/// Mean number at the replica by Little's law, `λ·R`, with the batch-means
/// CI of the mean response.
pub fn little_number(r: &BatchReport, lam: f64) -> Estimate {
    Estimate {
        mean: lam * r.response_ci.mean,
        half_width: lam * r.response_ci.half_width,
    }
}

/// One service law under PS and under FIFO, with their closed forms.
#[derive(Clone, Debug)]
pub struct InsensitivityRow {
    pub name: &'static str,
    pub ps: Estimate,
    pub ps_theory: f64,
    pub fifo: Estimate,
    pub fifo_theory: f64,
}

/// Open Poisson turns at `ρ = 0.7`, no memory limit, 1M turns per run.
pub fn insensitivity_scenario() -> Vec<InsensitivityRow> {
    ps_services()
        .into_iter()
        .enumerate()
        .map(|(i, (name, d))| {
            let lam = PS_RHO / d.mean();
            let run = |server| {
                let c =
                    BatchConfig::poisson_turns(lam, d.clone(), server, 1.0e6 / lam, 200 + i as u64);
                little_number(&batch::simulate(&c), lam)
            };
            InsensitivityRow {
                name,
                ps: run(Server::Ps {
                    phi: Phi::Constant(1.0),
                }),
                ps_theory: ps_num(1.0, PS_RHO),
                fifo: run(Server::Fifo),
                fifo_theory: num_in_system(lam, d.second_moment(), PS_RHO),
            }
        })
        .collect()
}

/// PS insensitivity: under processor sharing the mean number depends on the
/// work law only through the load; under FIFO it follows PK.
pub fn ps_insensitivity() -> Check {
    let rows = insensitivity_scenario();
    let mut pass = true;
    let mut obs = vec![];
    for r in &rows {
        pass &= r.ps.agrees_with(r.ps_theory, 0.02) && r.fifo.agrees_with(r.fifo_theory, 0.02);
        obs.push(format!(
            "{}: PS {} vs {:.4}, FIFO {} vs PK {:.4}",
            r.name, r.ps, r.ps_theory, r.fifo, r.fifo_theory
        ));
    }
    // FIFO separates the two laws, PS does not.
    pass &= rows[0].fifo.hi() < rows[1].fifo.lo();
    Check {
        id: "ps_insensitivity",
        paper: "sec:batch, prop:decode",
        lean: &["psNum"],
        kind: Kind::InModel,
        claim: "at a PS server L = ρ/(C-ρ) for every work law with the same mean; at a FIFO server L follows PK",
        expected: "ρ=0.7, φ≡1, work D or hit/miss (mean 0.14 s): PS L within CI (+2%) of ρ/(1-ρ) for both; FIFO L within CI (+2%) of λW_q+ρ and FIFO(D) < FIFO(hit/miss)".into(),
        observed: obs.join("; "),
        pass,
    }
}

/// One open-session run against the isolated PS formula.
#[derive(Clone, Debug)]
pub struct BcmpRow {
    pub phi: Phi,
    pub rho: f64,
    /// Turn rate `Λ/(1-p)`.
    pub lam: f64,
    pub throughput: f64,
    pub sim: Estimate,
    pub theory: f64,
}

/// Sessions arrive Poisson at `Λ`; each turn is followed by an H2 tool
/// call (mean 2 s, CV² 4) and another turn w.p. `p = 0.8`. Work per turn is
/// the hit/miss mixture. `φ ≡ 1` at `ρ = 0.7`, and `φ(n) = n/(1+(n-1)/4)`
/// (saturating at 4) at `ρ = 3`.
pub fn bcmp_scenario() -> Vec<BcmpRow> {
    let s = ps_services()[1].1.clone();
    let p = 0.8;
    [
        (Phi::Constant(1.0), PS_RHO),
        (
            Phi::Saturating {
                beta: 0.25,
                cap: None,
            },
            3.0,
        ),
    ]
    .into_iter()
    .enumerate()
    .map(|(i, (phi, rho))| {
        let lam = rho / s.mean();
        let mut c = BatchConfig::poisson_turns(
            lam * (1.0 - p),
            s.clone(),
            Server::Ps { phi },
            8.0e5 / lam,
            210 + i as u64,
        );
        c.classes[0].resume_prob = p;
        c.classes[0].tool_time = Dist::hyperexp_balanced(2.0, 4.0);
        let r = batch::simulate(&c);
        BcmpRow {
            phi,
            rho,
            lam,
            throughput: r.throughput,
            sim: little_number(&r, lam),
            theory: ps_mean_number(&phi, rho),
        }
    })
    .collect()
}

/// BCMP: with feedback through a general tool delay, the mean number at a
/// PS replica is that of an isolated PS queue fed at `λ = Λ/(1-p)`.
pub fn bcmp_feedback() -> Check {
    let rows = bcmp_scenario();
    let mut pass = true;
    let mut obs = vec![];
    for r in &rows {
        pass &= r.sim.agrees_with(r.theory, 0.02) && rel(r.throughput, r.lam) < 0.01;
        obs.push(format!(
            "{:?}, ρ={}: L {} vs {:.4}; X {:.3} vs λ {:.3}",
            r.phi, r.rho, r.sim, r.theory, r.throughput, r.lam
        ));
    }
    Check {
        id: "bcmp_feedback",
        paper: "sec:sessions, prop:decode",
        lean: &["psNum", "stationaryMean"],
        kind: Kind::InModel,
        claim: "open sessions with feedback: L at the PS replica equals Σ n π(n), π(n) ∝ ρⁿ/Π φ(k), with λ = Λ/(1-p)",
        expected: "p=0.8, H2 tool time (CV² 4), hit/miss work: L within CI (+2%) of the formula for φ≡1 and a saturating φ; turn throughput within 1% of Λ/(1-p)".into(),
        observed: obs.join("; "),
        pass,
    }
}

/// The PS analogue of [`miss_price_scenario`]: M/G/1-PS with `φ ≡ 1`,
/// hit/miss work `0.05`/`0.5` s, hit rate 0.8 at `ρ = 0.6`, against hit
/// rate `0.8 - δ`, common random numbers, 1M turns.
pub fn ps_price_scenario(delta: f64) -> MissPriceRun {
    let (s_h, s_m, p) = (MISS_PRICE_SH, MISS_PRICE_SM, 0.8);
    let base = Dist::HitMiss {
        p_hit: p,
        hit: s_h,
        miss: s_m,
    };
    let lam = 0.6 / base.mean();
    let rho = lam * base.mean();
    let d = Dist::HitMiss {
        p_hit: p - delta,
        hit: s_h,
        miss: s_m,
    };
    let ps = Server::Ps {
        phi: Phi::Constant(1.0),
    };
    let r0 = batch::simulate(&BatchConfig::poisson_turns(lam, base, ps, 1.0e6 / lam, 220));
    let r1 = batch::simulate(&BatchConfig::poisson_turns(lam, d, ps, 1.0e6 / lam, 220));
    let diffs: Vec<f64> = batch::paired_differences(&r0.responses, &r1.responses)
        .into_iter()
        .map(|x| lam * x)
        .collect();
    let phi = ps_price(1.0, rho, s_m - s_h);
    let lo = lam * delta * phi;
    let rho1 = rho + lam * delta * (s_m - s_h);
    MissPriceRun {
        phi,
        dl: batch_means(&diffs, 20),
        lo,
        hi: (1.0 - rho) / (1.0 - rho1) * lo,
        exact: ps_num(1.0, rho1) - ps_num(1.0, rho),
    }
}

/// Prop. decode: at a PS server of capacity `C`, turning a fraction `δ` of
/// turns into misses raises `L` by between `λδΦ_PS` and
/// `(C-ρ)/(C-ρ')·λδΦ_PS`, `Φ_PS = CΔS/(C-ρ)²`; the upper end is exact.
pub fn ps_price_bracket() -> Check {
    let mut pass = true;
    let mut obs = vec![];
    for delta in [0.01, 0.05] {
        let m = ps_price_scenario(delta);
        pass &= m.dl.lo() <= m.hi && m.dl.hi() >= m.lo && m.dl.agrees_with(m.exact, 0.01);
        obs.push(format!(
            "δ={delta}: ΔL {} vs bracket [{:.4}, {:.4}], exact {:.4}",
            m.dl, m.lo, m.hi, m.exact
        ));
    }
    Check {
        id: "ps_price_bracket",
        paper: "prop:decode",
        lean: &["psPrice_lower", "psPrice_upper", "psNum_diff_exact"],
        kind: Kind::InModel,
        claim: "λδΦ_PS ≤ ΔL ≤ (C-ρ)/(C-ρ')·λδΦ_PS at a PS server, Φ_PS = CΔS/(C-ρ)²",
        expected: "M/G/1-PS, C=1, s_h=0.05, s_m=0.5, p=0.8, ρ=0.6: 95% CI of ΔL overlaps the bracket and contains the exact difference ρ'/(1-ρ')-ρ/(1-ρ) (+1%)".into(),
        observed: obs.join("; "),
        pass,
    }
}

/// One footprint law: exact `expFit` vs Monte Carlo of FIFO admission.
#[derive(Clone, Debug)]
pub struct FootprintRow {
    pub law: &'static str,
    pub theory: f64,
    pub sim: Estimate,
}

/// `M = 12`; footprints 6, {5,7}, 7, {2,12}; 1M draws each.
pub fn footprint_scenario() -> Vec<FootprintRow> {
    let m = 12.0;
    let laws: [(&str, Vec<(f64, f64)>); 4] = [
        ("$K\\equiv 6$", vec![(6.0, 1.0)]),
        ("$K\\in\\{5,7\\}$", vec![(5.0, 0.5), (7.0, 0.5)]),
        ("$K\\equiv 7$", vec![(7.0, 1.0)]),
        ("$K\\in\\{2,12\\}$", vec![(2.0, 0.5), (12.0, 0.5)]),
    ];
    laws.into_iter()
        .enumerate()
        .map(|(i, (law, d))| {
            let dist = Dist::discrete(
                d.iter().map(|x| x.0).collect(),
                d.iter().map(|x| x.1).collect(),
            );
            let mut rng = StdRng::seed_from_u64(230 + i as u64);
            let mut w = Welford::new();
            for _ in 0..1_000_000 {
                w.push(batch::fifo_admitted(m, &dist, &mut rng) as f64);
            }
            FootprintRow {
                law,
                theory: exp_fit(&d, m),
                sim: Estimate {
                    mean: w.mean(),
                    half_width: 1.96 * (w.variance() / w.n() as f64).sqrt(),
                },
            }
        })
        .collect()
}

/// Prop. footprint: with memory `M` and FIFO admission, the expected number
/// admitted depends on the footprint law, and more variance can lower or
/// raise it.
pub fn footprint_batch_size() -> Check {
    let rows = footprint_scenario();
    let mut pass = rows
        .iter()
        .all(|r| r.sim.agrees_with(r.theory, 1e-3) || r.sim.half_width == 0.0);
    pass &= rows.iter().all(|r| (r.sim.mean - r.theory).abs() < 0.01);
    pass &= rows[1].sim.hi() < rows[0].sim.lo() && rows[2].sim.hi() < rows[3].sim.lo();
    Check {
        id: "footprint_batch_size",
        paper: "prop:footprint",
        lean: &["footprint_variance_hurts", "footprint_variance_helps"],
        kind: Kind::InModel,
        claim: "M=12: K≡6 admits 2, K∈{5,7} admits 7/4; K≡7 admits 1, K∈{2,12} admits 95/64",
        expected:
            "Monte Carlo means (1M draws) within CI of expFit, and ordered as the proposition says"
                .into(),
        observed: rows
            .iter()
            .map(|r| format!("{}: {} vs {:.4}", r.law, r.sim, r.theory))
            .collect::<Vec<_>>()
            .join("; "),
        pass,
    }
}

/// Exact limited PS against the theory's saturating `φ`, one cell.
#[derive(Clone, Debug)]
pub struct LpsRow {
    pub service: &'static str,
    pub cv2: f64,
    /// Load relative to `φ(B)`.
    pub u: f64,
    pub theory: f64,
    pub ps: Estimate,
    pub lps: Estimate,
}

pub const LPS_CAP: usize = 8;
pub const LPS_BETA: f64 = 0.1;

/// Poisson turns; exact LPS (at most `B = 8` in the batch at
/// `φ(n) = n/(1+0.1(n-1))`, FIFO beyond) against PS with the same `φ`
/// flattened at `B`, for work laws D, Exp and H2 (CV² 4) of mean 1 and
/// loads `u = ρ/φ(B)`. 400k turns per run.
pub fn lps_scenario() -> Vec<LpsRow> {
    let base = Phi::Saturating {
        beta: LPS_BETA,
        cap: None,
    };
    let capped = Phi::Saturating {
        beta: LPS_BETA,
        cap: Some(LPS_CAP),
    };
    let mut rows = vec![];
    for (i, (service, d)) in [
        ("D", Dist::Deterministic(1.0)),
        ("Exp", Dist::exp(1.0)),
        ("H2", Dist::hyperexp_balanced(1.0, 4.0)),
    ]
    .into_iter()
    .enumerate()
    {
        for (j, u) in [0.5, 0.8, 0.9].into_iter().enumerate() {
            let rho = u * capped.limit();
            let lam = rho / d.mean();
            let seed = 240 + (3 * i + j) as u64;
            let mut lps = BatchConfig::poisson_turns(
                lam,
                d.clone(),
                Server::Ps { phi: base },
                4.0e5 / lam,
                seed,
            );
            lps.batch_cap = Some(LPS_CAP);
            let ps = BatchConfig::poisson_turns(
                lam,
                d.clone(),
                Server::Ps { phi: capped },
                4.0e5 / lam,
                seed,
            );
            rows.push(LpsRow {
                service,
                cv2: d.cv2(),
                u,
                theory: ps_mean_number(&capped, rho),
                ps: little_number(&batch::simulate(&ps), lam),
                lps: little_number(&batch::simulate(&lps), lam),
            });
        }
    }
    rows
}

/// How far is the theory's "φ saturating at B" from the exact batch cap?
/// Both give the same total rate in every state; they differ in who gets
/// it. The PS side is insensitive; the LPS side is not.
pub fn lps_vs_saturating_phi() -> Check {
    let rows = lps_scenario();
    let mut pass = true;
    let mut obs = vec![];
    for r in &rows {
        pass &= r.ps.agrees_with(r.theory, 0.03);
        match r.service {
            "Exp" => pass &= r.lps.agrees_with(r.theory, 0.03),
            "D" if r.u >= 0.8 => pass &= r.lps.hi() < r.theory,
            "H2" if r.u >= 0.8 => pass &= r.lps.lo() > r.theory,
            _ => {}
        }
        obs.push(format!(
            "{} u={}: formula {:.3}, PS {:.3}, LPS {:.3} ({:+.1}%)",
            r.service,
            r.u,
            r.theory,
            r.ps.mean,
            r.lps.mean,
            100.0 * (r.lps.mean / r.theory - 1.0)
        ));
    }
    Check {
        id: "lps_vs_saturating_phi",
        paper: "sec:batch",
        lean: &["stationaryMean"],
        kind: Kind::BeyondModel,
        claim: "a batch cap B is modelled by φ flattened at B; the exact cap (LPS) is not insensitive, so the error depends on the work law",
        expected: "B=8, β=0.1: PS with flattened φ within CI (+3%) of Σnπ(n) for every law; LPS equals it for Exp (+3%), is below it for D and above it for H2 (CV² 4) at u ≥ 0.8".into(),
        observed: obs.join("; "),
        pass,
    }
}

// ---------------------------------------------------------- §2.3 / §3.2 -

/// §2.3: in a closed system with finite KV, throughput falls with N
/// because the hit rate falls and E[S] rises.
pub fn closed_throughput_falls_with_concurrency() -> Check {
    let ns = [16, 32, 64, 96];
    let rs: Vec<_> = ns
        .iter()
        .map(|&n| agentic::simulate(&AgenticConfig::example(n, 6.0e5)))
        .collect();
    let dec =
        |f: &dyn Fn(&agentic::AgenticReport) -> f64| rs.windows(2).all(|w| f(&w[1]) < f(&w[0]));
    let pass = dec(&|r| r.throughput) && dec(&|r| r.hit_rate) && dec(&|r| -r.service.mean());
    let obs = ns
        .iter()
        .zip(&rs)
        .map(|(n, r)| {
            format!(
                "N={n}: X={:.2}/s hit={:.2} E[S]={:.2}s",
                r.throughput,
                r.hit_rate,
                r.service.mean()
            )
        })
        .collect::<Vec<_>>()
        .join("; ");
    Check {
        id: "closed_throughput_falls_with_concurrency",
        paper: "sec:model (closed network), sec:offload",
        lean: &["meanService_antitone"],
        kind: Kind::BeyondModel,
        claim: "a throughput that falls with N signals per-step demand growing with N, via a falling hit rate",
        expected:
            "X, hit rate decreasing and E[S] increasing in N (hit rate emergent, not assumed)"
                .into(),
        observed: obs,
        pass,
    }
}

/// §2.3, fixed-demand side: with ample KV every follow-up turn hits, the
/// per-visit demand does not depend on N, and throughput is non-decreasing
/// in N and below the asymptotic bound `min(N/(D+Z), 1/D)`
/// (Lazowska et al.). This is the control case for
/// [`closed_throughput_falls_with_concurrency`].
pub fn closed_throughput_nondecreasing_fixed_demand() -> Check {
    let ns = [1, 2, 4, 8, 16, 32];
    let mut pass = true;
    let mut prev = 0.0;
    let mut obs = vec![];
    for n in ns {
        let mut cfg = AgenticConfig::example(n, 1.0e9);
        cfg.max_context = 2.0e5;
        let r = agentic::simulate(&cfg);
        let d = r.service.mean();
        let z = r.think.mean();
        let bound = (n as f64 / (d + z)).min(1.0 / d);
        pass &= r.hit_rate == 1.0 && r.throughput >= 0.99 * prev && r.throughput <= 1.01 * bound;
        prev = r.throughput;
        obs.push(format!("N={n}: X={:.2} ≤ {bound:.2}", r.throughput));
    }
    Check {
        id: "closed_throughput_nondecreasing_fixed_demand",
        paper: "sec:model (closed network)",
        lean: &[],
        kind: Kind::InModel,
        claim: "with fixed per-visit demand, closed-network throughput does not decrease with N",
        expected:
            "ample KV (hit rate 1): X non-decreasing in N (1% slack) and ≤ min(N/(D+Z), 1/D) (+1%)"
                .into(),
        observed: obs.join("; "),
        pass,
    }
}

/// Thm. irtl: R = N/X − Z in the closed agentic system.
pub fn interactive_response_time_law() -> Check {
    let mut worst: f64 = 0.0;
    let mut obs = vec![];
    for n in [8, 32, 96] {
        let r = agentic::simulate(&AgenticConfig::example(n, 6.0e5));
        let res = r.irtl_residual(n as f64);
        worst = worst.max(res);
        obs.push(format!(
            "N={n}: R={:.2} N/X-Z={:.2}",
            r.response.mean(),
            irtl_response(n as f64, r.throughput, r.think.mean())
        ));
    }
    Check {
        id: "interactive_response_time_law",
        paper: "sec:model (closed network)",
        lean: &[],
        kind: Kind::InModel,
        claim: "R = N/X - Z",
        expected: "|N - X(R+Z)|/N < 1%".into(),
        observed: format!("{} (worst residual {:.2}%)", obs.join("; "), 100.0 * worst),
        pass: worst < 0.01,
    }
}

/// Closed example workload with blocking fetches over a tier of `bw` tokens/s.
pub fn offload_cfg(n: usize, bw: f64, policy: OffloadPolicy) -> AgenticConfig {
    let mut cfg = AgenticConfig::example(n, 6.0e5);
    cfg.offload = policy;
    cfg.fetch = FetchMode::Blocking;
    cfg.tier_bandwidth = bw;
    cfg
}

/// Prop. option, second part: some costs make always-offload strictly worse.
/// Here: blocking fetches over a slow tier at high concurrency, the regime
/// of ThunderAgent App. A.2.
pub fn always_offload_can_be_worse() -> Check {
    let never = agentic::simulate(&offload_cfg(32, 5.0e3, OffloadPolicy::Never));
    let always = agentic::simulate(&offload_cfg(32, 5.0e3, OffloadPolicy::Always));
    Check {
        id: "always_offload_can_be_worse",
        paper: "sec:offload (option value)",
        lean: &["always_offload_can_be_worse"],
        kind: Kind::BeyondModel,
        claim: "always-offload can be strictly worse than never offloading",
        expected: "N=32, 5k tok/s tier, blocking fetch: X(always) < X(never)".into(),
        observed: format!(
            "X never={:.3}/s (hit {:.2}), always={:.3}/s (hit {:.2}, tier util {:.2}, stall {:.2})",
            never.throughput,
            never.hit_rate,
            always.throughput,
            always.hit_rate,
            always.tier_utilization,
            always.stall_load
        ),
        pass: always.throughput < never.throughput,
    }
}

/// Prop. option, first part, for a heuristic controller: choosing per
/// program between keep/offload/recompute is not worse than either fixed
/// policy. The Lean theorem is about the optimum; this checks whether a
/// simple congestion-aware rule gets close to it on a grid.
pub fn selective_offload_never_worse() -> Check {
    let mut pass = true;
    let mut obs = vec![];
    for bw in [5.0e3, 2.0e4, 1.0e5] {
        for n in [32, 64] {
            let x = |p| agentic::simulate(&offload_cfg(n, bw, p)).throughput;
            let (nv, al, se) = (
                x(OffloadPolicy::Never),
                x(OffloadPolicy::Always),
                x(OffloadPolicy::Selective),
            );
            let best = nv.max(al);
            pass &= se >= 0.97 * best;
            obs.push(format!(
                "bw={bw:.0e} N={n}: never {nv:.2} always {al:.2} selective {se:.2}"
            ));
        }
    }
    Check {
        id: "selective_offload_never_worse",
        paper: "sec:offload (option value)",
        lean: &[
            "optimal_cost_antitone_in_actions",
            "enabling_offload_never_hurts",
        ],
        kind: Kind::BeyondModel,
        claim: "enabling offloading never hurts when the choice is made per program",
        expected: "X(selective) ≥ 0.97·max(X(never), X(always)) on all 6 cells".into(),
        observed: obs.join("; "),
        pass,
    }
}

// ---------------------------------------------------------------- §3.1 --

/// Prop. evict (i).
pub fn shortest_first_counterexample() -> Check {
    let it: Vec<Item> = [4, 5, 6].iter().map(|&c| Item::uniform(c)).collect();
    let sf = eviction::subset_cost(&it, &eviction::shortest_first(&it, 6));
    let (opt, _) = eviction::optimal(&it, 6).expect("feasible");
    Check {
        id: "shortest_first_counterexample",
        paper: "sec:evict (SF counterexample)",
        lean: &[
            "shortestFirst_not_optimal",
            "shortestFirst_optimality_claim_false",
        ],
        kind: Kind::InModel,
        claim: "c={4,5,6}, ΔC=6: SF costs 41, {6} costs 36",
        expected: "SF=41, OPT=36".into(),
        observed: format!("SF={sf}, OPT={opt}"),
        pass: sf == 41.0 && opt == 36.0,
    }
}

/// Prop. evict (ii): SF/OPT ≤ 2 with uniform resume probabilities.
pub fn shortest_first_two_approx() -> Check {
    let mut worst: f64 = 0.0;
    let mut mean = vec![];
    for (i, (n, max_c)) in [(6, 20), (12, 200), (18, 60)].into_iter().enumerate() {
        let v = eviction::sweep(3000, n, max_c, ResumeModel::Uniform, 90 + i as u64);
        worst = v.iter().map(|r| r.shortest_first).fold(worst, f64::max);
        mean.push(v.iter().map(|r| r.shortest_first).sum::<f64>() / v.len() as f64);
    }
    Check {
        id: "shortest_first_two_approx",
        paper: "prop:blind (ii)",
        lean: &["shortestFirst_feasible", "shortestFirst_two_approx"],
        kind: Kind::InModel,
        claim: "SF is a 2-approximation when all p_i are equal",
        expected: "max SF/OPT ≤ 2 over 9000 random instances".into(),
        observed: format!(
            "max {worst:.3}; mean {:.3}, {:.3}, {:.3}",
            mean[0], mean[1], mean[2]
        ),
        pass: worst <= 2.0 + 1e-12,
    }
}

/// Prop. evict (ii), tightness: c={K,K+1}, ΔC=K+1.
pub fn shortest_first_tightness() -> Check {
    let mut pass = true;
    let mut last = 0.0;
    for k in [1u64, 2, 5, 10, 100, 1000] {
        let it = vec![Item::uniform(k), Item::uniform(k + 1)];
        let sf = eviction::subset_cost(&it, &eviction::shortest_first(&it, k + 1));
        let (opt, _) = eviction::optimal(&it, k + 1).expect("feasible");
        let r = sf / opt;
        let want = ((k * k + (k + 1) * (k + 1)) as f64) / ((k + 1) * (k + 1)) as f64;
        pass &= (r - want).abs() < 1e-12 && r > last && r < 2.0;
        last = r;
    }
    Check {
        id: "shortest_first_tightness",
        paper: "prop:blind (ii)",
        lean: &["shortestFirst_two_approx_tight"],
        kind: Kind::InModel,
        claim: "the factor 2 is tight",
        expected: "ratio (K²+(K+1)²)/(K+1)², increasing to 2".into(),
        observed: format!("ratio at K=1000: {last:.5}"),
        pass: pass && last > 1.99,
    }
}

/// Prop. evict (iii): with resume probabilities SF has no constant ratio,
/// and the density rule is much closer to optimal on random instances.
pub fn shortest_first_unbounded_with_resume_prob() -> Check {
    // Lean witness: A (c=2, p=1) vs B (c=M, p=1/M³), ΔC=2: ratio 4M.
    let mut pass = true;
    for m in [10u64, 100, 1000] {
        let it = vec![
            Item { c: 2, p: 1.0 },
            Item {
                c: m,
                p: 1.0 / (m as f64).powi(3),
            },
        ];
        let sf = eviction::subset_cost(&it, &eviction::shortest_first(&it, 2));
        let (opt, _) = eviction::optimal(&it, 2).expect("feasible");
        pass &= sf / opt > m as f64;
    }
    let v = eviction::sweep(3000, 12, 200, ResumeModel::Varied { lo: 0.05 }, 99);
    let max_sf = v.iter().map(|r| r.shortest_first).fold(0.0, f64::max);
    let mean_sf = v.iter().map(|r| r.shortest_first).sum::<f64>() / v.len() as f64;
    let mean_d = v.iter().map(|r| r.density_first).sum::<f64>() / v.len() as f64;
    pass &= max_sf > 2.0 && mean_d < mean_sf;
    Check {
        id: "shortest_first_unbounded_with_resume_prob",
        paper: "prop:blind (i), sec:evict (Dantzig)",
        lean: &[
            "shortestFirst_unbounded_with_resume_prob",
            "shortestFirst_wrong_with_resume_prob",
        ],
        kind: Kind::InModel,
        claim: "with p_i c_i² costs SF has no constant ratio; the density order p_i c_i is the relaxation's greedy",
        expected: "witness ratio > M for M=10,100,1000; on random p_i: max SF/OPT > 2 and mean(density) < mean(SF)".into(),
        observed: format!(
            "random p_i∈[0.05,1]: SF max {max_sf:.2} mean {mean_sf:.3}; density mean {mean_d:.3}"
        ),
        pass,
    }
}

/// Prop. guarded: with arbitrary weights `w_i` (e.g. prices `p_i Φ_i`),
/// plain density greedy has no constant ratio, while the guarded density
/// greedy stays within 2 of the optimum.
pub fn guarded_density_two_approx() -> Check {
    let mut pass = true;
    for k in [10u64, 1000, 100_000] {
        let (it, delta) = eviction::density_counterexample(k);
        let d = eviction::weighted_cost(&it, &eviction::density_weighted(&it, delta));
        let g = eviction::guarded_density(&it, delta).expect("feasible");
        let (opt, _) = eviction::optimal_weighted(&it, delta).expect("feasible");
        pass &= d == k as f64 && opt == 2.0 && eviction::weighted_cost(&it, &g) == 2.0;
    }
    let mut v = vec![];
    for (i, (n, max_c)) in [(6, 20), (12, 200), (18, 60)].into_iter().enumerate() {
        v.extend(eviction::sweep_weighted(3000, n, max_c, 160 + i as u64));
    }
    let q: Vec<eviction::Ratios> = (0..3)
        .flat_map(|i| eviction::sweep(3000, 12, 200, ResumeModel::Varied { lo: 0.05 }, 170 + i))
        .collect();
    let max = |xs: &[eviction::Ratios], f: fn(&eviction::Ratios) -> f64| {
        xs.iter().map(f).fold(0.0, f64::max)
    };
    let (gw, dw) = (max(&v, |r| r.guarded_density), max(&v, |r| r.density_first));
    let gq = max(&q, |r| r.guarded_density);
    pass &= gw <= 2.0 + 1e-12 && gq <= 2.0 + 1e-12 && dw > 2.0;
    Check {
        id: "guarded_density_two_approx",
        paper: "prop:guarded",
        lean: &[
            "densityFirst_unbounded",
            "threshold_prefix_le",
            "guardedGreedy_two_approx",
        ],
        kind: Kind::InModel,
        claim: "guarded density greedy is a 2-approximation for arbitrary weights; plain density greedy is not",
        expected: "witness (1,0),(K,K),(1,2), ΔC=2: density pays K, guarded and OPT 2; max guarded/OPT ≤ 2 over 9000 general-weight and 9000 p_i c_i² instances; plain density max > 2".into(),
        observed: format!(
            "general weights: guarded max {gw:.3}, density max {dw:.1}; p_i c_i²: guarded max {gq:.3}"
        ),
        pass,
    }
}

/// One random memory-pricing instance: states with price `w_i` (e.g.
/// `p_i Φ_i`) and byte-seconds `c_i = tokens × τ_i` (integers, for the DP).
fn memory_instance(rng: &mut StdRng, n: usize) -> Vec<eviction::Weighted> {
    (0..n)
        .map(|_| eviction::Weighted {
            c: rng.random_range(1..=8u64) * rng.random_range(1..=8u64),
            w: 10f64.powf(rng.random_range(-1.0..=2.0)),
        })
        .collect()
}

/// Prop. memory: (i) the θ-threshold set `{i : w_i ≤ θ c_i}` costs no more
/// than any set freeing at least as many byte-seconds (exact DP optimum);
/// (ii) at block level, the density prefix plus the block that completes
/// the target costs at most the optimum plus that block's price, although
/// plain density order alone is not optimal.
pub fn memory_threshold_rule() -> Check {
    let mut rng = StdRng::seed_from_u64(180);
    let (mut thresholds, mut ok_i) = (0usize, 0usize);
    let mut pass = true;
    for _ in 0..2000 {
        let n = rng.random_range(4..=12);
        let items = memory_instance(&mut rng, n);
        let thetas: Vec<f64> = items
            .iter()
            .map(eviction::Weighted::density)
            .chain(std::iter::once(0.0))
            .collect();
        for theta in thetas {
            let t: Vec<usize> = (0..items.len())
                .filter(|&i| items[i].w <= theta * items[i].c as f64)
                .collect();
            let freed = eviction::weighted_freed(&items, &t);
            let (opt, _) = eviction::optimal_weighted(&items, freed).expect("feasible");
            let cost = eviction::weighted_cost(&items, &t);
            thresholds += 1;
            if cost <= opt * (1.0 + 1e-12) {
                ok_i += 1;
            }
        }
    }
    pass &= ok_i == thresholds;
    // (ii) blocks: c_i = τ_i of the block's program, target ΔC random.
    let (mut blocks, mut ok_ii, mut greedy_beats_opt) = (0usize, 0usize, 0usize);
    let mut worst_excess: f64 = 0.0;
    for _ in 0..3000 {
        let n = rng.random_range(4..=16);
        let items: Vec<eviction::Weighted> = (0..n)
            .map(|_| eviction::Weighted {
                c: rng.random_range(1..=8),
                w: 10f64.powf(rng.random_range(-1.0..=2.0)),
            })
            .collect();
        let total: u64 = items.iter().map(|i| i.c).sum();
        let delta = rng.random_range(1..=total);
        let g = eviction::density_weighted(&items, delta);
        let x = *g.last().expect("delta ≥ 1 takes a block");
        let cost = eviction::weighted_cost(&items, &g);
        let (opt, _) = eviction::optimal_weighted(&items, delta).expect("feasible");
        blocks += 1;
        if cost <= opt + items[x].w + 1e-9 {
            ok_ii += 1;
        }
        if cost > opt * (1.0 + 1e-9) {
            greedy_beats_opt += 1;
            worst_excess = worst_excess.max((cost - opt) / items[x].w);
        }
    }
    pass &= ok_ii == blocks && greedy_beats_opt > 0;
    Check {
        id: "memory_threshold_rule",
        paper: "prop:memory",
        lean: &["threshold_rule_optimal", "density_prefix_plus_one"],
        kind: Kind::InModel,
        claim: "dropping exactly the states priced at most θ per byte-second is optimal for the memory it frees; block-level density order is optimal up to one block",
        expected: "(i) Σ_T w = OPT(Σ_T c) at every candidate θ of 2000 random instances (4–12 states, c_i = tokens·τ_i); (ii) density prefix + completing block ≤ OPT + w_x on 3000 block instances, with plain density > OPT on some".into(),
        observed: format!(
            "(i) {ok_i}/{thresholds} thresholds optimal; (ii) {ok_ii}/{blocks} within one block, density > OPT on {greedy_beats_opt}, worst excess {worst_excess:.3} of the completing block's price"
        ),
        pass,
    }
}

// ------------------------------------------------------------------ §4 --

/// Saturated PD scenario with exponential work and `E[K] = 1`.
pub fn pd_cfg(
    n: usize,
    mode: Mode,
    sp: f64,
    sd: f64,
    i: f64,
    g: (f64, f64),
    bnet: f64,
) -> PdConfig {
    let mut c = PdConfig::from_means(
        n,
        mode,
        Load::Saturated { jobs: 10 * n },
        sp,
        sd,
        i,
        g,
        bnet,
        1.0,
    );
    c.requests = 100_000;
    c.warmup = 10_000;
    c
}

/// Prop. pd (iii), capacity side: the scalar capacities are what a tandem
/// of FIFO pools actually delivers when saturated.
pub fn pd_capacity_matches() -> Check {
    let mut pass = true;
    let mut obs = vec![];
    let agg = pd::simulate(&pd_cfg(
        32,
        Mode::Aggregated,
        1.0,
        1.0,
        0.5,
        (2.0, 1.0),
        1000.0,
    ));
    let want = agg_capacity_i(32.0, 1.0, 1.0, 0.5);
    pass &= rel(agg.throughput, want) < 0.02;
    obs.push(format!("agg {:.2} vs {want:.2}", agg.throughput));
    for (np, bnet) in [(10, 1000.0), (11, 1000.0), (12, 1000.0), (11, 10.0)] {
        let cfg = pd_cfg(
            32,
            Mode::Disaggregated {
                prefill_devices: np,
            },
            1.0,
            1.0,
            0.5,
            (2.0, 1.0),
            bnet,
        );
        let r = pd::simulate(&cfg);
        let want = pd::split_capacity(&cfg, np);
        pass &= rel(r.throughput, want) < 0.02;
        obs.push(format!(
            "N_P={np} B/K={bnet}: {:.2} vs {want:.2}",
            r.throughput
        ));
    }
    Check {
        id: "pd_capacity_matches",
        paper: "prop:pd (iii), ex:pd",
        lean: &["pd_wins_example", "pd_loses_example"],
        kind: Kind::InModel,
        claim: "capacities N/(s_P+s_D+I) and min(N_P g_P/s_P, N_D g_D/s_D, B/E[K])",
        expected: "saturated throughput within 2% (N=32, s_P=s_D=1, I=0.5, g_P=2)".into(),
        observed: obs.join("; "),
        pass,
    }
}

/// Prop. pd (i)-(ii): without gains or interference no split beats
/// aggregation, and the rate-matched split ties.
pub fn pd_no_gain() -> Check {
    let (n, sp, sd) = (8, 1.0, 3.0);
    let agg = pd::simulate(&pd_cfg(
        n,
        Mode::Aggregated,
        sp,
        sd,
        0.0,
        (1.0, 1.0),
        f64::INFINITY,
    ))
    .throughput;
    let mut pass = rel(agg, agg_capacity(n as f64, sp, sd)) < 0.02;
    let mut obs = vec![format!("agg {agg:.3}")];
    for np in 1..n {
        let x = pd::simulate(&pd_cfg(
            n,
            Mode::Disaggregated {
                prefill_devices: np,
            },
            sp,
            sd,
            0.0,
            (1.0, 1.0),
            f64::INFINITY,
        ))
        .throughput;
        pass &= x <= agg * 1.01;
        if np == 2 {
            pass &= rel(x, agg) < 0.02;
        }
        obs.push(format!("N_P={np}: {x:.3}"));
    }
    Check {
        id: "pd_no_gain",
        paper: "prop:pd (i)-(ii)",
        lean: &[
            "pd_le_agg",
            "pd_eq_agg_at_rate_match",
            "rate_match_optimal",
            "pdCompute_eq_agg_of_no_gain",
        ],
        kind: Kind::InModel,
        claim: "μ_PD ≤ μ_A for every split, with equality at N_P = N s_P/(s_P+s_D)",
        expected: "every split ≤ agg (+1%); N_P=2 of 8 ties (s_P=1, s_D=3)".into(),
        observed: obs.join("; "),
        pass,
    }
}

/// Prop. pd (iii) as a decision: across a grid of (I, g_P, B/E[K]), does
/// the simulated winner (best integer split vs aggregation) match the
/// analytic win condition? Cells within 3% of the boundary are skipped.
pub fn pd_win_condition_decisions() -> Check {
    let n = 16;
    let mut agree = 0;
    let mut total = 0;
    let mut skipped = 0;
    let mut disagreements = vec![];
    for &i in &[0.0, 0.25, 0.5, 1.0] {
        for &gp in &[1.0, 1.5, 2.0] {
            for &bnet in &[5.0, 8.0, 1000.0] {
                let agg_a = agg_capacity_i(n as f64, 1.0, 1.0, i);
                let pd_a = pd_full_capacity(
                    n as f64,
                    1.0,
                    1.0,
                    gp,
                    1.0,
                    bnet,
                    1.0,
                    f64::INFINITY,
                    f64::INFINITY,
                );
                if rel(pd_a, agg_a) < 0.03 {
                    skipped += 1;
                    continue;
                }
                // The Lean capacity uses a real-valued split; the simulator
                // uses the best integer one, so compare against that.
                let best_np = (1..n)
                    .max_by(|&a, &b| {
                        let c = |np| {
                            pd::split_capacity(
                                &pd_cfg(
                                    n,
                                    Mode::Disaggregated {
                                        prefill_devices: np,
                                    },
                                    1.0,
                                    1.0,
                                    i,
                                    (gp, 1.0),
                                    bnet,
                                ),
                                np,
                            )
                        };
                        c(a).total_cmp(&c(b))
                    })
                    .expect("n > 1");
                let agg_s =
                    pd::simulate(&pd_cfg(n, Mode::Aggregated, 1.0, 1.0, i, (gp, 1.0), bnet))
                        .throughput;
                let pd_s = pd::simulate(&pd_cfg(
                    n,
                    Mode::Disaggregated {
                        prefill_devices: best_np,
                    },
                    1.0,
                    1.0,
                    i,
                    (gp, 1.0),
                    bnet,
                ))
                .throughput;
                total += 1;
                let analytic_pd_wins = agg_a < pd_a;
                if analytic_pd_wins == (agg_s < pd_s) {
                    agree += 1;
                } else {
                    disagreements.push(format!(
                        "I={i} g_P={gp} B/K={bnet}: sim agg {agg_s:.2} pd {pd_s:.2}"
                    ));
                }
            }
        }
    }
    Check {
        id: "pd_win_condition_decisions",
        paper: "prop:pd (iii)",
        lean: &["pd_beats_agg_iff"],
        kind: Kind::BeyondModel,
        claim: "PD beats aggregation iff each PD bottleneck exceeds N/(s_P+s_D+I)",
        expected:
            "simulated winner (best integer split) matches the condition in every decisive cell"
                .into(),
        observed: format!(
            "{agree}/{total} agree, {skipped} cells within 3% skipped{}",
            if disagreements.is_empty() {
                String::new()
            } else {
                format!("; disagree: {}", disagreements.join("; "))
            }
        ),
        pass: agree == total,
    }
}

// ---------------------------------------------------------------- §3.3 --

/// Prop. routing (ii): strict affinity is not optimal at high load.
pub fn affinity_breaks_at_high_load() -> Check {
    let rates = [0.6, 1.2, 1.6, 1.8];
    let aff: Vec<f64> = rates
        .iter()
        .map(|&r| {
            routing::simulate(&RoutingConfig::example(r, RoutePolicy::Affinity))
                .response
                .mean
        })
        .collect();
    let look = routing::simulate(&RoutingConfig::example(1.8, RoutePolicy::Lookahead));
    let pass = aff.windows(2).all(|w| w[1] > w[0]) && aff[3] > 10.0 * look.response.mean;
    Check {
        id: "affinity_breaks_at_high_load",
        paper: "prop:routing (ii)",
        lean: &["affinity_not_always_optimal", "mm1Wait_unbounded"],
        kind: Kind::BeyondModel,
        claim: "for any finite migration cost, some stable load makes affinity worse than moving",
        expected: "affinity response increasing in load; at the highest load > 10× lookahead"
            .into(),
        observed: format!(
            "affinity R: {}; lookahead at 1.8: {:.3}s ({} migrations)",
            rates
                .iter()
                .zip(&aff)
                .map(|(r, a)| format!("{r}/s→{a:.3}s"))
                .collect::<Vec<_>>()
                .join(", "),
            look.response.mean,
            look.migrations
        ),
        pass,
    }
}

/// Prop. routing (i): the lookahead rule, which contains "stay" as an
/// option, is not worse than affinity at any load.
pub fn lookahead_not_worse_than_affinity() -> Check {
    let mut pass = true;
    let mut obs = vec![];
    for r in [0.3, 0.9, 1.4] {
        let a = routing::simulate(&RoutingConfig::example(r, RoutePolicy::Affinity)).response;
        let l = routing::simulate(&RoutingConfig::example(r, RoutePolicy::Lookahead)).response;
        pass &= l.mean <= a.hi();
        obs.push(format!(
            "{r}/s: affinity {:.3} lookahead {:.3}",
            a.mean, l.mean
        ));
    }
    Check {
        id: "lookahead_not_worse_than_affinity",
        paper: "prop:routing (i)",
        lean: &["lookahead_prefers_iff"],
        kind: Kind::BeyondModel,
        claim: "the lookahead rule prefers staying iff (W1+S1)-(W2+S2) < M2 + (F2-F1)",
        expected: "lookahead mean response ≤ affinity upper CI at every load".into(),
        observed: obs.join("; "),
        pass,
    }
}

// ---------------------------------------------------------- observations -

/// A measured quantity with no asserted prediction.
#[derive(Clone, Debug)]
pub struct Observation {
    pub id: &'static str,
    pub paper: &'static str,
    pub question: &'static str,
    pub result: String,
}

/// Two-class mix: agents (p=0.95, short context) and one-shot long documents
/// (p=0.2, long context), on a 400k-token pool.
pub fn mixed_workload(n: usize, seed: u64, ev: EvictionPolicy) -> AgenticConfig {
    let mut cfg = AgenticConfig::example(n, 4.0e5);
    cfg.classes = vec![
        ProgramClass {
            weight: 1.0,
            resume_prob: 0.95,
            initial_tokens: Dist::Uniform {
                lo: 4_000.0,
                hi: 8_000.0,
            },
            new_tokens: Dist::exp(800.0),
            output_tokens: Dist::exp(300.0),
            tool_time: Dist::exp(3.0),
        },
        ProgramClass {
            weight: 1.0,
            resume_prob: 0.2,
            initial_tokens: Dist::Uniform {
                lo: 30_000.0,
                hi: 60_000.0,
            },
            new_tokens: Dist::exp(500.0),
            output_tokens: Dist::exp(300.0),
            tool_time: Dist::exp(3.0),
        },
    ];
    cfg.eviction = ev;
    cfg.seed = seed;
    cfg
}

/// Session arrival rates of the open-session eviction scenario on the
/// two-resource replica (see [`open_session_cfg`]); about 2.1 and 3.0
/// offered turns/s (10.7 turns per session). At the default cap of 24
/// live sessions the first is the onset of eviction (follow-up hit rate
/// about 0.95) and the second is deep inside the eviction window (about
/// 0.75); at 32 live sessions seeds start to thrash at the first and most
/// have thrashed at the second, at 16 neither load evicts much. Below
/// about 0.12 there are no evictions and the policies coincide.
pub const OPEN_RATES: [f64; 2] = [0.20, 0.28];
pub const OPEN_SEEDS: u64 = 20;
/// Default cap on live sessions of the scenario.
pub const OPEN_CAP: usize = 24;
/// Admission caps of the sweep (the default is one of them).
pub const OPEN_CAPS: [usize; 3] = [16, 24, 32];
/// All policies, run at the default cap.
pub const OPEN_POLICIES: [EvictionPolicy; 6] = [
    EvictionPolicy::ShortestFirst,
    EvictionPolicy::Density,
    EvictionPolicy::Priced,
    EvictionPolicy::PricedMemory,
    EvictionPolicy::PricedMemoryBlocks,
    EvictionPolicy::Lru,
];
/// Policies run at the other caps of the sweep.
pub const SWEEP_POLICIES: [EvictionPolicy; 3] = [
    EvictionPolicy::ShortestFirst,
    EvictionPolicy::Density,
    EvictionPolicy::PricedMemory,
];

/// Cost model of the open-session scenario: the example costs with a
/// KV-dependent decode term, `β = 2·10⁻⁹` s per output token per context
/// token (the KV of a 100k-token context takes as long to read as the
/// weights).
pub fn open_session_cost() -> CostModel {
    let mut cost = AgenticConfig::example(0, 1.0e6).cost;
    cost.decode_kv = 2.0e-9;
    cost
}

/// Open sessions on one two-resource replica with finite KV. Two classes
/// with equal arrival weight: agents (`p = 0.95`, 4–8k initial tokens, 800
/// new and 300 output per turn, tool calls Exp(6 s)) and one-shot documents
/// (`p = 0.3`, 15–30k tokens, 500 new, think time Exp(2 s)). The tool times
/// differ so that the byte-second price (`PricedMemory`) and the per-token
/// price (`Density`, `Priced`) can order the two classes differently.
/// 600k-token KV pool, batch cap 8 (prefilling and decoding turns), at most
/// `cap` live sessions (the rest wait to enter), 512-token blocks.
pub fn open_session_cfg(rate: f64, cap: usize, ev: EvictionPolicy, seed: u64) -> BatchConfig {
    let kv = 6.0e5;
    BatchConfig {
        population: Population::Open { rate },
        max_sessions: Some(cap),
        classes: vec![
            ProgramClass {
                weight: 1.0,
                resume_prob: 0.95,
                initial_tokens: Dist::Uniform {
                    lo: 4_000.0,
                    hi: 8_000.0,
                },
                new_tokens: Dist::exp(800.0),
                output_tokens: Dist::exp(300.0),
                tool_time: Dist::exp(6.0),
            },
            ProgramClass {
                weight: 1.0,
                resume_prob: 0.3,
                initial_tokens: Dist::Uniform {
                    lo: 15_000.0,
                    hi: 30_000.0,
                },
                new_tokens: Dist::exp(500.0),
                output_tokens: Dist::exp(300.0),
                tool_time: Dist::exp(2.0),
            },
        ],
        cost: open_session_cost(),
        work: Work::Tokens,
        server: Server::TwoStage,
        batch_cap: Some(8),
        kv_capacity: kv,
        max_context: 0.5 * kv,
        eviction: ev,
        block_tokens: 512.0,
        step_time: None,
        warmup: 1_000.0,
        horizon: 21_000.0,
        seed,
    }
}

/// One (cap, load, policy) cell over [`OPEN_SEEDS`] seeds.
#[derive(Clone, Debug)]
pub struct OpenEvictRow {
    pub cap: usize,
    pub rate: f64,
    pub policy: EvictionPolicy,
    pub throughput: Estimate,
    pub hit_rate: Estimate,
    /// Mean and p99 time to first token (prefill wait + prefill).
    pub ttft: Estimate,
    pub ttft_p99: Estimate,
    /// Mean and p99 turn response.
    pub response: Estimate,
    pub p99: Estimate,
    pub availability: Estimate,
    /// Mean wait of a new session in the entry queue (the cost of the cap).
    pub entry_wait: Estimate,
    /// Seeds whose follow-up hit rate fell below 0.5 (thrashing).
    pub collapsed: usize,
}

pub fn open_row(cap: usize, rate: f64, policy: EvictionPolicy) -> OpenEvictRow {
    let rs: Vec<BatchReport> = (1..=OPEN_SEEDS)
        .map(|s| batch::simulate(&open_session_cfg(rate, cap, policy, s)))
        .collect();
    let est = |f: fn(&BatchReport) -> f64| replications(&rs.iter().map(f).collect::<Vec<_>>());
    OpenEvictRow {
        cap,
        rate,
        policy,
        throughput: est(|r| r.throughput),
        hit_rate: est(|r| r.hit_rate),
        ttft: est(|r| r.ttft.mean()),
        ttft_p99: est(|r| r.ttft_p99),
        response: est(|r| r.response.mean()),
        p99: est(|r| r.p99),
        availability: est(|r| r.mean_availability),
        entry_wait: est(|r| r.entry_wait.mean()),
        collapsed: rs.iter().filter(|r| r.hit_rate < 0.5).count(),
    }
}

/// Every cell of the open-session scenario: all policies at the default
/// cap, [`SWEEP_POLICIES`] at the other caps, both loads. Cells run on
/// threads; the result is deterministic.
pub fn eviction_open_scenario() -> Vec<OpenEvictRow> {
    let mut cells = vec![];
    for cap in OPEN_CAPS {
        let pols: &[EvictionPolicy] = if cap == OPEN_CAP {
            &OPEN_POLICIES
        } else {
            &SWEEP_POLICIES
        };
        for rate in OPEN_RATES {
            for &policy in pols {
                cells.push((cap, rate, policy));
            }
        }
    }
    std::thread::scope(|s| {
        let handles: Vec<_> = cells
            .iter()
            .map(|&(cap, rate, policy)| s.spawn(move || open_row(cap, rate, policy)))
            .collect();
        handles
            .into_iter()
            .map(|h| h.join().expect("simulation thread"))
            .collect()
    })
}

/// Results that bear on the paper's open questions (§7) but test no
/// proposition.
pub fn observations() -> Vec<Observation> {
    let mut out = vec![];

    // E4: does the offline density advantage survive in a dynamic system?
    let mut lines = vec![];
    for n in [16, 24, 32] {
        let mut cells = vec![];
        for ev in [
            EvictionPolicy::ShortestFirst,
            EvictionPolicy::Density,
            EvictionPolicy::Priced,
            EvictionPolicy::Lru,
        ] {
            let xs: Vec<f64> = (1..=5)
                .map(|s| agentic::simulate(&mixed_workload(n, s, ev)).throughput)
                .collect();
            cells.push(format!("{ev:?} {}", replications(&xs)));
        }
        lines.push(format!("N={n}: {}", cells.join(", ")));
    }
    out.push(Observation {
        id: "dynamic_eviction",
        paper: "prop:blind, sec:exp-evict",
        question: "Offline, the density rule beats SF by a wide margin when p_i vary. Does that, or the congestion-priced order q_i Φ_i / c_i, carry over to a closed system where evictions repeat and freed memory is reused? (Two classes: agent p=0.95 short context; one-shot p=0.2 long context. Throughput turns/s, 5 seeds.)",
        result: lines.join("; "),
    });

    // Eviction with open sessions on the two-resource replica, with an
    // admission-cap sweep.
    let lines: Vec<String> = eviction_open_scenario()
        .iter()
        .map(|r| {
            format!(
                "cap={} Λ={} {:?}: X {} hit {} TTFT {} p99 {} R {} p99 {} avail {} entry wait {} ({} of {OPEN_SEEDS} seeds thrash)",
                r.cap,
                r.rate,
                r.policy,
                r.throughput,
                r.hit_rate,
                r.ttft,
                r.ttft_p99,
                r.response,
                r.p99,
                r.availability,
                r.entry_wait,
                r.collapsed
            )
        })
        .collect();
    out.push(Observation {
        id: "eviction_open_sessions",
        paper: "prop:price, prop:decode, prop:memory, sec:exp-evict",
        question: "On the two-resource replica misses are paid in the prefill FIFO (Prop. price) while decode is insensitive (Prop. decode), and the memory shadow price is per byte-second (Prop. memory). With open sessions, a session cap, finite KV and a batch cap, how do SF, Density, Priced, PricedMemory, block-level PricedMemory and LRU compare in throughput, hit rate, TTFT and turn response, and does the admission cap move the thrash window? (Turns/s and seconds, mean ± 95% half-width over seeds.)",
        result: lines.join("; "),
    });

    // Chain check: PK from measured moments vs measured wait, open system.
    let mut lines = vec![];
    for rate in [0.05, 0.08] {
        for ev in [EvictionPolicy::ShortestFirst, EvictionPolicy::Density] {
            let mut cfg = mixed_workload(0, 1, ev);
            cfg.population = Population::Open { rate };
            cfg.kv_capacity = 2.5e5;
            cfg.max_context = 1.25e5;
            cfg.horizon = 40_500.0;
            let r = agentic::simulate(&cfg);
            lines.push(format!(
                "{rate}/s {ev:?}: hit {:.3} ρ {:.2} CV² {:.1} Wq {} PK {:.3}",
                r.hit_rate,
                r.utilization,
                r.service.cv2(),
                r.wait,
                r.pk_wait_prediction()
            ));
        }
    }
    out.push(Observation {
        id: "pk_on_agentic_turns",
        paper: "sec:congestion, sec:limits",
        question: "Turn arrivals of agent programs are not Poisson and hits are correlated with memory state. How far is PK (fed the measured λ and service moments) from the simulated wait?",
        result: lines.join("; "),
    });

    // Tandem vs pooled latency at equal capacity.
    let mut lines = vec![];
    for rate in [1.0, 1.6, 1.9] {
        let mut a = PdConfig::from_means(
            8,
            Mode::Aggregated,
            Load::Poisson { rate },
            1.0,
            3.0,
            0.0,
            (1.0, 1.0),
            f64::INFINITY,
            1.0,
        );
        a.requests = 100_000;
        a.warmup = 10_000;
        let mut d = a.clone();
        d.mode = Mode::Disaggregated { prefill_devices: 2 };
        let (ra, rd) = (pd::simulate(&a), pd::simulate(&d));
        lines.push(format!("λ={rate}: agg {} vs PD {}", ra.latency, rd.latency));
    }
    out.push(Observation {
        id: "pd_latency_at_equal_capacity",
        paper: "prop:pd (ii)",
        question: "At the rate-matched split PD and aggregation have equal capacity (N=8, s_P=1, s_D=3, capacity 2/s). Do they have equal latency?",
        result: lines.join("; "),
    });

    out
}
