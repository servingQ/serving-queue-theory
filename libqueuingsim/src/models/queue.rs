//! Open G/G/c FIFO service centre (paper §2.1, §3).
//!
//! With exponential interarrivals and `servers = 1` this is the M/G/1 queue
//! of the PK formula; with exponential service it is M/M/1. Non-Poisson
//! arrivals (e.g. [`Dist::hyperexp_balanced`]) leave the model of Props.
//! mm1–cache and enter the regime of Kingman's bound.
//!
//! Interarrival and service times use separate RNG streams, so two runs that
//! differ only in the service distribution see the same arrival sequence
//! (common random numbers).

use std::collections::VecDeque;

use rand::SeedableRng;
use rand::rngs::StdRng;

use crate::dist::Dist;
use crate::engine::{Model, Scheduler, run};
use crate::stats::{Estimate, TimeAverage, Welford, batch_means};

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

enum Ev {
    Arrival,
    Departure { server: usize },
}

struct Customer {
    idx: usize,
    arrival: f64,
    service: f64,
}

struct Ggc {
    cfg: QueueConfig,
    arr_rng: StdRng,
    svc_rng: StdRng,
    total: usize,
    arrived: usize,
    queue: VecDeque<Customer>,
    busy: Vec<Option<Customer>>,
    waits: Vec<f64>,
    sojourns: Vec<f64>,
    service: Welford,
    in_system: TimeAverage,
    busy_servers: TimeAverage,
    window: Option<(f64, f64)>,
    snapshot: (f64, f64),
}

impl Ggc {
    fn new(cfg: QueueConfig) -> Self {
        let total = cfg.warmup + cfg.customers;
        let (arr_rng, svc_rng) = streams(cfg.seed);
        Self {
            busy: (0..cfg.servers).map(|_| None).collect(),
            cfg,
            arr_rng,
            svc_rng,
            total,
            arrived: 0,
            queue: VecDeque::new(),
            waits: vec![0.0; total],
            sojourns: vec![0.0; total],
            service: Welford::new(),
            in_system: TimeAverage::new(0.0, 0.0),
            busy_servers: TimeAverage::new(0.0, 0.0),
            window: None,
            snapshot: (0.0, 0.0),
        }
    }

    fn start(&mut self, server: usize, c: Customer, s: &mut Scheduler<Ev>) {
        let now = s.now();
        self.waits[c.idx] = now - c.arrival;
        s.after(c.service, Ev::Departure { server });
        self.busy[server] = Some(c);
        self.busy_servers.add(now, 1.0);
    }
}

impl Model for Ggc {
    type Event = Ev;

    fn handle(&mut self, ev: Ev, s: &mut Scheduler<Ev>) {
        let now = s.now();
        match ev {
            Ev::Arrival => {
                let idx = self.arrived;
                self.arrived += 1;
                if idx == self.cfg.warmup {
                    self.in_system.reset(now);
                    self.busy_servers.reset(now);
                    self.window = Some((now, now));
                }
                let service = self.cfg.service.sample(&mut self.svc_rng);
                if idx >= self.cfg.warmup {
                    self.service.push(service);
                }
                self.in_system.add(now, 1.0);
                let c = Customer {
                    idx,
                    arrival: now,
                    service,
                };
                match self.busy.iter().position(Option::is_none) {
                    Some(server) => self.start(server, c, s),
                    None => self.queue.push_back(c),
                }
                if self.arrived < self.total {
                    s.after(self.cfg.interarrival.sample(&mut self.arr_rng), Ev::Arrival);
                } else {
                    // Close the measurement window at the last arrival so the
                    // drain-out does not bias L and utilisation.
                    self.window = self.window.map(|(a, _)| (a, now));
                    self.snapshot = (self.in_system.mean(now), self.busy_servers.mean(now));
                }
            }
            Ev::Departure { server } => {
                let c = self.busy[server].take().expect("busy server");
                self.sojourns[c.idx] = now - c.arrival;
                self.in_system.add(now, -1.0);
                self.busy_servers.add(now, -1.0);
                if let Some(next) = self.queue.pop_front() {
                    self.start(server, next, s);
                }
            }
        }
    }
}

fn streams(seed: u64) -> (StdRng, StdRng) {
    (
        StdRng::seed_from_u64(seed),
        StdRng::seed_from_u64(seed ^ 0x9E37_79B9_7F4A_7C15),
    )
}

/// Simulate the queue and report steady-state estimates (20 batch means).
pub fn simulate(cfg: &QueueConfig) -> QueueReport {
    assert!(cfg.servers >= 1 && cfg.customers >= 20);
    let mut m = Ggc::new(cfg.clone());
    let mut s = Scheduler::new();
    s.after(m.cfg.interarrival.sample(&mut m.arr_rng), Ev::Arrival);
    run(&mut m, &mut s, f64::INFINITY);

    let w0 = cfg.warmup;
    let waits = m.waits[w0..].to_vec();
    let sojourns = m.sojourns[w0..].to_vec();
    let (t0, t1) = m.window.expect("window opened");
    QueueReport {
        wait: batch_means(&waits, 20),
        sojourn: batch_means(&sojourns, 20),
        waits,
        sojourns,
        mean_in_system: m.snapshot.0,
        arrival_rate: (cfg.customers - 1) as f64 / (t1 - t0),
        utilization: m.snapshot.1 / cfg.servers as f64,
        service: m.service,
    }
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
