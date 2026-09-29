//! Open G/G/c FIFO service centre (paper §2.1–2.2).
//!
//! With exponential interarrivals and `servers = 1` this is the M/G/1 queue
//! of the PK formula; with exponential service it is M/M/1. Non-Poisson
//! arrivals (e.g. [`Dist::hyperexp_balanced`]) leave the model of Props.
//! mm1–cache and enter the regime of Kingman's bound.
//!
//! Interarrival and service times use separate RNG streams, so two runs that
//! differ only in the service distribution see the same arrival sequence
//! (common random numbers).

use rand::SeedableRng;
use rand::rngs::StdRng;

use crate::Dist;
use crate::seq_adapter::sample_expr;
use crate::stats::{Estimate, Welford, batch_means};

#[derive(Clone, Debug)]
pub struct QueueConfig {
    pub interarrival: Dist,
    pub service: Dist,
    pub servers: usize,
    /// Customers whose statistics are recorded.
    pub customers: usize,
    /// Customers discarded at the start (initial transient).
    pub warmup: usize,
    pub seed: u64,
}

impl QueueConfig {
    /// M/G/1 with Poisson arrivals at rate `lam`.
    pub fn mg1(lam: f64, service: Dist, customers: usize, seed: u64) -> Self {
        Self {
            interarrival: Dist::exp(1.0 / lam),
            service,
            servers: 1,
            customers,
            warmup: customers / 10,
            seed,
        }
    }

    pub fn offered_load(&self) -> f64 {
        self.service.mean() / (self.interarrival.mean() * self.servers as f64)
    }
}

#[derive(Clone, Debug)]
pub struct QueueReport {
    /// Waiting time in queue of each recorded customer, in arrival order.
    pub waits: Vec<f64>,
    /// Time in system of each recorded customer, in arrival order.
    pub sojourns: Vec<f64>,
    pub wait: Estimate,
    pub sojourn: Estimate,
    /// Time-average number in system over the measurement window.
    pub mean_in_system: f64,
    /// Arrivals per unit time over the measurement window.
    pub arrival_rate: f64,
    /// Time-average fraction of busy servers.
    pub utilization: f64,
    /// Observed service times of recorded customers.
    pub service: Welford,
}

impl QueueReport {
    /// Little's law residual `|L - λW| / L`.
    pub fn little_residual(&self) -> f64 {
        let lw = self.arrival_rate * self.sojourn.mean;
        (self.mean_in_system - lw).abs() / self.mean_in_system
    }
}

fn streams(seed: u64) -> (StdRng, StdRng) {
    (
        StdRng::seed_from_u64(seed),
        StdRng::seed_from_u64(seed ^ 0x9E37_79B9_7F4A_7C15),
    )
}

