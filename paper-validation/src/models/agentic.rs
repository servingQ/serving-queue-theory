//! Agent programs sharing one replica with finite KV memory (paper §2.2–2.3, §3).
//!
//! This is the chain of §2 made executable:
//!
//! ```text
//! eviction policy → hit rate p → (E[S], E[S²]) → (ρ, E[Wq]) → throughput
//! ```
//!
//! Each program cycles `queue → service (prefill + decode) → tool → queue`
//! and grows its context every turn. Its KV stays resident during the tool
//! call, which is what creates memory pressure. When a turn needs memory
//! that is not free, suspended programs are evicted in the order given by an
//! [`EvictionPolicy`]; an evicted program either loses its KV (and its next
//! turn re-prefills the whole context, a miss) or is written to a slower
//! tier according to an [`OffloadPolicy`].
//!
//! Hit/miss status is not drawn from a fixed `p`: it emerges from memory
//! state, so the correlation between turns that the PK model ignores is
//! present. What is *not* modelled: continuous batching (the replica serves
//! one turn at a time, with per-turn costs taken as amortised), block
//! granularity, and partial prefix hits.

use crate::Dist;
use crate::analytic::pk_wait;
use crate::stats::{Estimate, Welford};

/// Per-turn service time as a function of tokens.
///
/// Prefilling `new` tokens on top of `cached` resident ones costs
/// `overhead + linear·new + quadratic·new·(cached + new/2)`: the last term is
/// attention over the prefix, so a full re-prefill of a context `c` is
/// quadratic in `c` (ThunderAgent Lemma 4.1). Decoding `out` tokens over a
/// context of `K` tokens costs `out·(decode_per_token + decode_kv·K)`: a
/// decode step reads the weights (`decode_per_token`, amortised over the
/// batch by the server model) and the turn's own KV (`decode_kv` per
/// context token, not amortised). With `decode_kv = 0` this is the
/// original context-free decode term.
#[derive(Clone, Debug)]
pub struct CostModel {
    pub overhead: f64,
    pub prefill_linear: f64,
    pub prefill_quadratic: f64,
    pub decode_per_token: f64,
    /// Decode time per output token per context token (KV read).
    pub decode_kv: f64,
}

impl CostModel {
    pub fn prefill(&self, new: f64, cached: f64) -> f64 {
        self.prefill_linear * new + self.prefill_quadratic * new * (cached + 0.5 * new)
    }

    /// Decode work of `out` output tokens over a context of `context`
    /// tokens (seconds at an otherwise idle device):
    /// `out·(decode_per_token + decode_kv·context)`.
    pub fn decode(&self, out: f64, context: f64) -> f64 {
        out * (self.decode_per_token + self.decode_kv * context)
    }

    /// Service time of a turn that appends `new` tokens to a resident
    /// prefix of `cached` tokens and decodes `out` tokens.
    pub fn turn(&self, new: f64, cached: f64, out: f64) -> f64 {
        self.overhead + self.prefill(new, cached) + self.decode(out, cached + new)
    }

    /// Extra service a miss pays over a hit for a context of `c` tokens:
    /// re-prefilling the prefix. `ΔS_i` of Eq. (utility).
    pub fn miss_penalty(&self, c: f64) -> f64 {
        self.prefill(c, 0.0)
    }
}

