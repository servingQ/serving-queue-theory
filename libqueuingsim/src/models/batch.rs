//! Sampled-work FIFO and processor-sharing session checks for the paper.
//! The arrival, service, feedback and batch-cap behavior executes in
//! `programs/batch_sampled.seq`; this module holds its configuration,
//! report shape, and analytic helpers.

use std::cmp::Ordering;

use rand::Rng;

use crate::Dist;
use crate::analytic::stationary_mean;
use crate::stats::{Estimate, Welford};

pub use super::agentic::{Population, ProgramClass};

/// Service capacity `φ(n)` of a batch of `n` turns, in work-seconds per
/// second.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Phi {
    /// `φ(n) = c` for `n ≥ 1`: plain processor sharing at rate `c`.
    Constant(f64),
    /// `φ(n) = m/(1+β(m-1))` with `m = min(n, cap)`: rises from 1 and
    /// saturates at `1/β` (or at `φ(cap)`, the theory's model of a batch
    /// cap). `β = 0` with a cap gives `min(n, cap)`.
    Saturating { beta: f64, cap: Option<usize> },
}

impl Phi {
    pub fn rate(&self, n: usize) -> f64 {
        if n == 0 {
            return 0.0;
        }
        match *self {
            Phi::Constant(c) => c,
            Phi::Saturating { beta, cap } => {
                let m = cap.map_or(n, |c| n.min(c)) as f64;
                m / (1.0 + beta * (m - 1.0))
            }
        }
    }

    /// `sup_n φ(n)`, the saturation throughput in work-seconds per second.
    pub fn limit(&self) -> f64 {
        match *self {
            Phi::Constant(c) => c,
            Phi::Saturating { cap: Some(c), .. } => self.rate(c),
            Phi::Saturating { beta, cap: None } if beta > 0.0 => 1.0 / beta,
            Phi::Saturating { .. } => f64::INFINITY,
        }
    }
}