/// Simulate through the packaged `mg1.seq` program and adapt its observations
/// to the existing queue report. `arrivals` stops the finite input stream and
/// drains the customers before producing the report.
pub fn simulate(cfg: &QueueConfig) -> QueueReport {
    assert!(cfg.servers >= 1 && cfg.customers >= 20);
    let total = cfg.warmup + cfg.customers;
    let path = seq::program_path("mg1");
    let mut source = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    source = source.replace(
        "stage svc : fifo;",
        &format!("stage svc : fifo({});", cfg.servers),
    );
    assert!(
        source.contains("arrive poisson(lam);"),
        "mg1.seq arrival declaration changed"
    );
    source = source.replace(
        "arrive poisson(lam);",
        &format!("arrive renewal({});", sample_expr(&cfg.interarrival)),
    );
    let start = source
        .find("    set s = law ==")
        .expect("mg1 service sampler");
    let tail = &source[start..];
    let end = tail.find(';').expect("mg1 service sampler terminator") + start + 1;
    source.replace_range(
        start..end,
        &format!("    set s = {};", sample_expr(&cfg.service)),
    );

    let rho = cfg.offered_load();
    let drain = if rho < 1.0 {
        20.0 * cfg.service.mean() / (1.0 - rho).max(0.01)
    } else {
        20.0 * total as f64 * cfg.interarrival.mean()
    };
    let margin = (10.0 * (total as f64).sqrt()).max(100.0);
    let mut horizon = cfg.interarrival.mean() * (total as f64 + margin) + drain;
    let report = loop {
        let overrides = seq::Overrides {
            seed: Some(cfg.seed),
            warmup: Some(0.0),
            horizon: Some(horizon),
            arrivals: Some(total),
            ..Default::default()
        };
        let result = seq::run_source(&source, &overrides, path.parent())
            .unwrap_or_else(|e| panic!("mg1.seq: {e}"));
        if result.arrivals >= total as u64 {
            break result;
        }
        horizon *= 2.0;
        assert!(
            horizon.is_finite(),
            "mg1.seq could not generate the requested arrivals"
        );
    };
    let waits = by_arrival(report.observe("wait").expect("queue wait observation"));
    let sojourn_observation = report
        .observe("sojourn")
        .expect("queue sojourn observation");
    let sojourns = by_arrival(sojourn_observation);
    let completions = completion_times_by_arrival(sojourn_observation);
    let services = by_arrival(
        report
            .observe("service")
            .expect("queue service observation"),
    );
    assert!(
        waits.len() >= total && sojourns.len() >= total && services.len() >= total,
        "mg1.seq did not drain all requested arrivals: {} arrivals, {} waits, {} sojourns, {} services",
        report.arrivals,
        waits.len(),
        sojourns.len(),
        services.len()
    );
    let start = completions[cfg.warmup] - sojourns[cfg.warmup];
    let end = completions[total - 1] - sojourns[total - 1];
    let span = end - start;
    let overlap = |a: f64, b: f64| (b.min(end) - a.max(start)).max(0.0);
    let mean_in_system = (0..total)
        .map(|i| overlap(completions[i] - sojourns[i], completions[i]))
        .sum::<f64>()
        / span;
    let utilization = (0..total)
        .map(|i| overlap(completions[i] - services[i], completions[i]))
        .sum::<f64>()
        / span
        / cfg.servers as f64;
    let waits = waits[cfg.warmup..total].to_vec();
    let sojourns = sojourns[cfg.warmup..total].to_vec();
    let services = &services[cfg.warmup..total];
    let mut service = Welford::new();
    services.iter().for_each(|&s| service.push(s));
    let arrival_rate = (cfg.customers - 1) as f64 / span;
    QueueReport {
        wait: batch_means(&waits, 20),
        sojourn: batch_means(&sojourns, 20),
        waits,
        sojourns,
        mean_in_system,
        arrival_rate,
        utilization,
        service,
    }
}

fn by_arrival(observation: &seq::engine::report::ObserveReport) -> Vec<f64> {
    let mut samples: Vec<_> = observation
        .records
        .iter()
        .zip(&observation.samples)
        .map(|(record, &value)| (record.1, value))
        .collect();
    samples.sort_unstable_by_key(|(serial, _)| *serial);
    samples.into_iter().map(|(_, value)| value).collect()
}

fn completion_times_by_arrival(observation: &seq::engine::report::ObserveReport) -> Vec<f64> {
    let mut records = observation.records.clone();
    records.sort_unstable_by_key(|record| record.1);
    records.into_iter().map(|record| record.0).collect()
}

/// Waiting times of a single-server FIFO queue by Lindley's recursion
/// `W_{n+1} = max(0, W_n + S_n - A_{n+1})`, drawing from the same RNG
/// streams in the same order as [`simulate`]. An independent check of the
/// event engine: for `servers = 1` the two must agree to rounding.
pub fn lindley_waits(cfg: &QueueConfig) -> Vec<f64> {
    let (mut arr, mut svc) = streams(cfg.seed);
    let total = cfg.warmup + cfg.customers;
    let _first_arrival = cfg.interarrival.sample(&mut arr);
    let mut out = Vec::with_capacity(total);
    let mut w = 0.0_f64;
    for n in 0..total {
        out.push(w);
        let s = cfg.service.sample(&mut svc);
        if n + 1 < total {
            let a = cfg.interarrival.sample(&mut arr);
            w = (w + s - a).max(0.0);
        }
    }
    out.split_off(cfg.warmup)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn engine_agrees_with_lindley() {
        let cfg = QueueConfig::mg1(0.8, Dist::hyperexp_balanced(1.0, 5.0), 50_000, 3);
        let des = simulate(&cfg);
        let lin = lindley_waits(&cfg);
        assert_eq!(des.waits.len(), lin.len());
        let worst = des
            .waits
            .iter()
            .zip(&lin)
            .map(|(a, b)| (a - b).abs())
            .fold(0.0, f64::max);
        assert!(worst < 1e-8, "max |DES - Lindley| = {worst}");
    }

    #[test]
    fn deterministic_underload_never_waits() {
        let cfg = QueueConfig {
            interarrival: Dist::Deterministic(1.0),
            service: Dist::Deterministic(0.5),
            servers: 1,
            customers: 1000,
            warmup: 10,
            seed: 0,
        };
        let r = simulate(&cfg);
        assert!(r.waits.iter().all(|&w| w == 0.0));
        assert!((r.utilization - 0.5).abs() < 1e-3);
    }
}
