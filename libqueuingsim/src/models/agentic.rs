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

use std::collections::VecDeque;

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};

use crate::analytic::{miss_price_given_wait, pk_wait};
use crate::dist::Dist;
use crate::engine::{Model, Scheduler, run};
use crate::stats::{Estimate, TimeAverage, Welford, batch_means};

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
    /// [`PriceEstimator`]. Unlike `Density`, the order depends on load:
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
    /// transfer costs its tier wait plus duration. Write on eviction iff
    /// `transfer < p_i·ΔS·(1+Q)`; fetch on resume iff `transfer < ΔS·(1+Q)`.
    /// With [`FetchMode::Blocking`] both options hold the replica, so the
    /// fetch test is `transfer < ΔS`.
    Selective,
    /// As `Selective`, with the price of a miss `Φ` (see
    /// [`EvictionPolicy::Priced`]) in place of `ΔS·(1+Q)`. Async: write iff
    /// `transfer < p_i·Φ`, fetch iff `transfer < Φ` (the transfer delays
    /// only this turn). Blocking: a fetch stalls the replica for the
    /// transfer, which is priced like extra service; `Φ` is increasing in
    /// the extra service, so both tests reduce to `transfer < ΔS`.
    Priced,
}

/// Online estimates of the quantities in the price of a miss, from what a
/// replica observes. Updated at every service start (warm-up included) as
/// exponentially weighted averages over turns with weight `ALPHA`:
/// the gap between service starts (so `λ̂` = 1 / mean gap, the turn rate),
/// the service time `ŝ`, and the queue wait `Ŵ` of the turn starting.
/// `ρ̂ = min(λ̂ ŝ, RHO_CAP)`. `Ŵ` is the measured wait, not PK from the
/// service moments, because turn arrivals of a closed population are not
/// Poisson. Before the first gap is seen `λ̂ = 0`, so `Φ = ΔS` and
/// `Priced` coincides with `Density`.
#[derive(Clone, Debug, Default)]
pub struct PriceEstimator {
    last_start: Option<f64>,
    gap: Option<f64>,
    service: f64,
    wait: f64,
    seen: u64,
}

impl PriceEstimator {
    pub const ALPHA: f64 = 0.01;
    pub const RHO_CAP: f64 = 0.99;

    fn ewma(old: f64, x: f64, first: bool) -> f64 {
        if first {
            x
        } else {
            (1.0 - Self::ALPHA) * old + Self::ALPHA * x
        }
    }

    /// Record a turn that starts service at `now` after waiting `wait`.
    pub fn observe(&mut self, now: f64, wait: f64, service: f64) {
        let first = self.seen == 0;
        self.service = Self::ewma(self.service, service, first);
        self.wait = Self::ewma(self.wait, wait, first);
        if let Some(t) = self.last_start {
            self.gap = Some(match self.gap {
                None => now - t,
                Some(g) => Self::ewma(g, now - t, false),
            });
        }
        self.last_start = Some(now);
        self.seen += 1;
    }

    /// `(λ̂, ρ̂, Ŵ)`.
    pub fn estimates(&self) -> (f64, f64, f64) {
        match self.gap {
            Some(g) if g > 0.0 => {
                let lam = 1.0 / g;
                (lam, (lam * self.service).min(Self::RHO_CAP), self.wait)
            }
            _ => (0.0, 0.0, self.wait),
        }
    }

    /// `Φ` for a turn of hit service `s_h` that a miss lengthens by `ds`.
    pub fn price(&self, s_h: f64, ds: f64) -> f64 {
        let (lam, rho, w) = self.estimates();
        miss_price_given_wait(lam, w, rho, s_h, s_h + ds)
    }
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

/// How a traced turn's prefix was obtained.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TurnKind {
    /// First turn of a session: the whole initial context is prefilled.
    Cold,
    /// Follow-up whose prefix was resident (or fetched from the tier).
    Hit,
    /// Follow-up whose prefix was evicted, wholly or (block eviction in
    /// [`super::batch`]) in part: the missing context is re-prefilled.
    Miss,
}

