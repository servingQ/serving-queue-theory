//! seQ execution for the paper's sampled-work PS, FIFO and LPS checks.

use super::agentic::Population;
use super::batch::{BatchConfig, BatchReport, Phi, Server, Work};
use crate::seq_adapter::{number, sample_expr};
use crate::stats::{Estimate, Welford, batch_means, quantile};

fn moments(xs: &[f64]) -> Welford {
    let mut out = Welford::new();
    xs.iter().for_each(|&x| out.push(x));
    out
}

fn ci_and_p99(xs: &[f64]) -> (Estimate, f64) {
    if xs.len() >= 40 {
        (batch_means(xs, 20), quantile(xs, 0.99))
    } else {
        (
            Estimate {
                mean: f64::NAN,
                half_width: f64::INFINITY,
            },
            f64::NAN,
        )
    }
}

fn replace(source: &mut String, from: &str, to: &str) {
    assert!(source.contains(from), "batch_sampled.seq lacks {from}");
    *source = source.replacen(from, to, 1);
}

fn ordered(observation: &seq::engine::report::ObserveReport) -> Vec<(u64, f64)> {
    let mut xs: Vec<_> = observation
        .records
        .iter()
        .zip(&observation.samples)
        .map(|(r, &x)| ((r.1 << 32) | u64::from(r.2), x))
        .collect();
    xs.sort_unstable_by_key(|r| r.0);
    xs
}

pub(super) fn simulate(cfg: &BatchConfig) -> BatchReport {
    let Work::Sampled { prefill, decode } = &cfg.work;
    assert_eq!(cfg.classes.len(), 1, "sampled-work check has one class");
    let class = &cfg.classes[0];
    let mut source = include_str!("../../../programs/batch_sampled.seq").to_string();
    if matches!(cfg.population, Population::Closed { .. }) {
        replace(&mut source, "arrive poisson(Lambda);", "arrive closed(N);");
    }
    replace(&mut source, "~exp(1)", &sample_expr(prefill));
    replace(&mut source, "~det(0)", &sample_expr(decode));
    replace(
        &mut source,
        "run tool (~det(0));",
        &format!("run tool ({});", sample_expr(&class.tool_time)),
    );
    let (phi, rate) = match cfg.server {
        Server::Fifo => {
            replace(
                &mut source,
                "stage svc : ps(service_rate);",
                "stage svc : fifo;",
            );
            (Phi::Constant(1.0), 1.0)
        }
        Server::Ps { phi } => {
            if let Phi::Saturating { .. } = phi {
                replace(
                    &mut source,
                    "stage svc : ps(service_rate);",
                    "stage svc : ps(min(n, phi_cap) / (1 + beta * (min(n, phi_cap) - 1)));",
                );
            }
            let rate = match phi {
                Phi::Constant(c) => c,
                Phi::Saturating { .. } => 1.0,
            };
            (phi, rate)
        }
    };
    let (beta, phi_cap) = match phi {
        Phi::Constant(_) => (0.0, f64::INFINITY),
        Phi::Saturating { beta, cap } => (beta, cap.map_or(f64::INFINITY, |c| c as f64)),
    };
    let (n, lambda) = match cfg.population {
        Population::Closed { programs } => (programs as f64, 1.0),
        Population::Open { rate } => (1.0, rate),
    };
    let lets = [
        ("Lambda", lambda),
        ("N", n),
        ("p", class.resume_prob),
        ("B", cfg.batch_cap.map_or(f64::INFINITY, |b| b as f64)),
        ("beta", beta),
        ("phi_cap", phi_cap),
        ("service_rate", rate),
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
    .unwrap_or_else(|e| panic!("batch_sampled.seq: {e}"));
    let response = report.observe("response").expect("batch response");
    let ttft = report.observe("ttft").expect("batch TTFT");
    let wait = report.observe("wait").expect("batch wait");
    let work = report.observe("work").expect("batch work");
    let responses = ordered(response);
    let ttfts = ordered(ttft);
    let response_values: Vec<_> = responses.iter().map(|r| r.1).collect();
    let ttft_values: Vec<_> = ttfts.iter().map(|r| r.1).collect();
    let (response_ci, p99) = ci_and_p99(&response_values);
    let (ttft_ci, ttft_p99) = ci_and_p99(&ttft_values);
    let batch = report.pool("batch").expect("batch cap pool");
    let svc = report.stage("svc").expect("batch service stage");
    BatchReport {
        turns: response.count,
        throughput: response.count as f64 / (cfg.horizon - cfg.warmup),
        sessions_done: report.ended,
        hit_rate: if class.resume_prob > 0.0 {
            1.0
        } else {
            f64::NAN
        },
        response: moments(&response_values),
        response_ci,
        p99,
        responses,
        ttft: moments(&ttft_values),
        ttft_ci,
        ttft_p99,
        ttfts,
        wait: moments(&wait.samples),
        work: moments(&work.samples),
        mean_number: batch.mean_queue + batch.mean_used,
        mean_batch: batch.mean_used,
        mean_prefill_number: batch.mean_queue + batch.mean_used,
        mean_decode_number: 0.0,
        mean_availability: 1.0,
        utilization: svc.utilization,
        mean_resident_kv: 0.0,
        mean_sessions: report.mean_live,
        mean_entry_queue: 0.0,
        entry_wait: Welford::new(),
        evictions: 0,
        recomputes: 0,
        recomputed_tokens: 0.0,
        truncated: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Dist;

    #[test]
    fn ttft_stops_after_prefill() {
        let mut cfg =
            BatchConfig::poisson_turns(0.1, Dist::Deterministic(2.0), Server::Fifo, 100.0, 1);
        cfg.population = Population::Closed { programs: 1 };
        cfg.classes[0].resume_prob = 1.0;
        cfg.classes[0].tool_time = Dist::Deterministic(10.0);
        cfg.work = Work::Sampled {
            prefill: Dist::Deterministic(2.0),
            decode: Dist::Deterministic(3.0),
        };
        let report = simulate(&cfg);
        assert!((report.ttft.mean() - 2.0).abs() < 1e-9);
        assert!((report.response.mean() - 5.0).abs() < 1e-9);
    }
}