/// A class of agent programs.
#[derive(Clone, Debug)]
pub struct ProgramClass {
    /// Relative frequency among new programs.
    pub weight: f64,
    /// Probability that the program issues another turn when its tool call
    /// returns (the resume probability `p_i` of Prop. evict (iii)). It is
    /// drawn only then, so a suspended program holds KV that may never be
    /// reused. Turns per program are geometric with mean
    /// `1/(1 - resume_prob)`.
    pub resume_prob: f64,
    /// Tokens of the first turn (system prompt + task), all uncached.
    pub initial_tokens: Dist,
    /// New tokens appended per later turn (tool output, user input).
    pub new_tokens: Dist,
    /// Decoded tokens per turn.
    pub output_tokens: Dist,
    /// Tool (think) time after a turn.
    pub tool_time: Dist,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Population {
    /// `programs` concurrent programs; a finished one is replaced at once
    /// (the fixed-concurrency benchmark of ThunderAgent).
    Closed { programs: usize },
    /// New programs arrive as a Poisson process with `rate` per second.
    Open { rate: f64 },
}

/// Which suspended programs lose their KV first.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EvictionPolicy {
    /// Smallest context first (ThunderAgent Def. 4.1 / App. F.3).
    ShortestFirst,
    LongestFirst,
    /// Least recently served first.
    Lru,
    /// Uniformly random order.
    Random,
    /// Increasing expected recompute cost per token freed,
    /// `p_i ΔS_i / c_i`: the greedy rule for the knapsack relaxation
    /// (Dantzig 1957), with Eq. utility's cost less its common `1/(1-ρ)`.
    Density,
    /// Increasing congestion price per token freed, `q_i Φ_i / c_i`, with
    /// `Φ_i` the price of a miss (paper Prop. price, `missPrice`):
    ///
    /// `Φ_i = ΔS_i + λ̂(s_m² - s_h²)/(2(1-ρ̂)) + λ̂ Ŵ ΔS_i/(1-ρ̂)`,
    ///
    /// `q_i` the resume probability (1 for a queued program, as in
    /// `Density`), `s_h` the hit service of the program's next turn at the
    /// class-mean new and output tokens, `s_m = s_h + ΔS_i` and
    /// `ΔS_i = miss_penalty(c_i)`. `λ̂, ρ̂, Ŵ` are online estimates, see
    /// seQ estimates the load online. Unlike `Density`, the order depends on load:
    /// the own-length term `λ(s_m² - s_h²)/(2(1-ρ))` grows like `ΔS²`, so
    /// near saturation long recomputes are priced above their share of work.
    /// Plain density order, not the guarded greedy of Prop. guarded; see
    /// the doc comment of `evict` for why.
    Priced,
    /// Increasing price per byte-second, `q_i Φ_i / (c_i τ_i)`, with `τ_i`
    /// the expected remaining suspension of the program: the mean tool time
    /// of its class while it is in a tool call, a common constant while it
    /// waits for admission (so within each eviction phase only the tool-call
    /// order changes). The threshold rule of paper Prop. memory (i)
    /// (`threshold_rule_optimal`): the shadow price `θ` of memory is per
    /// byte-second, so a state that would sit idle longer is cheaper to
    /// drop per unit of the resource it frees.
    PricedMemory,
    /// Block-level [`PricedMemory`](Self::PricedMemory): evict blocks of
    /// `block_tokens` from the tail of a context, cheapest per byte-second
    /// first, `q_i Φ(ΔP) / (m τ_i)` with `ΔP = a·m + b·m·(K - m/2)` the cost
    /// of re-prefilling the `m` evicted tokens over the kept prefix (paper
    /// Prop. memory (ii), `density_prefix_plus_one`). A partial miss then
    /// re-prefills only the evicted suffix. Implemented in
    /// [`super::batch`] only.
    PricedMemoryBlocks,
}

/// What happens to an evicted program's KV.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OffloadPolicy {
    /// Drop it; the next turn recomputes.
    Never,
    /// Always write it to the tier and always fetch it back.
    Always,
    /// Per program `argmin` of Prop. option. A recompute adds `ΔS` of work
    /// to the replica and delays the `Q` turns queued behind it, so its cost
    /// is taken as `ΔS·(1+Q)` (the congestion factor of Eq. utility); a
    /// transfer costs its tier wait plus duration. With async fetch, write
    /// on eviction iff `transfer < p_i·ΔS·(1+Q)` and fetch on resume iff
    /// `transfer < ΔS·(1+Q)`. With [`FetchMode::Blocking`] both options hold
    /// the replica, so the write and fetch tests use `p_i·ΔS` and `ΔS`.
    Selective,
    /// As `Selective`, with the price of a miss `Φ` (see
    /// [`EvictionPolicy::Priced`]) in place of `ΔS·(1+Q)`. Async: write iff
    /// `transfer < p_i·Φ`, fetch iff `transfer < Φ` (the transfer delays
    /// only this turn). Blocking: a fetch stalls the replica for the
    /// transfer, which is priced like extra service; `Φ` is increasing in
    /// the extra service, so both tests reduce to `transfer < ΔS`.
    Priced,
}

/// How a fetch from the offload tier interacts with the replica.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FetchMode {
    /// The fetch completes before the turn joins the replica queue; the
    /// replica keeps serving others meanwhile.
    Async,
    /// The fetch starts when the turn reaches the replica and the replica
    /// waits for it (tier queue plus transfer), as when KV loading sits on
    /// the critical path of the batch.
    Blocking,
}