/// Mean number of turns in a PS queue with capacity `φ` and offered load
/// `rho = λ E[S]` (work-seconds per second): `Σ n π(n)` with
/// `π(n) ∝ ρⁿ / Π_{k≤n} φ(k)`. Insensitive to the service law beyond its
/// mean. For `φ ≡ C` this is `ρ/(C-ρ)`.
pub fn ps_mean_number(phi: &Phi, rho: f64) -> f64 {
    assert!(rho < phi.limit(), "load {rho} ≥ capacity {}", phi.limit());
    // Weights w(n) = a(n)ρⁿ, a(n) = 1/(φ(1)⋯φ(n)), formed as products so
    // they neither overflow nor underflow; truncate where negligible.
    let mut w = vec![1.0];
    let mut z = 1.0;
    for n in 1..10_000_000usize {
        let wn = w[n - 1] * rho / phi.rate(n);
        w.push(wn);
        z += wn;
        if wn < 1e-16 * z && n > 10 {
            break;
        }
    }
    stationary_mean(&w, 1.0)
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Server {
    /// One turn at a time at rate 1 (batch cap 1).
    Fifo,
    /// Continuous batching with chunked prefill as one PS station of
    /// capacity `φ`.
    Ps { phi: Phi },
}

/// Where a turn's work comes from.
#[derive(Clone, Debug, PartialEq)]
pub enum Work {
    /// I.i.d. prefill and decode work per turn, independent of KV state
    /// (for the in-model checks). The work is drawn when the turn becomes
    /// ready, from its own random stream, so two runs that differ only in
    /// these laws see the same turns (common random numbers).
    Sampled { prefill: Dist, decode: Dist },
}

#[derive(Clone, Debug)]
pub struct BatchConfig {
    pub population: Population,
    /// One session class; its resume probability and tool time shape feedback.
    pub classes: Vec<ProgramClass>,
    pub work: Work,
    pub server: Server,
    /// Exact LPS: at most this many turns admitted to the batch.
    pub batch_cap: Option<usize>,
    pub warmup: f64,
    pub horizon: f64,
    pub seed: u64,
}

impl BatchConfig {
    /// Open Poisson turns (`p = 0`, one turn per session) with i.i.d. work
    /// `service`: the M/G/· queue of the in-model checks.
    pub fn poisson_turns(
        rate: f64,
        service: Dist,
        server: Server,
        horizon: f64,
        seed: u64,
    ) -> Self {
        Self {
            population: Population::Open { rate },
            classes: vec![ProgramClass {
                weight: 1.0,
                resume_prob: 0.0,
                initial_tokens: Dist::Deterministic(0.0),
                new_tokens: Dist::Deterministic(0.0),
                output_tokens: Dist::Deterministic(0.0),
                tool_time: Dist::Deterministic(0.0),
            }],
            work: Work::Sampled {
                prefill: service,
                decode: Dist::Deterministic(0.0),
            },
            server,
            batch_cap: None,
            warmup: 0.05 * horizon,
            horizon,
            seed,
        }
    }
}

#[derive(Clone, Debug)]
pub struct BatchReport {
    /// Turns completed in the measurement window, and per second.
    pub turns: u64,
    pub throughput: f64,
    pub sessions_done: u64,
    /// Fraction of follow-up turns whose whole context was resident at
    /// admission.
    pub hit_rate: f64,
    /// Ready (tool done) to turn done, for turns ready after warm-up.
    pub response: Welford,
    /// `(turn sequence number, response)` sorted by sequence number, i.e.
    /// by the order in which turns became ready.
    pub responses: Vec<(u64, f64)>,
    /// Batch-means CI of the mean response.
    pub response_ci: Estimate,
    pub p99: f64,
    /// Time to first token, ready → prefill done (blocking prefill; empty
    /// otherwise).
    pub ttft: Welford,
    pub ttfts: Vec<(u64, f64)>,
    pub ttft_ci: Estimate,
    pub ttft_p99: f64,
    /// Ready to admitted.
    pub wait: Welford,
    /// Work per turn (seconds at rate 1).
    pub work: Welford,
    /// Time-average number of turns at the replica (waiting + admitted).
    pub mean_number: f64,
    /// Time-average number admitted (the batch).
    pub mean_batch: f64,
    /// Time-average number in the prefill stage (waiting for admission,
    /// waiting for or under prefill).
    pub mean_prefill_number: f64,
    /// Time-average number in the decode batch.
    pub mean_decode_number: f64,
    /// Time-average device availability for prefill (1: every server here
    /// gives prefill the whole device).
    pub mean_availability: f64,
    /// Fraction of time with at least one admitted turn.
    pub utilization: f64,
    pub mean_resident_kv: f64,
    pub mean_sessions: f64,
    pub mean_entry_queue: f64,
    /// Entry-queue wait of sessions started after warm-up (0 if none waited).
    pub entry_wait: Welford,
    pub evictions: u64,
    /// Follow-up turns that re-prefilled part or all of their context.
    pub recomputes: u64,
    /// Context tokens re-prefilled by follow-up turns.
    pub recomputed_tokens: f64,
    pub truncated: u64,
}

/// Run the sampled-work session model in seQ.
pub fn simulate(cfg: &BatchConfig) -> BatchReport {
    super::batch_seq::simulate(cfg)
}

/// Per-turn differences `b - a` of two per-turn series (e.g.
/// [`BatchReport::responses`]) of runs with common random numbers, paired
/// by turn sequence number.
pub fn paired_differences(a: &[(u64, f64)], b: &[(u64, f64)]) -> Vec<f64> {
    let (mut i, mut j, mut out) = (0, 0, vec![]);
    while i < a.len() && j < b.len() {
        match a[i].0.cmp(&b[j].0) {
            Ordering::Less => i += 1,
            Ordering::Greater => j += 1,
            Ordering::Equal => {
                out.push(b[j].1 - a[i].1);
                i += 1;
                j += 1;
            }
        }
    }
    out
}

/// Number of requests admitted, in FIFO order, into memory `capacity`
/// until the first whose footprint (drawn from `footprint`) does not fit.
pub fn fifo_admitted<R: Rng + ?Sized>(capacity: f64, footprint: &Dist, rng: &mut R) -> usize {
    let (mut used, mut n) = (0.0, 0);
    loop {
        let k = footprint.sample(rng);
        if used + k > capacity {
            return n;
        }
        used += k;
        n += 1;
    }
}