/// One served turn, for visualisation ([`simulate_traced`],
/// [`super::batch::simulate_traced`]). Times are simulation seconds from 0,
/// warm-up included.
/// `enqueued ≤ admitted ≤ start ≤ prefill_end ≤ end`.
#[derive(Clone, Debug, PartialEq)]
pub struct TurnSpan {
    /// Session serial number, in order of arrival (slots are reused, serials
    /// are not).
    pub session: u64,
    /// Turn index within the session, from 1.
    pub turn: u32,
    pub kind: TurnKind,
    /// Joined the replica queue.
    pub enqueued: f64,
    /// Admitted to the batch (KV reserved). Equal to `start` here; in
    /// [`super::batch`] a turn may then wait in the prefill FIFO.
    pub admitted: f64,
    /// Prefill start. The prefill phase `[start, prefill_end)` includes the
    /// per-turn overhead and any blocking fetch stall.
    pub start: f64,
    pub prefill_end: f64,
    /// Decode phase `[prefill_end, end)`.
    pub end: f64,
    /// Context tokens after the turn.
    pub context: f64,
    /// Tokens prefilled: the new tokens on a hit or a cold turn, the
    /// missing context plus the new tokens on a miss.
    pub prefill_tokens: f64,
    /// Resident prefix reused (0 on a cold turn or a whole miss).
    pub cached_tokens: f64,
    /// Tokens decoded.
    pub decode_tokens: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Residency {
    /// First turn, never prefilled.
    Cold,
    Resident,
    Offloaded,
    Dropped,
    /// Fetched from the tier, waiting in the replica queue.
    Staged,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Phase {
    Queued,
    Fetching,
    InService,
    Tool,
    Dead,
}

#[derive(Clone, Debug)]
struct Program {
    class: usize,
    context: f64,
    kv: f64,
    residency: Residency,
    phase: Phase,
    turns: u32,
    ready_at: f64,
    enqueued_at: f64,
    last_used: f64,
    serial: u64,
}

enum Ev {
    ProgramArrival,
    ToolDone(usize),
    FetchDone(usize),
    ServiceDone(usize),
    EndWarmup,
}

struct Agentic {
    cfg: AgenticConfig,
    rng: StdRng,
    programs: Vec<Program>,
    free_slots: Vec<usize>,
    queue: VecDeque<usize>,
    in_service: Option<(usize, bool, f64)>,
    used_kv: f64,
    tier_free_at: f64,
    warm: bool,
    price: PriceEstimator,
    next_serial: u64,
    trace: Option<Vec<TurnSpan>>,
    // statistics
    turns: u64,
    follow_ups: u64,
    hits: u64,
    service: Welford,
    waits: Vec<f64>,
    response: Welford,
    think: Welford,
    busy: TimeAverage,
    resident: TimeAverage,
    live: TimeAverage,
    tier_busy: f64,
    evictions: u64,
    offload_writes: u64,
    fetches: u64,
    recomputes: u64,
    truncated: u64,
    recompute_time: f64,
    stall_time: f64,
}

impl Agentic {
    fn new(cfg: AgenticConfig) -> Self {
        assert!(!cfg.classes.is_empty());
        assert!(cfg.max_context < cfg.kv_capacity);
        assert!(cfg.warmup < cfg.horizon);
        let rng = StdRng::seed_from_u64(cfg.seed);
        Self {
            cfg,
            rng,
            programs: Vec::new(),
            free_slots: Vec::new(),
            queue: VecDeque::new(),
            in_service: None,
            used_kv: 0.0,
            tier_free_at: 0.0,
            warm: false,
            price: PriceEstimator::default(),
            next_serial: 0,
            trace: None,
            turns: 0,
            follow_ups: 0,
            hits: 0,
            service: Welford::new(),
            waits: Vec::new(),
            response: Welford::new(),
            think: Welford::new(),
            busy: TimeAverage::new(0.0, 0.0),
            resident: TimeAverage::new(0.0, 0.0),
            live: TimeAverage::new(0.0, 0.0),
            tier_busy: 0.0,
            evictions: 0,
            offload_writes: 0,
            fetches: 0,
            recomputes: 0,
            truncated: 0,
            recompute_time: 0.0,
            stall_time: 0.0,
        }
    }

    fn pick_class(&mut self) -> usize {
        let total: f64 = self.cfg.classes.iter().map(|c| c.weight).sum();
        let mut u = self.rng.random::<f64>() * total;
        for (i, c) in self.cfg.classes.iter().enumerate() {
            if u < c.weight {
                return i;
            }
            u -= c.weight;
        }
        self.cfg.classes.len() - 1
    }

    fn spawn(&mut self, s: &mut Scheduler<Ev>) {
        let now = s.now();
        let class = self.pick_class();
        let p = Program {
            class,
            context: 0.0,
            kv: 0.0,
            residency: Residency::Cold,
            phase: Phase::Queued,
            turns: 0,
            ready_at: now,
            enqueued_at: now,
            last_used: now,
            serial: self.next_serial,
        };
        self.next_serial += 1;
        let id = match self.free_slots.pop() {
            Some(id) => {
                self.programs[id] = p;
                id
            }
            None => {
                self.programs.push(p);
                self.programs.len() - 1
            }
        };
        self.live.add(now, 1.0);
        self.enqueue(id, s);
    }

    fn enqueue(&mut self, id: usize, s: &mut Scheduler<Ev>) {
        let p = &mut self.programs[id];
        p.phase = Phase::Queued;
        p.enqueued_at = s.now();
        self.queue.push_back(id);
        if self.in_service.is_none() {
            self.start_next(s);
        }
    }

    fn tier_transfer(&mut self, now: f64, tokens: f64) -> f64 {
        let start = self.tier_free_at.max(now);
        let dur = tokens / self.cfg.tier_bandwidth;
        self.tier_free_at = start + dur;
        if self.warm {
            self.tier_busy += dur;
        }
        self.tier_free_at
    }

    fn tier_backlog(&self, now: f64) -> f64 {
        (self.tier_free_at - now).max(0.0)
    }

    /// System cost of recomputing a `c`-token prefix now (see
    /// [`OffloadPolicy::Selective`]).
    fn recompute_cost(&self, c: f64) -> f64 {
        self.cfg.cost.miss_penalty(c) * (1.0 + self.queue.len() as f64)
    }

    /// Price of a miss (Prop. price) for program `id` if its next turn
    /// were a miss of a `c`-token prefix, from the online estimates.
    fn miss_price(&self, id: usize, c: f64) -> f64 {
        let cls = &self.cfg.classes[self.programs[id].class];
        let s_h = self
            .cfg
            .cost
            .turn(cls.new_tokens.mean(), c, cls.output_tokens.mean());
        self.price.price(s_h, self.cfg.cost.miss_penalty(c))
    }

    /// Resume probability of a program as seen at eviction time: a queued
    /// program resumes with certainty.
    fn resume_prob(&self, id: usize) -> f64 {
        let p = &self.programs[id];
        if p.phase == Phase::Tool {
            self.cfg.classes[p.class].resume_prob
        } else {
            1.0
        }
    }

    fn evict_key(&mut self, id: usize) -> f64 {
        let p = &self.programs[id];
        match self.cfg.eviction {
            EvictionPolicy::ShortestFirst => p.kv,
            EvictionPolicy::LongestFirst => -p.kv,
            EvictionPolicy::Lru => p.last_used,
            EvictionPolicy::Random => self.rng.random(),
            EvictionPolicy::Density => {
                let kv = p.kv;
                self.resume_prob(id) * self.cfg.cost.miss_penalty(kv) / kv
            }
            EvictionPolicy::Priced => {
                let kv = p.kv;
                self.resume_prob(id) * self.miss_price(id, kv) / kv
            }
            EvictionPolicy::PricedMemory => {
                let kv = p.kv;
                let tau = if p.phase == Phase::Tool {
                    self.cfg.classes[p.class].tool_time.mean()
                } else {
                    1.0
                };
                self.resume_prob(id) * self.miss_price(id, kv) / (kv * tau)
            }
            EvictionPolicy::PricedMemoryBlocks => {
                unimplemented!("block-level eviction is implemented in models::batch only")
            }
        }
    }

    /// Free at least `need` tokens, never touching `exclude`. Programs in a
    /// tool call are evicted before programs waiting in the queue. Every
    /// policy takes its order greedily until `need` is met; the guard of
    /// Prop. guarded is not applied online (it protects against a heavy
    /// item with good density, which with quadratic `ΔS` and bounded `q_i`
    /// is not the regime here).
    fn evict(&mut self, need: f64, exclude: usize, now: f64) {
        let mut freed = 0.0;
        for phase in [Phase::Tool, Phase::Queued] {
            let ids: Vec<usize> = (0..self.programs.len())
                .filter(|&i| {
                    i != exclude && self.programs[i].phase == phase && self.programs[i].kv > 0.0
                })
                .collect();
            let mut keyed: Vec<(f64, usize)> =
                ids.into_iter().map(|i| (self.evict_key(i), i)).collect();
            keyed.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
            for (_, i) in keyed {
                if freed >= need {
                    return;
                }
                freed += self.drop_kv(i, now);
            }
        }
        assert!(
            freed >= need - 1e-6,
            "cannot free {need} tokens; max_context too large for kv_capacity"
        );
    }

    fn drop_kv(&mut self, id: usize, now: f64) -> f64 {
        let tokens = self.programs[id].kv;
        self.used_kv -= tokens;
        self.resident.add(now, -tokens);
        self.evictions += 1;
        let p = &self.programs[id];
        let offload = p.phase == Phase::Tool
            && match self.cfg.offload {
                OffloadPolicy::Never => false,
                OffloadPolicy::Always => true,
                OffloadPolicy::Selective => {
                    let q = self.cfg.classes[p.class].resume_prob;
                    let transfer = self.tier_backlog(now) + tokens / self.cfg.tier_bandwidth;
                    transfer < q * self.recompute_cost(tokens)
                }
                OffloadPolicy::Priced => {
                    let q = self.cfg.classes[p.class].resume_prob;
                    let transfer = self.tier_backlog(now) + tokens / self.cfg.tier_bandwidth;
                    if self.cfg.fetch == FetchMode::Blocking {
                        transfer < self.cfg.cost.miss_penalty(tokens)
                    } else {
                        transfer < q * self.miss_price(id, tokens)
                    }
                }
            };
        let p = &mut self.programs[id];
        p.kv = 0.0;
        p.residency = if offload {
            Residency::Offloaded
        } else {
            Residency::Dropped
        };
        if offload {
            self.offload_writes += 1;
            self.tier_transfer(now, tokens);
        }
        tokens
    }

    fn start_next(&mut self, s: &mut Scheduler<Ev>) {
        debug_assert!(self.in_service.is_none(), "replica already busy");
        let now = s.now();
        while let Some(id) = self.queue.pop_front() {
            let class = self.programs[id].class;
            let first = self.programs[id].residency == Residency::Cold;
            let cls = &self.cfg.classes[class];
            let new = if first {
                cls.initial_tokens.sample(&mut self.rng)
            } else {
                cls.new_tokens.sample(&mut self.rng)
            };
            let out = cls.output_tokens.sample(&mut self.rng);
            let p = &self.programs[id];
            let target = p.context + new + out;
            if target > self.cfg.kv_capacity {
                self.truncated += 1;
                // `finish` may spawn a replacement whose enqueue already
                // started a service; the replica serves one turn at a time.
                self.finish(id, s);
                if self.in_service.is_some() {
                    return;
                }
                continue;
            }
            let context = p.context;
            // Blocking fetch: the replica waits for the tier.
            let mut stall = 0.0;
            if p.residency == Residency::Offloaded {
                let fetch = match self.cfg.offload {
                    OffloadPolicy::Never => false,
                    OffloadPolicy::Always => true,
                    // Both options hold the replica, so compare directly.
                    OffloadPolicy::Selective | OffloadPolicy::Priced => {
                        self.tier_backlog(now) + context / self.cfg.tier_bandwidth
                            < self.cfg.cost.miss_penalty(context)
                    }
                };
                if fetch {
                    stall = self.tier_transfer(now, context) - now;
                    if self.warm {
                        self.fetches += 1;
                    }
                }
                self.programs[id].residency = if fetch {
                    Residency::Staged
                } else {
                    Residency::Dropped
                };
            }
            let p = &self.programs[id];
            let hit = matches!(p.residency, Residency::Resident | Residency::Staged);
            let hit_service = self.cfg.cost.turn(new, context, out);
            let service = if first {
                self.cfg.cost.turn(new, 0.0, out)
            } else if hit {
                hit_service + stall
            } else {
                self.cfg.cost.turn(context + new, 0.0, out)
            };
            if self.warm && !first && !hit {
                self.recompute_time += service - hit_service;
            }
            if self.warm {
                self.stall_time += stall;
            }
            let extra = target - p.kv;
            let need = self.used_kv + extra - self.cfg.kv_capacity;
            if need > 0.0 {
                self.evict(need, id, now);
            }
            self.used_kv += extra;
            self.resident.add(now, extra);
            let wait = now - self.programs[id].enqueued_at;
            self.price.observe(now, wait, service);
            let p = &mut self.programs[id];
            p.kv = target;
            p.phase = Phase::InService;
            if self.warm {
                self.waits.push(now - p.enqueued_at);
                self.service.push(service);
                if !first {
                    self.follow_ups += 1;
                    if hit {
                        self.hits += 1;
                    } else {
                        self.recomputes += 1;
                    }
                }
            }
            if let Some(trace) = &mut self.trace {
                let decode = self.cfg.cost.decode(out, context + new);
                trace.push(TurnSpan {
                    session: p.serial,
                    turn: p.turns + 1,
                    kind: if first {
                        TurnKind::Cold
                    } else if hit {
                        TurnKind::Hit
                    } else {
                        TurnKind::Miss
                    },
                    enqueued: p.enqueued_at,
                    admitted: now,
                    start: now,
                    prefill_end: now + service - decode,
                    end: now + service,
                    context: target,
                    prefill_tokens: if hit { new } else { context + new },
                    cached_tokens: if hit { context } else { 0.0 },
                    decode_tokens: out,
                });
            }
            p.context = target;
            p.residency = Residency::Resident;
            self.in_service = Some((id, first, service));
            self.busy.set(now, 1.0);
            s.after(service, Ev::ServiceDone(id));
            return;
        }
        self.busy.set(now, 0.0);
    }

    fn finish(&mut self, id: usize, s: &mut Scheduler<Ev>) {
        let now = s.now();
        let kv = self.programs[id].kv;
        self.used_kv -= kv;
        self.resident.add(now, -kv);
        self.programs[id].kv = 0.0;
        self.programs[id].phase = Phase::Dead;
        self.free_slots.push(id);
        self.live.add(now, -1.0);
        if let Population::Closed { .. } = self.cfg.population {
            self.spawn(s);
        }
    }
}

impl Model for Agentic {
    type Event = Ev;

    fn handle(&mut self, ev: Ev, s: &mut Scheduler<Ev>) {
        let now = s.now();
        match ev {
            Ev::EndWarmup => {
                self.warm = true;
                self.busy.reset(now);
                self.resident.reset(now);
                self.live.reset(now);
            }
            Ev::ProgramArrival => {
                if let Population::Open { rate } = self.cfg.population {
                    let gap = Dist::exp(1.0 / rate).sample(&mut self.rng);
                    s.after(gap, Ev::ProgramArrival);
                }
                self.spawn(s);
            }
            Ev::ToolDone(id) => {
                let class = self.programs[id].class;
                if self.rng.random::<f64>() >= self.cfg.classes[class].resume_prob {
                    self.finish(id, s);
                    return;
                }
                self.programs[id].ready_at = now;
                let blocking = self.cfg.fetch == FetchMode::Blocking;
                if self.programs[id].residency == Residency::Offloaded && !blocking {
                    let c = self.programs[id].context;
                    let fetch = match self.cfg.offload {
                        OffloadPolicy::Never => false,
                        OffloadPolicy::Always => true,
                        OffloadPolicy::Selective => {
                            self.tier_backlog(now) + c / self.cfg.tier_bandwidth
                                < self.recompute_cost(c)
                        }
                        OffloadPolicy::Priced => {
                            self.tier_backlog(now) + c / self.cfg.tier_bandwidth
                                < self.miss_price(id, c)
                        }
                    };
                    if fetch {
                        if self.warm {
                            self.fetches += 1;
                        }
                        self.programs[id].phase = Phase::Fetching;
                        let done = self.tier_transfer(now, c);
                        s.at(done, Ev::FetchDone(id));
                        return;
                    }
                    self.programs[id].residency = Residency::Dropped;
                }
                self.enqueue(id, s);
            }
            Ev::FetchDone(id) => {
                self.programs[id].residency = Residency::Staged;
                self.enqueue(id, s);
            }
            Ev::ServiceDone(id) => {
                self.in_service = None;
                let p = &mut self.programs[id];
                p.turns += 1;
                p.last_used = now;
                let cls = &self.cfg.classes[p.class];
                let p = &self.programs[id];
                let cont = p.context <= self.cfg.max_context;
                let think = if cont {
                    cls.tool_time.sample(&mut self.rng)
                } else {
                    0.0
                };
                if self.warm {
                    self.turns += 1;
                    self.response.push(now - p.ready_at);
                    self.think.push(think);
                }
                if cont {
                    self.programs[id].phase = Phase::Tool;
                    s.after(think, Ev::ToolDone(id));
                } else {
                    self.finish(id, s);
                }
                if self.in_service.is_none() {
                    self.start_next(s);
                }
            }
        }
    }
}

/// Run the configured system and report measurement-window statistics.
pub fn simulate(cfg: &AgenticConfig) -> AgenticReport {
    simulate_inner(cfg, false).0
}

/// As [`simulate`], also returning every turn served before the horizon
/// (warm-up included), in service-start order.
pub fn simulate_traced(cfg: &AgenticConfig) -> (AgenticReport, Vec<TurnSpan>) {
    simulate_inner(cfg, true)
}

fn simulate_inner(cfg: &AgenticConfig, traced: bool) -> (AgenticReport, Vec<TurnSpan>) {
    let mut m = Agentic::new(cfg.clone());
    if traced {
        m.trace = Some(Vec::new());
    }
    let mut s = Scheduler::new();
    s.at(cfg.warmup, Ev::EndWarmup);
    match cfg.population {
        Population::Closed { programs } => {
            for _ in 0..programs {
                m.spawn(&mut s);
            }
        }
        Population::Open { .. } => s.at(0.0, Ev::ProgramArrival),
    }
    let end = run(&mut m, &mut s, cfg.horizon);
    let end = end.max(cfg.horizon);
    let span = end - cfg.warmup;
    let wait = if m.waits.len() >= 40 {
        batch_means(&m.waits, 20)
    } else {
        Estimate {
            mean: f64::NAN,
            half_width: f64::INFINITY,
        }
    };
    let trace = m.trace.take().unwrap_or_default();
    let report = AgenticReport {
        turns: m.turns,
        throughput: m.turns as f64 / span,
        hit_rate: if m.follow_ups > 0 {
            m.hits as f64 / m.follow_ups as f64
        } else {
            f64::NAN
        },
        service: m.service,
        wait,
        waits: m.waits,
        response: m.response,
        think: m.think,
        utilization: m.busy.mean(end),
        mean_resident_kv: m.resident.mean(end),
        mean_programs: m.live.mean(end),
        evictions: m.evictions,
        offload_writes: m.offload_writes,
        fetches: m.fetches,
        recomputes: m.recomputes,
        truncated: m.truncated,
        tier_utilization: m.tier_busy / span,
        recompute_load: m.recompute_time / span,
        stall_load: m.stall_time / span,
    };
    (report, trace)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ample_memory_means_every_follow_up_hits() {
        let mut cfg = AgenticConfig::example(8, 1.0e9);
        cfg.max_context = 2.0e5;
        cfg.horizon = 2_000.0;
        let r = simulate(&cfg);
        assert_eq!(r.evictions, 0);
        assert_eq!(r.hit_rate, 1.0);
        assert!(r.turns > 100);
    }

    #[test]
    fn memory_is_never_oversubscribed() {
        // Tight memory: many evictions, but `evict` asserts feasibility and
        // resident KV stays within capacity on average by construction.
        let cfg = AgenticConfig::example(32, 3.0e5);
        let r = simulate(&cfg);
        assert!(r.evictions > 0);
        assert!(r.mean_resident_kv <= cfg.kv_capacity + 1e-6);
        assert!(r.hit_rate < 1.0);
    }

    #[test]
    fn truncation_never_double_books_the_replica() {
        // Heavy-tailed appends against a small pool force `target >
        // kv_capacity`; `start_next` debug-asserts the replica is idle.
        let mut cfg = AgenticConfig::example(16, 1.2e5);
        cfg.max_context = 1.0e5;
        cfg.classes[0].new_tokens = Dist::hyperexp_balanced(8_000.0, 20.0);
        cfg.horizon = 3_000.0;
        let r = simulate(&cfg);
        assert!(r.truncated > 0, "scenario must exercise truncation");
        assert!(r.utilization <= 1.0 + 1e-9);
    }

    #[test]
    fn price_estimator_falls_back_to_delta_s_and_tracks_rate() {
        let mut e = PriceEstimator::default();
        assert_eq!(e.price(0.1, 2.0), 2.0);
        // One turn of 0.5 s every second, no waiting: λ=1, ρ=0.5, W=0.
        for k in 0..2000 {
            e.observe(k as f64, 0.0, 0.5);
        }
        let (lam, rho, w) = e.estimates();
        assert!((lam - 1.0).abs() < 1e-9 && (rho - 0.5).abs() < 1e-9 && w == 0.0);
        let want = crate::analytic::miss_price(1.0, 0.0, 0.5, 0.1, 2.1);
        assert!((e.price(0.1, 2.0) - want).abs() < 1e-9);
        // Saturation is capped.
        for k in 0..2000 {
            e.observe(2000.0 + 0.1 * k as f64, 5.0, 0.5);
        }
        assert_eq!(e.estimates().1, PriceEstimator::RHO_CAP);
    }

    #[test]
    fn priced_policies_run_under_pressure() {
        let mut cfg = AgenticConfig::example(32, 3.0e5);
        cfg.eviction = EvictionPolicy::Priced;
        cfg.offload = OffloadPolicy::Priced;
        cfg.tier_bandwidth = 2.0e4;
        let r = simulate(&cfg);
        assert!(r.evictions > 0 && r.offload_writes > 0 && r.turns > 100);
    }

    #[test]
    fn trace_is_consistent_and_does_not_perturb() {
        let cfg = AgenticConfig {
            horizon: 600.0,
            ..AgenticConfig::example(16, 150_000.0)
        };
        let (report, trace) = simulate_traced(&cfg);
        assert_eq!(report.turns, simulate(&cfg).turns);
        assert!(trace.iter().any(|t| t.kind == TurnKind::Miss));
        for t in &trace {
            assert!(t.enqueued <= t.start && t.start < t.prefill_end && t.prefill_end <= t.end);
            assert_eq!(t.turn == 1, t.kind == TurnKind::Cold);
            let tokens = t.prefill_tokens + t.cached_tokens + t.decode_tokens;
            assert!((tokens - t.context).abs() < 1e-6 * t.context.max(1.0));
        }
        // One turn at a time, and turns of a session are numbered 1, 2, ….
        for w in trace.windows(2) {
            assert!(w[0].end <= w[1].start + 1e-9);
        }
        let mut last = std::collections::HashMap::new();
        for t in &trace {
            let prev = last.insert(t.session, t.turn).unwrap_or(0);
            assert_eq!(t.turn, prev + 1);
        }
    }

    #[test]
    fn same_seed_same_result() {
        let cfg = AgenticConfig::example(16, 4.0e5);
        let a = simulate(&cfg);
        let b = simulate(&cfg);
        assert_eq!(a.turns, b.turns);
        assert_eq!(a.waits, b.waits);
    }
}
