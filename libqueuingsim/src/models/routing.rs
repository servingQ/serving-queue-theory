//! Routing follow-up turns across replicas (paper §3.3, Prop. routing).
//!
//! The executable deployment is `programs/routing.seq` in seQ. This module
//! keeps the Rust configuration and report types used by the paper tables,
//! then delegates simulation to the shared seQ interpreter.

use crate::Dist;
use crate::models::agentic::{CostModel, ProgramClass};
use crate::stats::{Estimate, Welford};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RoutePolicy {
    /// Always the replica holding the KV (session affinity, `M = ∞`).
    Affinity,
    /// Least unfinished work, ignoring where the KV is.
    LeastLoaded,
    /// Least unfinished work; off-home the state is fetched over the link
    /// when that is cheaper than recomputing it.
    LeastLoadedFetch,
    /// KV-aware myopic: `min_j W_j + S_j`, with `S_j` a miss off-home.
    Myopic,
    /// `min_j W_j + S_j + M_j + F_j` with `F_j = 0`.
    Lookahead,
}

impl RoutePolicy {
    fn code(self) -> u8 {
        match self {
            Self::Affinity => 0,
            Self::LeastLoaded => 1,
            Self::LeastLoadedFetch => 2,
            Self::Myopic => 3,
            Self::Lookahead => 4,
        }
    }
}

#[derive(Clone, Debug)]
pub struct RoutingConfig {
    pub replicas: usize,
    /// Program arrivals per second (Poisson).
    pub program_rate: f64,
    pub class: ProgramClass,
    pub cost: CostModel,
    pub policy: RoutePolicy,
    /// Fraction of new programs placed on replica 0; the rest uniformly.
    pub hot_fraction: f64,
    /// Migration link bandwidth, tokens/s.
    pub migrate_bandwidth: f64,
    pub warmup: f64,
    pub horizon: f64,
    pub seed: u64,
}

impl RoutingConfig {
    /// Four replicas, half of the new programs on replica 0. Illustrative
    /// numbers, not measured.
    pub fn example(program_rate: f64, policy: RoutePolicy) -> Self {
        Self {
            replicas: 4,
            program_rate,
            class: ProgramClass {
                weight: 1.0,
                resume_prob: 0.9,
                initial_tokens: Dist::Uniform {
                    lo: 5_000.0,
                    hi: 15_000.0,
                },
                new_tokens: Dist::exp(500.0),
                output_tokens: Dist::exp(200.0),
                tool_time: Dist::exp(2.0),
            },
            cost: CostModel {
                overhead: 0.005,
                prefill_linear: 2.0e-5,
                prefill_quadratic: 2.0e-9,
                decode_per_token: 2.0e-4,
                decode_kv: 0.0,
            },
            policy,
            hot_fraction: 0.5,
            migrate_bandwidth: 2.0e6,
            warmup: 500.0,
            horizon: 10_500.0,
            seed: 1,
        }
    }
}

#[derive(Clone, Debug)]
pub struct RoutingReport {
    pub turns: u64,
    /// Ready-to-done time of follow-up turns, completion order.
    pub responses: Vec<f64>,
    pub response: Estimate,
    pub p99: f64,
    pub hit_rate: f64,
    pub migrations: u64,
    pub recomputes: u64,
    /// Busy fraction per replica.
    pub utilization: Vec<f64>,
    pub service: Welford,
    /// Mean context (tokens) of follow-up turns at their routing decision.
    pub mean_context: f64,
    /// Busy fraction of the migration link.
    pub link_utilization: f64,
}

fn number(x: f64) -> String {
    format!("{x:.17e}")
}

