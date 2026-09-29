//! Aggregated vs prefill/decode-disaggregated serving (paper §4, Prop. pd).
//!
//! Aggregated: one pool of `N` devices; a request holds one device for
//! `prefill + decode + I` (interference). Disaggregated: a tandem
//! `prefill pool (N_P) → KV link → decode pool (N_D)`, with specialisation
//! gains dividing each phase's work and a single FIFO link moving `K`
//! tokens per request at `b_net` tokens/s.
//!
//! [`Load::Saturated`] keeps every pool busy and measures capacity, the
//! scalar Prop. pd reasons about. [`Load::Poisson`] measures latency at a
//! given rate, which the scalar model does not see: two configurations with
//! equal capacity can have different queueing delay. Memory caps
//! (`μ_{P,mem}`, `μ_{D,mem}`) are not simulated.

use std::path::Path;

use crate::Dist;
use crate::seq_adapter::sample_expr;
use crate::stats::{Estimate, Welford, batch_means};

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Mode {
    Aggregated,
    Disaggregated { prefill_devices: usize },
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Load {
    /// `jobs` requests always in the system (a finished one re-enters at
    /// once): measures capacity.
    Saturated { jobs: usize },
    /// Poisson arrivals at `rate` per second: measures latency.
    Poisson { rate: f64 },
}

#[derive(Clone, Debug)]
pub struct PdConfig {
    pub devices: usize,
    pub mode: Mode,
    pub load: Load,
    /// Prefill work per request on a generic device (seconds), mean `s_P`.
    pub prefill: Dist,
    /// Decode work per request on a generic device (seconds), mean `s_D`.
    pub decode: Dist,
    /// Aggregated-only interference overhead per request (seconds), `I`.
    pub interference: f64,
    pub gain_prefill: f64,
    pub gain_decode: f64,
    /// KV tokens shipped per request, mean `E[K]`.
    pub kv_tokens: Dist,
    /// Link bandwidth, tokens/s (`B_net`). `f64::INFINITY` disables it.
    pub b_net: f64,
    pub requests: usize,
    pub warmup: usize,
    pub seed: u64,
}

impl PdConfig {
    /// Mean-value parameters `(s_P, s_D, I, g_P, g_D, B_net, E[K])` with
    /// exponential work, for comparison with the Lean closed forms.
    #[allow(clippy::too_many_arguments)]
    pub fn from_means(
        devices: usize,
        mode: Mode,
        load: Load,
        s_p: f64,
        s_d: f64,
        interference: f64,
        gains: (f64, f64),
        b_net: f64,
        e_k: f64,
    ) -> Self {
        Self {
            devices,
            mode,
            load,
            prefill: Dist::exp(s_p),
            decode: Dist::exp(s_d),
            interference,
            gain_prefill: gains.0,
            gain_decode: gains.1,
            kv_tokens: Dist::Deterministic(e_k),
            b_net,
            requests: 200_000,
            warmup: 20_000,
            seed: 1,
        }
    }
}

#[derive(Clone, Debug)]
pub struct PdReport {
    /// Completions per second after warm-up.
    pub throughput: f64,
    /// End-to-end latency per request, completion order.
    pub latencies: Vec<f64>,
    pub latency: Estimate,
    /// Busy fraction of each station (aggregated: one entry; PD: P, link, D).
    pub station_utilization: Vec<f64>,
    pub latency_stats: Welford,
}

pub fn simulate(cfg: &PdConfig) -> PdReport {
    if let Load::Saturated { jobs } = cfg.load {
        return simulate_saturated_seq(cfg, jobs);
    }
    simulate_poisson_seq(cfg)
}

/// The saturated tandem model is defined by the packaged `pd_tandem.seq`
/// program. Keep this module as the Rust configuration/report adapter.
fn simulate_saturated_seq(cfg: &PdConfig, jobs: usize) -> PdReport {
    let prefill_devices = match cfg.mode {
        // `pd_tandem.seq` declares all three stations even on the aggregate
        // path; keep both split pools positive because seQ checks the model
        // declarations before it sees the branch.
        Mode::Aggregated => 1,
        Mode::Disaggregated { prefill_devices } => prefill_devices,
    };
    let (mut source, path) = {
        let path = seq::program_path("pd_tandem");
        let source = std::fs::read_to_string(&path)
            .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
        (source, path)
    };
    for (pattern, replacement) in [
        ("~exp(sP)", sample_expr(&cfg.prefill)),
        ("~exp(sD)", sample_expr(&cfg.decode)),
        ("~exp(K)", sample_expr(&cfg.kv_tokens)),
    ] {
        assert!(source.contains(pattern), "pd_tandem.seq lacks {pattern}");
        source = source.replacen(pattern, &replacement, 1);
    }

    let split = matches!(cfg.mode, Mode::Disaggregated { .. });
    let mean_sp = cfg.prefill.mean() / cfg.gain_prefill;
    let mean_sd = cfg.decode.mean() / cfg.gain_decode;
    let capacity = if split {
        (prefill_devices as f64 / mean_sp)
            .min((cfg.devices - prefill_devices) as f64 / mean_sd)
            .min(cfg.b_net / cfg.kv_tokens.mean())
    } else {
        cfg.devices as f64 / (cfg.prefill.mean() + cfg.decode.mean() + cfg.interference)
    };
    let measured = cfg.requests.max(1) as f64;
    let horizon = 1.2 * (cfg.warmup as f64 + measured) / capacity.max(f64::MIN_POSITIVE) + 1.0;
    let number = |x: f64| {
        seq::frontend::parser::parse_expr(&format!("{x:.17e}"))
            .unwrap_or_else(|e| panic!("invalid seQ number {x}: {e}"))
    };
    let overrides = seq::Overrides {
        lets: vec![
            ("N".into(), number(cfg.devices as f64)),
            ("NP".into(), number(prefill_devices as f64)),
            ("sP".into(), number(cfg.prefill.mean())),
            ("sD".into(), number(cfg.decode.mean())),
            ("I".into(), number(cfg.interference)),
            ("gP".into(), number(cfg.gain_prefill)),
            ("gD".into(), number(cfg.gain_decode)),
            ("bnet".into(), number(cfg.b_net)),
            ("K".into(), number(cfg.kv_tokens.mean())),
            ("jobs".into(), number(jobs as f64)),
            ("mode".into(), number(if split { 1.0 } else { 0.0 })),
        ],
        seed: Some(cfg.seed),
        warmup: Some(0.0),
        horizon: Some(horizon),
        ..Default::default()
    };
    let report = seq::run_source(&source, &overrides, Path::new(&path).parent())
        .unwrap_or_else(|e| panic!("pd_tandem.seq: {e}"));
    let observed = report.observe("latency").expect("PD latency observation");
    let start = cfg.warmup.min(observed.samples.len());
    let end = (start + cfg.requests).min(observed.samples.len());
    assert!(end > start, "pd_tandem.seq produced no measured requests");
    let latencies = observed.samples[start..end].to_vec();
    let times = &observed.records[start..end];
    let span = if times.len() > 1 {
        times[times.len() - 1].0 - times[0].0
    } else {
        horizon
    };
    let mut latency_stats = Welford::new();
    for &latency in &latencies {
        latency_stats.push(latency);
    }
    let station_utilization = if split {
        ["prefill", "link", "decode"]
            .iter()
            .map(|name| report.stage(name).map_or(0.0, |stage| stage.utilization))
            .collect()
    } else {
        vec![report.stage("agg").map_or(0.0, |stage| stage.utilization)]
    };
    PdReport {
        throughput: latencies.len() as f64 / span.max(f64::MIN_POSITIVE),
        latency: batch_means(&latencies, 20),
        latencies,
        station_utilization,
        latency_stats,
    }
}

/// Open arrivals run the seQ program `pd_open.seq`; this adapter only maps
/// the Rust configuration and seQ observations onto the compatibility report.
fn simulate_poisson_seq(cfg: &PdConfig) -> PdReport {
    let Load::Poisson { rate } = cfg.load else {
        unreachable!()
    };
    let (prefill_devices, split) = match cfg.mode {
        Mode::Aggregated => (1, false),
        Mode::Disaggregated { prefill_devices } => {
            assert!(0 < prefill_devices && prefill_devices < cfg.devices);
            (prefill_devices, true)
        }
    };
    let path = seq::program_path("pd_open");
    let mut source = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    for (pattern, replacement) in [
        ("~exp(sP)", sample_expr(&cfg.prefill)),
        ("~exp(sD)", sample_expr(&cfg.decode)),
        ("~exp(K)", sample_expr(&cfg.kv_tokens)),
    ] {
        assert!(source.contains(pattern), "pd_open.seq lacks {pattern}");
        source = source.replacen(pattern, &replacement, 1);
    }
    let number = |x: f64| {
        seq::frontend::parser::parse_expr(&format!("{x:.17e}"))
            .unwrap_or_else(|e| panic!("invalid seQ number {x}: {e}"))
    };
    let horizon = 1.5 * (cfg.warmup + cfg.requests).max(1) as f64 / rate + 100.0;
    let overrides = seq::Overrides {
        lets: vec![
            ("N".into(), number(cfg.devices as f64)),
            ("NP".into(), number(prefill_devices as f64)),
            ("Lambda".into(), number(rate)),
            ("sP".into(), number(cfg.prefill.mean())),
            ("sD".into(), number(cfg.decode.mean())),
            ("I".into(), number(cfg.interference)),
            ("gP".into(), number(cfg.gain_prefill)),
            ("gD".into(), number(cfg.gain_decode)),
            ("bnet".into(), number(cfg.b_net)),
            ("K".into(), number(cfg.kv_tokens.mean())),
            ("mode".into(), number(if split { 1.0 } else { 0.0 })),
        ],
        seed: Some(cfg.seed),
        warmup: Some(0.0),
        horizon: Some(horizon),
        ..Default::default()
    };
    let report = seq::run_source(&source, &overrides, Path::new(&path).parent())
        .unwrap_or_else(|e| panic!("pd_open.seq: {e}"));
    let observed = report.observe("latency").expect("PD latency observation");
    let start = cfg.warmup.min(observed.samples.len());
    let end = (start + cfg.requests).min(observed.samples.len());
    assert!(end > start, "pd_open.seq produced no measured requests");
    let latencies = observed.samples[start..end].to_vec();
    let times = &observed.records[start..end];
    let span = if times.len() > 1 {
        times[times.len() - 1].0 - times[0].0
    } else {
        horizon
    };
    let mut latency_stats = Welford::new();
    for &latency in &latencies {
        latency_stats.push(latency);
    }
    let station_utilization = if split {
        [
            ("prefill", prefill_devices),
            ("link", 1),
            ("decode", cfg.devices - prefill_devices),
        ]
        .iter()
        .map(|(name, servers)| {
            report.stage(name).map_or(0.0, |stage| {
                (stage.throughput * stage.mean_service / *servers as f64).min(1.0)
            })
        })
        .collect()
    } else {
        vec![report.stage("agg").map_or(0.0, |stage| {
            (stage.throughput * stage.mean_service / cfg.devices as f64).min(1.0)
        })]
    };
    PdReport {
        throughput: latencies.len() as f64 / span.max(f64::MIN_POSITIVE),
        latency: batch_means(&latencies, 20),
        latencies,
        station_utilization,
        latency_stats,
    }
}

/// Capacity of an integer split under the model of Prop. pd (iii), without
/// memory caps: `min(N_P g_P / s_P, N_D g_D / s_D, B_net / E[K])`.
pub fn split_capacity(cfg: &PdConfig, prefill_devices: usize) -> f64 {
    let n_p = prefill_devices as f64;
    let n_d = (cfg.devices - prefill_devices) as f64;
    (n_p * cfg.gain_prefill / cfg.prefill.mean())
        .min(n_d * cfg.gain_decode / cfg.decode.mean())
        .min(cfg.b_net / cfg.kv_tokens.mean())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn single_device_aggregated_capacity() {
        let mut cfg = PdConfig::from_means(
            1,
            Mode::Aggregated,
            Load::Saturated { jobs: 4 },
            0.3,
            0.7,
            0.0,
            (1.0, 1.0),
            f64::INFINITY,
            1.0,
        );
        cfg.requests = 50_000;
        cfg.warmup = 1_000;
        let r = simulate(&cfg);
        assert!((r.throughput - 1.0).abs() < 0.02, "{}", r.throughput);
        assert!(r.station_utilization[0] > 0.99);
    }

    #[test]
    fn open_poisson_load_uses_the_seq_program() {
        let mut cfg = PdConfig::from_means(
            8,
            Mode::Disaggregated { prefill_devices: 2 },
            Load::Poisson { rate: 1.5 },
            1.0,
            3.0,
            0.0,
            (1.0, 1.0),
            f64::INFINITY,
            1.0,
        );
        cfg.requests = 5_000;
        cfg.warmup = 500;
        let report = simulate(&cfg);
        assert_eq!(report.latencies.len(), cfg.requests);
        assert!(report.throughput > 1.2 && report.throughput < 1.8);
        assert!(
            report
                .station_utilization
                .iter()
                .all(|u| *u >= 0.0 && *u <= 1.0)
        );
    }
}
