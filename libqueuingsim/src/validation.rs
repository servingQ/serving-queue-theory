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
    self, AgenticConfig, EvictionPolicy, FetchMode, OffloadPolicy, Population, ProgramClass,
};
use crate::models::eviction::{self, Item, ResumeModel};
use crate::models::pd::{self, Load, Mode, PdConfig};
use crate::models::queue::{self, QueueConfig};
use crate::models::routing::{self, RoutePolicy, RoutingConfig};
use crate::stats::replications;

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

// ---------------------------------------------------------------- §3 ----

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
        paper: "thm:pk, prop:pk",
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

/// Thm. kingman and §7 Limitations: bursty arrivals add delay beyond PK.
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
        paper: "thm:kingman, sec:limits",
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
        paper: "thm:little",
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

// ---------------------------------------------------------- §2.3 / §3 ---

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
        paper: "thm:irtl",
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

// ---------------------------------------------------------------- §3.2 --

/// Prop. evict (i).
pub fn shortest_first_counterexample() -> Check {
    let it: Vec<Item> = [4, 5, 6].iter().map(|&c| Item::uniform(c)).collect();
    let sf = eviction::subset_cost(&it, &eviction::shortest_first(&it, 6));
    let (opt, _) = eviction::optimal(&it, 6).expect("feasible");
    Check {
        id: "shortest_first_counterexample",
        paper: "prop:evict (i)",
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
        paper: "prop:evict (ii)",
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
        paper: "prop:evict (ii)",
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
        paper: "prop:evict (iii), thm:dantzig",
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

// ------------------------------------------------------------------ §5 --

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
        paper: "prop:evict, sec:exp-evict",
        question: "Offline, the density rule beats SF by a wide margin when p_i vary. Does that carry over to a closed system where evictions repeat and freed memory is reused? (Two classes: agent p=0.95 short context; one-shot p=0.2 long context. Throughput turns/s, 5 seeds.)",
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
