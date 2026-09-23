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

use std::collections::VecDeque;

use rand::SeedableRng;
use rand::rngs::StdRng;

use crate::dist::Dist;
use crate::engine::{Model, Scheduler, run};
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

#[derive(Clone, Copy)]
struct Job {
    arrival: f64,
    prefill: f64,
    decode: f64,
    kv: f64,
}

struct Station {
    servers: usize,
    busy: usize,
    queue: VecDeque<Job>,
    busy_time: f64,
}

enum Ev {
    Arrival,
    Done { station: usize, job: Job },
}

struct Pd {
    cfg: PdConfig,
    rng: StdRng,
    stations: Vec<Station>,
    completed: usize,
    t_warm: f64,
    latencies: Vec<f64>,
}

impl Pd {
    fn new_job(&mut self, now: f64) -> Job {
        Job {
            arrival: now,
            prefill: self.cfg.prefill.sample(&mut self.rng),
            decode: self.cfg.decode.sample(&mut self.rng),
            kv: self.cfg.kv_tokens.sample(&mut self.rng),
        }
    }

    fn service(&self, station: usize, j: &Job) -> f64 {
        match (self.cfg.mode, station) {
            (Mode::Aggregated, _) => j.prefill + j.decode + self.cfg.interference,
            (Mode::Disaggregated { .. }, 0) => j.prefill / self.cfg.gain_prefill,
            (Mode::Disaggregated { .. }, 1) => j.kv / self.cfg.b_net,
            (Mode::Disaggregated { .. }, _) => j.decode / self.cfg.gain_decode,
        }
    }

    fn arrive_at(&mut self, station: usize, job: Job, s: &mut Scheduler<Ev>) {
        if self.stations[station].busy < self.stations[station].servers {
            let d = self.service(station, &job);
            let st = &mut self.stations[station];
            st.busy += 1;
            if self.completed >= self.cfg.warmup {
                st.busy_time += d;
            }
            s.after(d, Ev::Done { station, job });
        } else {
            self.stations[station].queue.push_back(job);
        }
    }

    fn enter(&mut self, s: &mut Scheduler<Ev>) {
        let job = self.new_job(s.now());
        self.arrive_at(0, job, s);
    }
}

impl Model for Pd {
    type Event = Ev;

    fn handle(&mut self, ev: Ev, s: &mut Scheduler<Ev>) {
        let now = s.now();
        match ev {
            Ev::Arrival => {
                if let Load::Poisson { rate } = self.cfg.load {
                    s.after(Dist::exp(1.0 / rate).sample(&mut self.rng), Ev::Arrival);
                }
                self.enter(s);
            }
            Ev::Done { station, job } => {
                self.stations[station].busy -= 1;
                if let Some(next) = self.stations[station].queue.pop_front() {
                    self.arrive_at(station, next, s);
                }
                if station + 1 < self.stations.len() {
                    self.arrive_at(station + 1, job, s);
                    return;
                }
                self.completed += 1;
                if self.completed == self.cfg.warmup {
                    self.t_warm = now;
                } else if self.completed > self.cfg.warmup {
                    self.latencies.push(now - job.arrival);
                }
                if let Load::Saturated { .. } = self.cfg.load {
                    self.enter(s);
                }
            }
        }
    }

    fn finished(&self) -> bool {
        self.completed >= self.cfg.warmup + self.cfg.requests
    }
}

pub fn simulate(cfg: &PdConfig) -> PdReport {
    let station = |servers| Station {
        servers,
        busy: 0,
        queue: VecDeque::new(),
        busy_time: 0.0,
    };
    let stations = match cfg.mode {
        Mode::Aggregated => vec![station(cfg.devices)],
        Mode::Disaggregated { prefill_devices } => {
            assert!(0 < prefill_devices && prefill_devices < cfg.devices);
            vec![
                station(prefill_devices),
                station(1),
                station(cfg.devices - prefill_devices),
            ]
        }
    };
    let mut m = Pd {
        cfg: cfg.clone(),
        rng: StdRng::seed_from_u64(cfg.seed),
        stations,
        completed: 0,
        t_warm: 0.0,
        latencies: Vec::with_capacity(cfg.requests),
    };
    let mut s = Scheduler::new();
    match cfg.load {
        Load::Saturated { jobs } => (0..jobs).for_each(|_| m.enter(&mut s)),
        Load::Poisson { .. } => s.at(0.0, Ev::Arrival),
    }
    let end = run(&mut m, &mut s, f64::INFINITY);
    let span = end - m.t_warm;
    let mut latency_stats = Welford::new();
    m.latencies.iter().for_each(|&x| latency_stats.push(x));
    PdReport {
        throughput: cfg.requests as f64 / span,
        latency: batch_means(&m.latencies, 20),
        station_utilization: m
            .stations
            .iter()
            .map(|st| st.busy_time / (span * st.servers as f64))
            .collect(),
        latencies: m.latencies,
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
}