/// Render a `Dist` as a seQ sampling expression. Categorical mixtures are
/// represented by nested Bernoulli choices, so sampling stays in seQ.
fn sample_expr(dist: &Dist) -> String {
    match dist {
        Dist::Deterministic(x) => format!("~det({})", number(*x)),
        Dist::Exponential { mean } => format!("~exp({})", number(*mean)),
        Dist::Erlang { k, mean } => format!("~erlang({k}, {})", number(*mean)),
        Dist::HyperExp { p, mean1, mean2 } => format!(
            "(~bernoulli({}) ? ~exp({}) : ~exp({}))",
            number(*p),
            number(*mean1),
            number(*mean2)
        ),
        Dist::Uniform { lo, hi } => {
            format!("~uniform({}, {})", number(*lo), number(*hi))
        }
        Dist::Discrete { values, probs } => {
            assert!(!values.is_empty() && values.len() == probs.len());
            let mut tail = number(*values.last().expect("nonempty"));
            let mut suffix_probability = *probs.last().expect("nonempty");
            for (&value, &prob) in values.iter().zip(probs).rev().skip(1) {
                suffix_probability += prob;
                if prob > 0.0 {
                    let conditional = prob / suffix_probability;
                    tail = format!(
                        "(~bernoulli({}) ? {} : {})",
                        number(conditional),
                        number(value),
                        tail
                    );
                }
            }
            tail
        }
        Dist::HitMiss { p_hit, hit, miss } => format!(
            "(~bernoulli({}) ? {} : {})",
            number(*p_hit),
            number(*hit),
            number(*miss)
        ),
        Dist::Bernoulli { p } => format!("~bernoulli({})", number(*p)),
    }
}

/// Simulate by loading `programs/routing.seq` and running it in seQ.
pub fn simulate(cfg: &RoutingConfig) -> RoutingReport {
    assert_eq!(
        cfg.replicas, 4,
        "routing.seq currently declares four replicas"
    );
    let path = seq::program_path("routing");
    let mut source = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    for (pattern, replacement) in [
        (
            "~uniform(5000, 15000)",
            sample_expr(&cfg.class.initial_tokens),
        ),
        ("~exp(500)", sample_expr(&cfg.class.new_tokens)),
        ("~exp(200)", sample_expr(&cfg.class.output_tokens)),
        ("~exp(Z)", sample_expr(&cfg.class.tool_time)),
    ] {
        assert!(source.contains(pattern), "routing.seq lacks {pattern}");
        source = source.replacen(pattern, &replacement, 1);
    }
    let lets = vec![
        ("J", cfg.replicas.to_string()),
        ("rate", number(cfg.program_rate)),
        ("hot", number(cfg.hot_fraction)),
        ("policy", cfg.policy.code().to_string()),
        ("s0", number(cfg.cost.overhead)),
        ("a", number(cfg.cost.prefill_linear)),
        ("b", number(cfg.cost.prefill_quadratic)),
        ("d", number(cfg.cost.decode_per_token)),
        ("dv", number(cfg.cost.decode_kv)),
        ("p", number(cfg.class.resume_prob)),
        ("bw", number(cfg.migrate_bandwidth)),
    ]
    .into_iter()
    .map(|(name, value)| {
        (
            name.to_string(),
            seq::parser::parse_expr(&value).unwrap_or_else(|e| panic!("{name}={value}: {e}")),
        )
    })
    .collect::<Vec<_>>();
    let overrides = seq::Overrides {
        lets,
        seed: Some(cfg.seed),
        warmup: Some(cfg.warmup),
        horizon: Some(cfg.horizon),
        ..Default::default()
    };
    let r =
        seq::run_source(&source, &overrides, None).unwrap_or_else(|e| panic!("routing.seq: {e}"));

    let response = r.observe("response").expect("routing response observation");
    let hitrate = r.observe("hitrate").expect("routing hitrate observation");
    let migrations = r.observe("migration").map_or(0, |o| o.count);
    let hits = (hitrate.mean * hitrate.count as f64).round() as u64;
    let mut service = Welford::new();
    if let Some(samples) = r.observe("service") {
        for &x in &samples.samples {
            service.push(x);
        }
    }
    let mean_context = r.observe("context").map_or(0.0, |o| o.mean);
    let utilization = r
        .stages_named("rep")
        .iter()
        .map(|s| s.utilization)
        .collect();
    let link_utilization = r.stage("link").map_or(0.0, |s| s.utilization);

    RoutingReport {
        turns: r.turns,
        responses: response.samples.clone(),
        response: Estimate {
            mean: response.mean,
            half_width: response.ci.half_width,
        },
        p99: response.p99,
        hit_rate: hitrate.mean,
        migrations,
        recomputes: hitrate.count.saturating_sub(hits),
        utilization,
        service,
        mean_context,
        link_utilization,
    }
}
