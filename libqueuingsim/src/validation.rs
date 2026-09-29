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

use crate::Dist;
use crate::analytic::*;
use crate::models::agentic::{
    self, AgenticConfig, EvictionPolicy, FetchMode, OffloadPolicy, Population, ProgramClass,
};
use crate::models::batch::{self, BatchConfig, BatchReport, Phi, Server, ps_mean_number};
use crate::models::eviction::{self, Item, ResumeModel};
use crate::models::pd::{self, Load, Mode, PdConfig};
use crate::models::queue::{self, QueueConfig};
use crate::models::routing::{self, RoutePolicy, RoutingConfig};
use crate::stats::{Estimate, Welford, batch_means, replications};
use crate::workload::TraceCorpusExt;
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
        prefill_pays_the_miss(),
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
        trace_replay_variance_sources(),
        inversion_load_closed_form(),
        inversion_load_rises_with_move_cost(),
        finite_source_wait_below_open(),
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

/// Props. price and decode on a replica with the vLLM v1 engine's rules
/// (`seq_price`, the seQ program `programs/price_vllm.seq`): forcing a
/// fraction `δ` of turns to miss raises the number in the *prefill* stage
/// by an amount bracketed by the M/G/1 price at the stage's effective
/// service `P/r̄`, and changes the number in the *decode* stage, whose
/// demand does not depend on hit or miss, by less than 1 % (it is not
/// exactly zero there: a miss's prefill lengthens the iterations the
/// decoding turns share). Beyond the model: the prefill rate fluctuates
/// with the decode batch and the engine works in iterations.
pub fn prefill_pays_the_miss() -> Check {
    let mut pass = true;
    let mut obs = vec![];
    let mut head = String::new();
    for delta in [0.01, 0.05] {
        let m = crate::seq_price::price_scenario(delta);
        if head.is_empty() {
            head = format!(
                "r̄={:.3}, ρ_P={:.3}, L_P {} vs M/G/1 {:.3}, L_D {}",
                m.avail, m.rho_p, m.l_p, m.l_p_theory, m.l_d
            );
        }
        // Prefill: the CI of ΔL_P must overlap the bracket (5% slack for
        // the fluctuating rate). Decode: |ΔL_D| below 1% of L_D.
        pass &= m.dl_p.lo() <= 1.05 * m.hi && m.dl_p.hi() >= 0.95 * m.lo;
        pass &= m.dl_d.mean.abs() <= 0.01 * m.l_d.mean;
        obs.push(format!(
            "δ={delta}: ΔL_P {} vs [{:.4}, {:.4}], ΔL_D {} ({:.2}% of L_D)",
            m.dl_p,
            m.lo,
            m.hi,
            m.dl_d,
            100.0 * m.dl_d.mean / m.l_d.mean
        ));
    }
    Check {
        id: "prefill_pays_the_miss",
        paper: "prop:price, prop:decode",
        lean: &["missPrice_lower", "missPrice_upper", "stationaryMean"],
        kind: Kind::BeyondModel,
        claim: "on a replica with vLLM's engine rules the price of a miss is paid in the prefill queue (FIFO bracket at the stage's effective service) and hardly in the decode batch",
        expected: "vLLM rules, testbed cost, hit/miss prefill 512/5120 tokens, λE[P]=0.6: 95% CI of λΔTTFT overlaps [λδΦ, (1-ρ)/(1-ρ')λδΦ] (5% slack) at service P/r̄; |λΔ(R-TTFT)| below 1% of λE[R-TTFT]".into(),
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

pub const OPEN_SEEDS: u64 = 20;
/// Default cap on live sessions of the scenario.
pub const OPEN_CAP: usize = 24;
/// Admission caps of the sweep (the default is one of them).
pub const OPEN_CAPS: [usize; 3] = [16, 24, 32];
/// One (cap, load, policy) cell over [`OPEN_SEEDS`] seeds.
#[derive(Clone, Debug)]
pub struct OpenEvictRow {
    pub cap: usize,
    pub rate: f64,
    pub policy: EvictionPolicy,
    /// Whether the scheduler knows that a session ended (its KV is then
    /// dropped); libqueuingsim always drops it.
    pub end_known: bool,
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

// ------------------------------------------------ §4.1 trace replay ----

/// Session arrival rates (per s) of the trace-replay scenario.
/// With the calibrated cost model the open replica runs at ρ ≈ 0.3 and 0.55.
pub const TRACE_RATES: [f64; 2] = [0.0005, 0.001];
/// KV pools (tokens) of the trace-replay scenario; `INFINITY` = no eviction.
/// Sized against the corpus (mean final context 3.9·10^5 tokens): the pools
/// hold about ten, five and two or three finished sessions.
pub const TRACE_POOLS: [f64; 4] = [f64::INFINITY, 4.0e6, 2.0e6, 1.0e6];

/// Cost model of the trace-replay scenario, calibrated on the NPU testbed
/// (paper §4.3): the prefill terms are the E1 least-squares fit
/// (`data/exp/e1/fit.json`, `scripts/exp/fit_e1.py`; `scripts/check_sim.sh`
/// checks these constants against that file) and the decode iteration time
/// is the mean inter-token latency of the lightest E2 replay (cap 8; it rose
/// to 0.12 s with the batch under the loose caps) and did not vary with the
/// context over 30k–90k tokens, so `β = 0`.
pub const CAL_PREFILL_LINEAR: f64 = 1.94e-4; // a, s per new token
pub const CAL_PREFILL_QUADRATIC: f64 = 6.51e-9; // b, s per token², K_c = a/b ≈ 30k
pub const CAL_PREFILL_OVERHEAD: f64 = 0.044; // c0, s per request
pub const CAL_DECODE_STEP: f64 = 0.057; // ω, s per decode iteration (E2 ITL at cap 8)
pub const TRACE_SEEDS: u64 = 5;
/// Warm-up and horizon (s) of every replay run.
pub const TRACE_WARMUP: f64 = 6_000.0;
pub const TRACE_HORIZON: f64 = 66_000.0;

/// One (rate, pool) cell of the trace-replay scenario over [`TRACE_SEEDS`]
/// seeds. Follow-up turns only for the variance split; all turns for the
/// prefill queue.
#[derive(Clone, Debug)]
pub struct TraceRow {
    pub rate: f64,
    pub kv: f64,
    pub cap: usize,
    pub policy: EvictionPolicy,
    pub hit_rate: Estimate,
    /// Mean share of a follow-up turn's reusable prefix that it reused (the
    /// hit rate under whole-session eviction; higher under block eviction,
    /// where a miss can be partial).
    pub reused: Estimate,
    /// Mean live sessions and mean entry-queue wait of admitted sessions.
    pub sessions: Estimate,
    pub entry_wait: Estimate,
    /// Prefill load of the queue in stage time, `λ E[S]/availability`.
    pub rho: Estimate,
    /// `CV²` of the prefill work of follow-up turns.
    pub cv2: Estimate,
    /// Share of `Var[S]` (follow-up prefill work) from the hit/miss mixture,
    /// by the law of total variance; the rest is the spread of the appends
    /// and contexts within hits and within misses.
    pub mixture_share: Estimate,
    /// Mean prefill-queue wait (ready → prefill start), observed, and the
    /// PK prediction from the measured `λ`, `E[S]`, `E[S²]` in stage time.
    pub wait: Estimate,
    pub pk_wait: Estimate,
    pub ttft: Estimate,
    pub ttft_p99: Estimate,
    pub prefill_number: Estimate,
    pub availability: Estimate,
    pub truncated: Estimate,
    /// Turns completed per second.
    pub throughput: Estimate,
}

/// Admission caps of the scenario as multiples of `pool / mean final
/// context` (the number of finished sessions the pool holds): tight and
/// loose. With an infinite pool the cap is [`TRACE_CAP_OPEN`].
pub const TRACE_CAP_FACTORS: [f64; 2] = [0.8, 1.6];
pub const TRACE_CAP_OPEN: usize = 24;

/// Live-session cap for a pool: `factor · pool / mean final context`, at
/// least 1; [`TRACE_CAP_OPEN`] for an infinite pool.
pub fn trace_cap(corpus: &crate::workload::TraceCorpus, kv: f64, factor: f64) -> usize {
    if kv.is_finite() {
        ((factor * kv / corpus.mean_final_context()).floor() as usize).max(1)
    } else {
        TRACE_CAP_OPEN
    }
}

/// §2.3 / E2 on a real workload, the replay of §4.2 on the vLLM-rule
/// replica (`seq_replay`): with no eviction the prefill-work variance of
/// follow-up turns comes from the appends alone (mixture share 0); with a
/// finite pool and a tight admission cap the hit/miss mixture supplies a
/// share of `Var[S]` (small under block eviction, where a miss is often
/// partial; it was above 0.3 under libqueuingsim's whole-session eviction);
/// and the PK wait computed from the measured moments is an upper bound on
/// the observed prefill wait in every cell (the live sessions are a finite
/// population, so arrivals are self-limiting and the open M/G/1 queue
/// overstates the wait).
pub fn trace_replay_variance_sources() -> Check {
    let corpus = std::sync::Arc::new(crate::workload::TraceCorpus::weka());
    // The higher rate, as in the table: at the lower one the cap of the
    // largest pool never binds and there is no eviction to measure.
    let rate = TRACE_RATES[TRACE_RATES.len() - 1];
    let rows: Vec<TraceRow> = TRACE_POOLS
        .iter()
        .map(|&kv| {
            crate::seq_replay::trace_row(rate, kv, trace_cap(&corpus, kv, TRACE_CAP_FACTORS[0]))
        })
        .collect();
    let open_has_no_mixture = rows[0].mixture_share.mean < 1e-9 && rows[0].hit_rate.mean > 0.999;
    let finite_has_mixture = rows[1..].iter().all(|r| r.mixture_share.mean > 0.0);
    let pk_upper = rows.iter().all(|r| r.pk_wait.mean >= r.wait.mean);
    Check {
        id: "trace_replay_variance_sources",
        paper: "sec:congestion, sec:exp-variance, sec:limits",
        lean: &["pkWait_mixture_antitone", "mixtureCV2_agentic_example"],
        kind: Kind::BeyondModel,
        claim: "on replayed production sessions (vLLM engine rules), prefill-work variance has two sources: the appends (all of it with no eviction) and the hit/miss mixture (a share once the pool is finite, small under block eviction); PK from measured moments is an upper bound on the prefill wait of a finite live population",
        expected: "mixture share 0 with an infinite pool and > 0 for every finite pool at the tight cap; PK ≥ observed wait in every cell".into(),
        observed: rows
            .iter()
            .map(|r| {
                format!(
                    "pool {} cap {}: hit {:.3} ρ {:.2} CV² {:.1} mix {:.2} Wq {:.1}s PK {:.1}s TTFT {:.1}s",
                    if r.kv.is_finite() { format!("{:.1e}", r.kv) } else { "∞".into() },
                    r.cap,
                    r.hit_rate.mean,
                    r.rho.mean,
                    r.cv2.mean,
                    r.mixture_share.mean,
                    r.wait.mean,
                    r.pk_wait.mean,
                    r.ttft.mean
                )
            })
            .collect::<Vec<_>>()
            .join("; "),
        pass: open_has_no_mixture && finite_has_mixture && pk_upper,
    }
}

// ------------------------------------------- §3.2 inversion load ----

/// Migration-link bandwidths (tokens/s) of the inversion-load scenario,
/// from a shared KV store that moves a context in a few milliseconds to a
/// slow link that takes longer than a recompute.
pub const INVERSION_BANDWIDTHS: [f64; 4] = [2.0e7, 2.0e6, 5.0e5, 1.25e5];
/// Program arrival rates (per s) swept for the inversion.
pub const INVERSION_RATES: [f64; 19] = [
    0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0,
];

/// One link bandwidth of the inversion-load scenario.
#[derive(Clone, Debug)]
pub struct InversionRow {
    pub bandwidth: f64,
    /// Mean move cost over mean service, `M̄/E[S]`, with `M̄` the mean of
    /// the cheaper of fetch and recompute over the follow-up contexts.
    pub move_over_service: f64,
    /// `ρ* = x/(1+x)` with `x = M̄/E[S]` and `F = 0`: Prop. routing (i) for
    /// one M/M/1 node and an idle alternative.
    pub rho_star: f64,
    /// Lowest swept program rate at which always moving to the least
    /// loaded replica (fetching the state) beats affinity in mean response
    /// by more than both half-widths.
    pub inversion_rate: Option<f64>,
    /// Utilisation of the hot replica under affinity at that rate.
    pub hot_utilization: Option<f64>,
    /// Utilisation of the shared link under always-move at that rate.
    pub link_utilization: Option<f64>,
    pub affinity_response: Option<f64>,
    pub move_response: Option<f64>,
    /// Lookahead (state-dependent) mean response at that rate.
    pub lookahead_response: Option<f64>,
}

/// For each bandwidth, sweep the rate and find the inversion of affinity
/// against always-move; the move cost is measured on the affinity run.
pub fn inversion_scenario() -> Vec<InversionRow> {
    let aff: Vec<routing::RoutingReport> = INVERSION_RATES
        .iter()
        .map(|&r| routing::simulate(&RoutingConfig::example(r, RoutePolicy::Affinity)))
        .collect();
    let cost = RoutingConfig::example(1.0, RoutePolicy::Affinity).cost;
    INVERSION_BANDWIDTHS
        .iter()
        .map(|&bw| {
            let mut found = None;
            for (i, &r) in INVERSION_RATES.iter().enumerate() {
                let mut cfg = RoutingConfig::example(r, RoutePolicy::LeastLoadedFetch);
                cfg.migrate_bandwidth = bw;
                let mv = routing::simulate(&cfg);
                let a = &aff[i];
                if mv.response.mean + mv.response.half_width
                    < a.response.mean - a.response.half_width
                {
                    let mut lcfg = RoutingConfig::example(r, RoutePolicy::Lookahead);
                    lcfg.migrate_bandwidth = bw;
                    let look = routing::simulate(&lcfg);
                    found = Some((i, mv, look));
                    break;
                }
            }
            let i = found.as_ref().map_or(INVERSION_RATES.len() - 1, |f| f.0);
            let a = &aff[i];
            let c = a.mean_context;
            let m = (c / bw).min(cost.miss_penalty(c));
            let x = m / a.service.mean();
            InversionRow {
                bandwidth: bw,
                move_over_service: x,
                rho_star: x / (1.0 + x),
                inversion_rate: found.as_ref().map(|_| INVERSION_RATES[i]),
                hot_utilization: found.as_ref().map(|_| a.utilization[0]),
                link_utilization: found.as_ref().map(|f| f.1.link_utilization),
                affinity_response: found.as_ref().map(|_| a.response.mean),
                move_response: found.as_ref().map(|f| f.1.response.mean),
                lookahead_response: found.as_ref().map(|f| f.2.response.mean),
            }
        })
        .collect()
}

/// Prop. routing (ii) beyond its model (4 replicas, skewed placement, a
/// shared link): the load at which always moving (fetching the state) beats
/// strict affinity exists for every finite move cost and never falls as the
/// link slows.
pub fn inversion_load_rises_with_move_cost() -> Check {
    let rows = inversion_scenario();
    let all_found = rows.iter().all(|r| r.inversion_rate.is_some());
    let monotone = rows.windows(2).all(|w| {
        w[0].inversion_rate.unwrap_or(f64::INFINITY) <= w[1].inversion_rate.unwrap_or(f64::INFINITY)
    });
    Check {
        id: "inversion_load_rises_with_move_cost",
        paper: "prop:routing (ii)",
        lean: &["inversionLoad_mono", "affinity_loses_iff"],
        kind: Kind::BeyondModel,
        claim: "a cheaper move lowers the load at which always moving beats strict affinity; every finite move cost has such a load",
        expected: "an inversion rate for every bandwidth, nondecreasing as the link slows; hot-replica utilisation at the inversion near ρ*".into(),
        observed: rows
            .iter()
            .map(|r| {
                format!(
                    "B={:.2e}: M̄/E[S] {:.2} ρ* {:.2} inversion at {} (hot util {})",
                    r.bandwidth,
                    r.move_over_service,
                    r.rho_star,
                    r.inversion_rate
                        .map_or("none".into(), |x| format!("{x:.1}/s")),
                    r.hot_utilization.map_or("-".into(), |u| format!("{u:.2}"))
                )
            })
            .collect::<Vec<_>>()
            .join("; "),
        pass: all_found && monotone,
    }
}

/// Prop. routing (i) in its model: an M/M/1 affinity node with `μ = 10`
/// against an idle node plus a move cost `M + F = x/μ`. The simulated mean
/// response is below the move cost `(1+x)/μ` at utilisation `ρ* − 0.05` and
/// above it at `ρ* + 0.05`, with `ρ* = x/(1+x)`.
pub fn inversion_load_closed_form() -> Check {
    let mu = 10.0;
    let mut obs = vec![];
    let mut pass = true;
    for (i, x) in [0.25, 1.0, 4.0].into_iter().enumerate() {
        let rho_star = x / (1.0 + x);
        let threshold = (1.0 + x) / mu;
        let mut side = vec![];
        for (k, d) in [-0.05, 0.05].into_iter().enumerate() {
            let lam = (rho_star + d) * mu;
            let r = queue::simulate(&QueueConfig::mg1(
                lam,
                Dist::exp(1.0 / mu),
                2_000_000,
                40 + 2 * i as u64 + k as u64,
            ));
            let ok = if d < 0.0 {
                r.sojourn.hi() < threshold
            } else {
                r.sojourn.lo() > threshold
            };
            pass &= ok;
            side.push(format!(
                "ρ={:.2}: W {} {} {threshold:.3}",
                rho_star + d,
                r.sojourn,
                if d < 0.0 { "<" } else { ">" }
            ));
        }
        obs.push(format!("x={x} (ρ*={rho_star:.2}): {}", side.join(", ")));
    }
    Check {
        id: "inversion_load_closed_form",
        paper: "prop:routing (i)",
        lean: &["affinity_loses_iff", "inversionLoad_utilization", "inversionLoad_stable"],
        kind: Kind::InModel,
        claim: "affinity's M/M/1 response exceeds the cost of moving to an idle node iff ρ > ρ* = μ(M+F)/(1+μ(M+F))",
        expected: "W below (1+x)/μ at ρ*−0.05 and above it at ρ*+0.05 for x = M+F over service ∈ {0.25, 1, 4}".into(),
        observed: obs.join("; "),
        pass,
    }
}

/// Forced-miss shares of the replayed price scenario.
pub const TRACE_PRICE_DELTAS: [f64; 3] = [0.01, 0.03, 0.1];

#[derive(Clone, Debug)]
pub struct TracePriceRow {
    pub rate: f64,
    pub delta: f64,
    /// Baseline prefill load and mean live sessions.
    pub rho: f64,
    pub live: f64,
    /// Forced run: prefill load `ρ'` implied by the added work, mean live
    /// sessions, baseline `L_P`.
    pub rho1: f64,
    pub live1: f64,
    pub l_p: f64,
    pub dl_p: Estimate,
    pub lo: f64,
    pub hi: f64,
    /// Exact M/M/1//N price of the added mean work (`finite_source_price`)
    /// with `N` the baseline's mean live count rounded, `Z` the corpus mean
    /// think time and the baseline's mean prefill service in stage time.
    pub finite: f64,
    pub hit_rate: f64,
}

// --------------------------------------------- finite-source prefill queue ----

/// Live-session counts of the finite-source scenario.
pub const FINITE_SOURCE_NS: [usize; 5] = [2, 4, 8, 16, 64];
/// Server utilisation held fixed across `N` by choosing the think time.
pub const FINITE_SOURCE_RHO: f64 = 0.6;

/// One `N` of the finite-source scenario: `N` sessions, exponential think
/// time chosen so that the server utilisation is [`FINITE_SOURCE_RHO`],
/// exponential service of mean 1 s at one FIFO server.
#[derive(Clone, Debug)]
pub struct FiniteSourceRow {
    pub n: usize,
    pub think: f64,
    pub rho: f64,
    /// Exact M/M/1//N mean wait in queue.
    pub wait_exact: f64,
    /// Simulated mean wait in queue with its batch-means CI.
    pub wait_sim: Estimate,
    /// Open M/M/1 wait at the same throughput, `ρ/(μ(1-ρ))`, i.e. the PK
    /// formula fed the measured arrival rate and service moments.
    pub wait_open: f64,
}

pub fn finite_source_scenario() -> Vec<FiniteSourceRow> {
    let mu = 1.0;
    FINITE_SOURCE_NS
        .iter()
        .map(|&n| {
            let nu = finite_source_nu_for_utilization(n, mu, FINITE_SOURCE_RHO);
            let (_, x, wq) = finite_source_mm1(n, nu, mu);
            let mut cfg = BatchConfig::poisson_turns(
                1.0,
                Dist::exp(1.0 / mu),
                Server::Fifo,
                400_000.0,
                300 + n as u64,
            );
            cfg.population = Population::Closed { programs: n };
            cfg.classes[0].resume_prob = 1.0;
            cfg.classes[0].tool_time = Dist::exp(1.0 / nu);
            cfg.max_context = f64::INFINITY;
            let r = batch::simulate(&cfg);
            let rho = x / mu;
            FiniteSourceRow {
                n,
                think: 1.0 / nu,
                rho,
                wait_exact: wq,
                wait_sim: batch_means(
                    &r.responses.iter().map(|(_, t)| t - 0.0).collect::<Vec<_>>(),
                    20,
                ),
                wait_open: rho / (mu * (1.0 - rho)),
            }
        })
        .collect()
}

/// The prefill queue of a replica with `N` live sessions is a finite-source
/// system. In model (M/M/1//N, Kleinrock §3.8) the simulated wait matches
/// the exact formula, and the open M/M/1 wait at the same utilisation is
/// above it for every `N`, with the gap closing as `N` grows: the open
/// price of Prop. price is an upper bound for a finite live population.
pub fn finite_source_wait_below_open() -> Check {
    let rows = finite_source_scenario();
    let mut pass = true;
    let mut obs = vec![];
    let mut prev_ratio = f64::INFINITY;
    for r in &rows {
        // simulated response = wait + service; compare response to exact
        let resp_exact = r.wait_exact + 1.0;
        pass &= r.wait_sim.agrees_with(resp_exact, 0.02);
        let ratio = r.wait_open / r.wait_exact;
        pass &= ratio >= 1.0 && ratio <= prev_ratio + 1e-9;
        prev_ratio = ratio;
        obs.push(format!(
            "N={}: Z={:.1}s ρ={:.2} R sim {} exact {:.3}; W_q exact {:.3} open {:.3} (×{:.2})",
            r.n, r.think, r.rho, r.wait_sim, resp_exact, r.wait_exact, r.wait_open, ratio
        ));
    }
    Check {
        id: "finite_source_wait_below_open",
        paper: "sec:batch, prop:price, sec:limits",
        lean: &["missPrice_upper"],
        kind: Kind::InModel,
        claim: "with N live sessions the prefill queue is a finite-source system; the open M/G/1 wait at the same utilisation is an upper bound that tightens as N grows",
        expected: format!(
            "simulated response within CI (+2%) of the exact M/M/1//N value; open/exact wait ratio ≥ 1 and nonincreasing in N at ρ = {FINITE_SOURCE_RHO}"
        ),
        observed: obs.join("; "),
        pass,
    }
}
