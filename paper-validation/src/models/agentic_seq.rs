//! Execute the paper's agentic workload with seQ and adapt its observations.

use super::agentic::{
    AgenticConfig, AgenticReport, EvictionPolicy, FetchMode, OffloadPolicy, Population,
};
use crate::seq_adapter::{number, sample_expr};
use crate::stats::{Estimate, Welford, batch_means};

fn moments(xs: &[f64]) -> Welford {
    let mut out = Welford::new();
    for &x in xs {
        out.push(x);
    }
    out
}

fn class_expr(
    cfg: &AgenticConfig,
    law: impl Fn(&super::agentic::ProgramClass) -> String,
) -> String {
    let mut classes = cfg.classes.iter().enumerate().rev();
    let (_, last) = classes.next().expect("at least one program class");
    let mut expr = law(last);
    for (i, class) in classes {
        expr = format!("(cls == {i} ? {} : {expr})", law(class));
    }
    expr
}

fn replace(source: &mut String, from: &str, to: &str) {
    assert!(source.contains(from), "agentic_model.seq lacks {from}");
    *source = source.replacen(from, to, 1);
}

pub(super) fn simulate(cfg: &AgenticConfig) -> AgenticReport {
    assert!(!cfg.classes.is_empty());
    assert!(cfg.warmup < cfg.horizon);
    let mut source = include_str!("../../../programs/agentic_model.seq").to_string();
    if let Population::Open { .. } = cfg.population {
        replace(&mut source, "arrive closed(N);", "arrive poisson(Lambda);");
    }

    let weights: Vec<f64> = cfg.classes.iter().map(|c| c.weight).collect();
    let weight_sum: f64 = weights.iter().sum();
    let class_law = if weights.len() == 1 {
        "0".to_string()
    } else {
        sample_expr(&seq::Dist::discrete(
            (0..weights.len()).map(|i| i as f64).collect(),
            weights.iter().map(|w| w / weight_sum).collect(),
        ))
    };
    replace(
        &mut source,
        "set K = 0; set cold = 1; set p = 0.9;",
        &format!(
            "set K = 0; set cold = 1; set cls = {class_law}; set p = {}; set mean_new = {}; set mean_out = {}; set tau = {};",
            class_expr(cfg, |c| number(c.resume_prob)),
            class_expr(cfg, |c| number(c.new_tokens.mean())),
            class_expr(cfg, |c| number(c.output_tokens.mean())),
            class_expr(cfg, |c| number(c.tool_time.mean()))
        ),
    );
    replace(
        &mut source,
        "~uniform(1e4, 3e4)",
        &class_expr(cfg, |c| sample_expr(&c.initial_tokens)),
    );
    replace(
        &mut source,
        "~exp(1000)",
        &class_expr(cfg, |c| sample_expr(&c.new_tokens)),
    );
    replace(
        &mut source,
        "~exp(300)",
        &class_expr(cfg, |c| sample_expr(&c.output_tokens)),
    );
    replace(
        &mut source,
        "~exp(3)",
        &class_expr(cfg, |c| sample_expr(&c.tool_time)),
    );

    let key = match cfg.eviction {
        EvictionPolicy::ShortestFirst => "evict by (queued, size);",
        EvictionPolicy::LongestFirst => "evict by (queued, -size);",
        EvictionPolicy::Lru => "evict by (queued, last);",
        EvictionPolicy::Random => "evict by (queued, ~uniform(0, 1));",
        EvictionPolicy::Density => "evict by (queued, (queued ? 1 : p) * (a + b * size / 2));",
        EvictionPolicy::Priced => {
            "evict by (queued, (queued ? 1 : p) * price(svc, s0 + a * mean_new + b * mean_new * (size + mean_new / 2) + mean_out * (d + dv * (size + mean_new)), a * size + b * size * size / 2) / size);"
        }
        EvictionPolicy::PricedMemory => {
            "evict by (queued, (queued ? 1 : p) * price(svc, s0 + a * mean_new + b * mean_new * (size + mean_new / 2) + mean_out * (d + dv * (size + mean_new)), a * size + b * size * size / 2) / (size * (queued ? 1 : tau)));"
        }
        EvictionPolicy::PricedMemoryBlocks => {
            panic!("block-level eviction belongs to the batch model")
        }
    };
    replace(&mut source, "evict by (queued, size);", key);
    let miss = "(a * size + b * size * size / 2)";
    let hit = "(s0 + a * mean_new + b * mean_new * (size + mean_new / 2) + mean_out * (d + dv * (size + mean_new)))";
    let transfer = "(work(link) + size / bw)";
    let spill = match cfg.offload {
        OffloadPolicy::Never => "0".to_string(),
        OffloadPolicy::Always => "!queued".to_string(),
        OffloadPolicy::Selective if cfg.fetch == FetchMode::Blocking => {
            format!("!queued && {transfer} < p * {miss}")
        }
        OffloadPolicy::Selective => {
            format!("!queued && {transfer} < p * {miss} * (1 + queued(slot))")
        }
        OffloadPolicy::Priced if cfg.fetch == FetchMode::Blocking => {
            format!("!queued && {transfer} < {miss}")
        }
        OffloadPolicy::Priced => {
            format!("!queued && {transfer} < p * price(svc, {hit}, {miss})")
        }
    };
    replace(&mut source, "when (0)", &format!("when ({spill})"));
    let fetch = match cfg.offload {
        OffloadPolicy::Never => "0".to_string(),
        OffloadPolicy::Always => "1".to_string(),
        OffloadPolicy::Selective | OffloadPolicy::Priced if cfg.fetch == FetchMode::Blocking => {
            "work(link) + K / bw < a * K + b * K * K / 2".to_string()
        }
        OffloadPolicy::Selective => {
            "work(link) + K / bw < (a * K + b * K * K / 2) * (1 + queued(slot))"
                .to_string()
        }
        OffloadPolicy::Priced => {
            "work(link) + K / bw < price(svc, s0 + a * mean_new + b * mean_new * (K + mean_new / 2) + mean_out * (d + dv * (K + mean_new)), a * K + b * K * K / 2)".to_string()
        }
    };
    replace(
        &mut source,
        "blocking == 0 && 1",
        &format!("blocking == 0 && ({fetch})"),
    );
    replace(
        &mut source,
        "blocking == 1 && 1",
        &format!("blocking == 1 && ({fetch})"),
    );

    let (n, rate) = match cfg.population {
        Population::Closed { programs } => (programs as f64, 0.05),
        Population::Open { rate } => (1.0, rate),
    };
    let lets = [
        ("N", n),
        ("Lambda", rate),
        ("C", cfg.kv_capacity),
        ("maxctx", cfg.max_context),
        ("s0", cfg.cost.overhead),
        ("a", cfg.cost.prefill_linear),
        ("b", cfg.cost.prefill_quadratic),
        ("d", cfg.cost.decode_per_token),
        ("dv", cfg.cost.decode_kv),
        ("bw", cfg.tier_bandwidth),
        (
            "blocking",
            if cfg.fetch == FetchMode::Blocking {
                1.0
            } else {
                0.0
            },
        ),
    ]
    .into_iter()
    .map(|(name, value)| {
        (
            name.to_string(),
            seq::frontend::parser::parse_expr(&number(value)).expect("numeric seQ override"),
        )
    })
    .collect();
    let report = seq::run_source(
        &source,
        &seq::Overrides {
            lets,
            seed: Some(cfg.seed),
            warmup: Some(cfg.warmup),
            horizon: Some(cfg.horizon),
            ..Default::default()
        },
        None,
    )
    .unwrap_or_else(|e| panic!("agentic_model.seq: {e}"));
    let values = |name: &str| {
        report
            .observe(name)
            .unwrap_or_else(|| panic!("agentic_model.seq lacks {name}"))
            .samples
            .clone()
    };
    let responses = values("response");
    let waits = values("wait");
    let service = values("service");
    let think = values("think");
    let hits = values("hit");
    let recompute = values("recompute_work");
    let stall = values("stall");
    let span = cfg.horizon - cfg.warmup;
    let kv = report.pool("kv").expect("KV pool");
    let slot = report.pool("slot").expect("replica slot");
    let link = report.stage("link").expect("tier link");
    AgenticReport {
        turns: responses.len() as u64,
        throughput: responses.len() as f64 / span,
        hit_rate: moments(&hits).mean(),
        service: moments(&service),
        wait: if waits.len() >= 40 {
            batch_means(&waits, 20)
        } else {
            Estimate {
                mean: f64::NAN,
                half_width: f64::INFINITY,
            }
        },
        waits,
        response: moments(&responses),
        think: moments(&think),
        utilization: slot.mean_used,
        mean_resident_kv: kv.mean_used + kv.mean_cached,
        mean_programs: report.mean_live,
        evictions: kv.evicted_entries,
        offload_writes: kv.spills,
        fetches: report.observe("fetched").map_or(0, |x| x.count),
        recomputes: hits.iter().filter(|&&x| x == 0.0).count() as u64,
        truncated: report.observe("truncated").map_or(0, |x| x.count),
        tier_utilization: link.utilization,
        recompute_load: recompute.iter().sum::<f64>() / span,
        stall_load: stall.iter().sum::<f64>() / span,
    }
}