#[derive(Clone, Debug)]
pub struct AgenticConfig {
    pub population: Population,
    pub classes: Vec<ProgramClass>,
    pub cost: CostModel,
    /// Device KV capacity, tokens.
    pub kv_capacity: f64,
    /// A program ends once its context exceeds this (default: half of
    /// capacity), so a single program always fits.
    pub max_context: f64,
    pub eviction: EvictionPolicy,
    pub offload: OffloadPolicy,
    /// Offload-tier bandwidth, tokens per second (read and write share it).
    pub tier_bandwidth: f64,
    pub fetch: FetchMode,
    pub warmup: f64,
    pub horizon: f64,
    pub seed: u64,
}

impl AgenticConfig {
    /// A coding-agent-like workload. Numbers are illustrative, not
    /// measured: 20k-token initial context, 1k new and 300 output tokens per
    /// turn, 90 % resume probability, 3 s tool time. A hit costs ~0.1 s and a
    /// miss of a 30k context ~1–2 s.
    pub fn example(programs: usize, kv_capacity: f64) -> Self {
        Self {
            population: Population::Closed { programs },
            classes: vec![ProgramClass {
                weight: 1.0,
                resume_prob: 0.9,
                initial_tokens: Dist::Uniform {
                    lo: 10_000.0,
                    hi: 30_000.0,
                },
                new_tokens: Dist::exp(1_000.0),
                output_tokens: Dist::exp(300.0),
                tool_time: Dist::exp(3.0),
            }],
            cost: CostModel {
                overhead: 0.005,
                prefill_linear: 2.0e-5,
                prefill_quadratic: 2.0e-9,
                decode_per_token: 2.0e-4,
                decode_kv: 0.0,
            },
            kv_capacity,
            max_context: 0.5 * kv_capacity,
            eviction: EvictionPolicy::ShortestFirst,
            offload: OffloadPolicy::Never,
            tier_bandwidth: 1.0e6,
            fetch: FetchMode::Async,
            warmup: 500.0,
            horizon: 5_500.0,
            seed: 1,
        }
    }
}

#[derive(Clone, Debug)]
pub struct AgenticReport {
    /// Turns completed in the measurement window.
    pub turns: u64,
    /// Turns per second.
    pub throughput: f64,
    /// Fraction of follow-up turns (turn ≥ 2) whose prefix was available
    /// (resident, or fetched from the tier).
    pub hit_rate: f64,
    /// Service time of every turn.
    pub service: Welford,
    /// Wait in the replica queue per turn, in completion order.
    pub waits: Vec<f64>,
    pub wait: Estimate,
    /// Ready (tool done) to turn done, including any tier fetch.
    pub response: Welford,
    /// Think time after each completed turn (0 when the program hit
    /// `max_context` and was replaced at once).
    pub think: Welford,
    pub utilization: f64,
    pub mean_resident_kv: f64,
    /// Time-average number of live programs.
    pub mean_programs: f64,
    pub evictions: u64,
    pub offload_writes: u64,
    pub fetches: u64,
    pub recomputes: u64,
    pub truncated: u64,
    pub tier_utilization: f64,
    /// Replica seconds per second spent re-prefilling evicted prefixes.
    pub recompute_load: f64,
    /// Replica seconds per second stalled on blocking fetches.
    pub stall_load: f64,
}

impl AgenticReport {
    /// PK prediction from the *measured* turn rate and service moments,
    /// i.e. what the model of §2.2 would say given this hit rate.
    /// `NaN` when the measured load is not below one (PK does not apply).
    pub fn pk_wait_prediction(&self) -> f64 {
        let lam = self.throughput;
        let rho = lam * self.service.mean();
        if rho >= 1.0 {
            return f64::NAN;
        }
        pk_wait(lam, self.service.second_moment(), rho)
    }

    /// Interactive response-time law residual `|N - X(R + Z)| / N` for a
    /// closed population of `n` programs.
    pub fn irtl_residual(&self, n: f64) -> f64 {
        (n - self.throughput * (self.response.mean() + self.think.mean())).abs() / n
    }
}

/// Run the configured agentic system in seQ.
pub fn simulate(cfg: &AgenticConfig) -> AgenticReport {
    super::agentic_seq::simulate(cfg)
}
