//! A batching replica serving agent sessions (paper §`sec:batch`,
//! §`sec:sessions`; the two-resource replica of §`sec:price`).
//!
//! **Arrivals.** Sessions (agent programs) arrive as a Poisson process of
//! rate `Λ` ([`Population::Open`]) or a fixed number is kept live
//! ([`Population::Closed`]). Inside a session the loop is closed: a turn at
//! the replica, then a tool call (an infinite-server delay of general law),
//! then with probability `p` another turn, else the session ends. The
//! context grows every turn. With an open population this is an open
//! network with feedback; when the replica is processor sharing it has
//! BCMP product form, so the mean number at the replica is that of an
//! isolated PS queue fed at the turn rate `λ = Λ/(1-p)`. An optional cap on
//! live sessions ([`BatchConfig::max_sessions`]) holds further arrivals in
//! an entry queue so that open runs near saturation do not thrash memory.
//!
//! **Servers.** [`Server::Ps`] is continuous batching with chunked prefill
//! as a single processor-sharing station of capacity `φ(n)`: with `n` turns
//! in the batch the replica does `φ(n)` work-seconds per second and each
//! turn gets `φ(n)/n`. [`Server::BlockingPrefill`] is the contrast without
//! chunking: a turn's prefill runs alone at rate `φ(1)`, FIFO among prefills
//! and with priority over decode, and stalls every decoding turn; decode is
//! PS at `φ(n)` while no prefill runs. [`Server::Fifo`] serves one turn at
//! a time at rate 1, the single-turn replica of [`super::agentic`], kept
//! for regression.
//!
//! The two-resource replica of the paper's §2.2 (decode one token per
//! turn per iteration, prefill FIFO on the compute left) is not simulated
//! here: its closed forms are the propositions, and the paper's evidence
//! runs vLLM v1's engine rules as seQ programs (`crate::seq_price`,
//! `crate::seq_open`, `crate::seq_replay`).
//!
//! **Exact limited PS.** In the theory the batch cap `B` is modelled by a
//! `φ` that saturates at `B` ([`Phi::Saturating`] with `cap`). The
//! simulator also implements the exact rule: at most `B` turns are admitted
//! ([`BatchConfig::batch_cap`]), admission is further limited by KV memory (resident KV
//! of batch members plus that of suspended sessions must fit in
//! [`BatchConfig::kv_capacity`], after evicting suspended sessions), and
//! turns that cannot be admitted wait FIFO with head-of-line blocking.
//!
//! **In-batch interference** (optional, [`StepTime`], `Ps` only): a decode
//! step takes `a + b·K` with `K` the KV tokens in the batch, so the batch's
//! work rate is scaled by `a/(a + bK)`. Work is measured in seconds at an
//! empty batch.
//!
//! **Eviction** is as in [`super::agentic`] (sessions in a tool call first,
//! then waiting sessions, never batch members), with the policies of
//! [`EvictionPolicy`]; offloading is not modelled here. A session's KV is a
//! resident *prefix* of its context: whole-session policies drop it
//! entirely, [`EvictionPolicy::PricedMemoryBlocks`] drops
//! [`BatchConfig::block_tokens`] from its tail, and the next turn
//! re-prefills whatever is missing (`prefill(K - kv + new, kv)`). A turn is
//! a hit iff its whole context was resident. `Priced` uses the price of a
//! miss of the server mode: under PS `Φ = ΔS·κ̂` with `κ̂ = L'(ρ̂)` for
//! `φ ≡ C`, a common factor, so its order is the `Density` order (Prop.
//! decode); under blocking prefill and `Fifo` it is the M/G/1 price with
//! the head-of-line term, from online `λ̂, ρ̂, Ŵ` of the FIFO part (the
//! prefill queue, resp. the whole turn).

use std::cmp::Ordering;
use std::collections::{BinaryHeap, VecDeque};
use std::sync::Arc;

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};

use crate::analytic::stationary_mean;
use crate::dist::Dist;
use crate::engine::{Model, Scheduler, run};
use crate::stats::{Estimate, TimeAverage, Welford, batch_means, quantile};
use crate::workload::TraceCorpus;

pub use super::agentic::{
    CostModel, EvictionPolicy, Population, PriceEstimator, ProgramClass, TurnKind, TurnSpan,
};

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

/// Optional in-batch interference: a decode step takes `a + b·K`, `K` the
/// KV tokens of the turns in the batch.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct StepTime {
    pub a: f64,
    pub b: f64,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Server {
    /// One turn at a time at rate 1 (batch cap 1).
    Fifo,
    /// Continuous batching with chunked prefill as one PS station of
    /// capacity `φ`.
    Ps { phi: Phi },
    /// Prefill exclusive at rate `φ(1)`, FIFO, with priority; decode PS at
    /// `φ(n)` while no prefill runs.
    BlockingPrefill { phi: Phi },
}

impl Server {
    fn phi(&self) -> Phi {
        match *self {
            Server::Fifo => Phi::Constant(1.0),
            Server::Ps { phi } | Server::BlockingPrefill { phi } => phi,
        }
    }
}

/// Where a turn's work comes from.
#[derive(Clone, Debug, PartialEq)]
pub enum Work {
    /// From the class token laws and the [`CostModel`]: a hit prefills the
    /// new tokens over the resident prefix, a miss re-prefills the context.
    Tokens,
    /// I.i.d. prefill and decode work per turn, independent of KV state
    /// (for the in-model checks). The work is drawn when the turn becomes
    /// ready, from its own random stream, so two runs that differ only in
    /// these laws see the same turns (common random numbers).
    Sampled { prefill: Dist, decode: Dist },
}

#[derive(Clone, Debug)]
pub struct BatchConfig {
    pub population: Population,
    /// Open population only: at most this many live sessions; later
    /// arrivals wait in an entry queue.
    pub max_sessions: Option<usize>,
    /// Session classes. With [`BatchConfig::trace`] set they only supply the
    /// scheduler's estimates (`resume_prob` as `p_i`, `tool_time.mean()` as
    /// `τ_i`); tokens, outputs, think times and whether a session continues
    /// then come from the replayed session.
    pub classes: Vec<ProgramClass>,
    /// Replay real sessions (see [`crate::workload`]): each new session is
    /// a uniformly drawn corpus session, played turn by turn.
    pub trace: Option<Arc<TraceCorpus>>,
    /// Probability that a follow-up turn whose context is resident is
    /// forced to miss (its KV dropped at admission), drawn from its own
    /// random stream so that runs differing only in this share the rest.
    /// The `q_i` of Prop. price.
    pub force_miss: f64,
    pub cost: CostModel,
    pub work: Work,
    pub server: Server,
    /// Exact LPS: at most this many turns admitted to the batch.
    pub batch_cap: Option<usize>,
    /// Device KV capacity, tokens (`INFINITY`: no memory limit).
    pub kv_capacity: f64,
    /// A session ends once its context exceeds this.
    pub max_context: f64,
    pub eviction: EvictionPolicy,
    /// Block size (tokens) of [`EvictionPolicy::PricedMemoryBlocks`].
    pub block_tokens: f64,
    pub step_time: Option<StepTime>,
    pub warmup: f64,
    pub horizon: f64,
    pub seed: u64,
}

impl BatchConfig {
    /// Open Poisson turns (`p = 0`, one turn per session) with i.i.d. work
    /// `service`, no memory limit: the M/G/· queue of the in-model checks.
    /// The cost model keeps the example's `ω = 2·10⁻⁴` and `a = 2·10⁻⁵`.
    pub fn poisson_turns(
        rate: f64,
        service: Dist,
        server: Server,
        horizon: f64,
        seed: u64,
    ) -> Self {
        Self {
            population: Population::Open { rate },
            max_sessions: None,
            trace: None,
            force_miss: 0.0,
            classes: vec![ProgramClass {
                weight: 1.0,
                resume_prob: 0.0,
                initial_tokens: Dist::Deterministic(0.0),
                new_tokens: Dist::Deterministic(0.0),
                output_tokens: Dist::Deterministic(0.0),
                tool_time: Dist::Deterministic(0.0),
            }],
            cost: CostModel {
                overhead: 0.0,
                prefill_linear: 2.0e-5,
                prefill_quadratic: 0.0,
                decode_per_token: 2.0e-4,
                decode_kv: 0.0,
            },
            work: Work::Sampled {
                prefill: service,
                decode: Dist::Deterministic(0.0),
            },
            server,
            batch_cap: None,
            kv_capacity: f64::INFINITY,
            max_context: f64::INFINITY,
            eviction: EvictionPolicy::ShortestFirst,
            block_tokens: 512.0,
            step_time: None,
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Phase {
    Queued,
    Prefill,
    Decode,
    Tool,
    Dead,
}

#[derive(Clone, Debug)]
struct Session {
    class: usize,
    context: f64,
    /// Resident prefix of the context (≤ `context`).
    kv: f64,
    cold: bool,
    phase: Phase,
    last_used: f64,
    // the pending / current turn
    seq: u64,
    ready_at: f64,
    new: f64,
    out: f64,
    sampled: (f64, f64),
    prefill_work: f64,
    /// Decode work after the prefill (seconds).
    decode_work: f64,
    /// Arrival serial number and turn index, for [`simulate_traced`].
    serial: u64,
    turn_no: u32,
    /// The current turn's trace record, while it is at the replica.
    span: Option<TurnSpan>,
    /// Replayed session: (corpus session index, index of the current turn).
    replay: Option<(usize, usize)>,
}

/// A job in the PS pool, keyed by its virtual finish time.
#[derive(Clone, Copy, Debug)]
struct Tag(f64, usize);

impl PartialEq for Tag {
    fn eq(&self, o: &Self) -> bool {
        self.cmp(o) == Ordering::Equal
    }
}
impl Eq for Tag {}
impl Ord for Tag {
    // Reversed: `BinaryHeap` pops the smallest finish time.
    fn cmp(&self, o: &Self) -> Ordering {
        o.0.total_cmp(&self.0).then_with(|| o.1.cmp(&self.1))
    }
}
impl PartialOrd for Tag {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}

enum Ev {
    SessionArrival,
    ToolDone(usize),
    /// Blocking prefill finished.
    PrefillDone(usize),
    /// Next PS departure, valid only for the matching generation.
    Depart(u64),
    EndWarmup,
}

struct Batch {
    cfg: BatchConfig,
    phi: Phi,
    arrivals_rng: StdRng,
    work_rng: StdRng,
    flow_rng: StdRng,
    miss_rng: StdRng,
    sessions: Vec<Session>,
    free_slots: Vec<usize>,
    entry: VecDeque<f64>,
    waiting: VecDeque<usize>,
    live: usize,
    used_kv: f64,
    // PS pool (virtual time = service attained by every pool member)
    pool: BinaryHeap<Tag>,
    pool_kv: f64,
    v: f64,
    v_last: f64,
    rate: f64,
    generation: u64,
    dirty: bool,
    // blocking prefill
    prefilling: Option<usize>,
    next_seq: u64,
    next_serial: u64,
    trace: Option<Vec<TurnSpan>>,
    price: PriceEstimator,
    warm: bool,
    // statistics
    turns: u64,
    sessions_done: u64,
    follow_ups: u64,
    hits: u64,
    responses: Vec<(u64, f64)>,
    ttfts: Vec<(u64, f64)>,
    wait: Welford,
    work: Welford,
    entry_wait: Welford,
    number: TimeAverage,
    batch: TimeAverage,
    pnum: TimeAverage,
    dnum: TimeAverage,
    avail: TimeAverage,
    busy: TimeAverage,
    resident: TimeAverage,
    live_avg: TimeAverage,
    entry_avg: TimeAverage,
    evictions: u64,
    recomputes: u64,
    recomputed_tokens: f64,
    truncated: u64,
}

impl Batch {
    fn new(cfg: BatchConfig) -> Self {
        assert!(!cfg.classes.is_empty());
        assert!(cfg.warmup < cfg.horizon);
        assert!(cfg.max_context < cfg.kv_capacity || cfg.kv_capacity.is_infinite());
        let seed = cfg.seed;
        Self {
            phi: cfg.server.phi(),
            cfg,
            arrivals_rng: StdRng::seed_from_u64(seed),
            work_rng: StdRng::seed_from_u64(seed ^ 0x9e37_79b9_7f4a_7c15),
            flow_rng: StdRng::seed_from_u64(seed ^ 0x5851_f42d_4c95_7f2d),
            miss_rng: StdRng::seed_from_u64(seed ^ 0x2545_f491_4f6c_dd1d),
            sessions: Vec::new(),
            free_slots: Vec::new(),
            entry: VecDeque::new(),
            waiting: VecDeque::new(),
            live: 0,
            used_kv: 0.0,
            pool: BinaryHeap::new(),
            pool_kv: 0.0,
            v: 0.0,
            v_last: 0.0,
            rate: 0.0,
            generation: 0,
            dirty: false,
            prefilling: None,
            next_seq: 0,
            next_serial: 0,
            trace: None,
            price: PriceEstimator::default(),
            warm: false,
            turns: 0,
            sessions_done: 0,
            follow_ups: 0,
            hits: 0,
            responses: Vec::new(),
            ttfts: Vec::new(),
            wait: Welford::new(),
            work: Welford::new(),
            entry_wait: Welford::new(),
            number: TimeAverage::new(0.0, 0.0),
            batch: TimeAverage::new(0.0, 0.0),
            pnum: TimeAverage::new(0.0, 0.0),
            dnum: TimeAverage::new(0.0, 0.0),
            avail: TimeAverage::new(0.0, 1.0),
            busy: TimeAverage::new(0.0, 0.0),
            resident: TimeAverage::new(0.0, 0.0),
            live_avg: TimeAverage::new(0.0, 0.0),
            entry_avg: TimeAverage::new(0.0, 0.0),
            evictions: 0,
            recomputes: 0,
            recomputed_tokens: 0.0,
            truncated: 0,
        }
    }

    fn blocking(&self) -> bool {
        matches!(self.cfg.server, Server::BlockingPrefill { .. })
    }

    fn cap(&self) -> usize {
        match self.cfg.server {
            Server::Fifo => 1,
            _ => self.cfg.batch_cap.unwrap_or(usize::MAX),
        }
    }

    fn admitted(&self) -> usize {
        self.pool.len() + usize::from(self.prefilling.is_some())
    }

    /// Work per second the replica delivers to the PS pool.
    fn pool_total_rate(&self) -> f64 {
        if self.prefilling.is_some() {
            return 0.0;
        }
        let r = self.phi.rate(self.pool.len());
        match self.cfg.step_time {
            Some(StepTime { a, b }) => r * a / (a + b * self.pool_kv),
            None => r,
        }
    }

    fn prefill_rate(&self) -> f64 {
        self.phi.rate(1)
    }

    fn advance(&mut self, now: f64) {
        let dt = now - self.v_last;
        self.v += self.rate * dt;
        self.v_last = now;
    }

    fn reschedule(&mut self, s: &mut Scheduler<Ev>) {
        let n = self.pool.len();
        self.rate = if n == 0 {
            0.0
        } else {
            self.pool_total_rate() / n as f64
        };
        self.generation += 1;
        if let Some(t) = self.pool.peek()
            && self.rate > 0.0
        {
            let dt = ((t.0 - self.v) / self.rate).max(0.0);
            s.after(dt, Ev::Depart(self.generation));
        }
        self.dirty = false;
    }

    fn pick_class(&mut self) -> usize {
        let total: f64 = self.cfg.classes.iter().map(|c| c.weight).sum();
        let mut u = self.flow_rng.random::<f64>() * total;
        for (i, c) in self.cfg.classes.iter().enumerate() {
            if u < c.weight {
                return i;
            }
            u -= c.weight;
        }
        self.cfg.classes.len() - 1
    }

    fn spawn(&mut self, now: f64, arrived: f64) {
        if self.warm && arrived >= self.cfg.warmup {
            self.entry_wait.push(now - arrived);
        }
        let class = self.pick_class();
        let replay = self
            .cfg
            .trace
            .as_ref()
            .map(|c| (self.flow_rng.random_range(0..c.sessions.len()), 0));
        let sess = Session {
            class,
            context: 0.0,
            kv: 0.0,
            cold: true,
            phase: Phase::Queued,
            last_used: now,
            seq: 0,
            ready_at: now,
            new: 0.0,
            out: 0.0,
            sampled: (0.0, 0.0),
            prefill_work: 0.0,
            decode_work: 0.0,
            serial: self.next_serial,
            turn_no: 0,
            span: None,
            replay,
        };
        self.next_serial += 1;
        let id = match self.free_slots.pop() {
            Some(id) => {
                self.sessions[id] = sess;
                id
            }
            None => {
                self.sessions.push(sess);
                self.sessions.len() - 1
            }
        };
        self.live += 1;
        self.new_turn(id, now);
    }

    /// The session's next turn becomes ready and joins the FIFO wait.
    /// The replayed turn record of session `id`, if it is a replay.
    fn replay_turn(&self, id: usize) -> Option<crate::workload::TraceTurn> {
        let (si, ti) = self.sessions[id].replay?;
        Some(self.cfg.trace.as_ref()?.sessions[si].turns[ti])
    }

    fn new_turn(&mut self, id: usize, now: f64) {
        let cls = &self.cfg.classes[self.sessions[id].class];
        let (new, out) = match self.replay_turn(id) {
            Some(t) => (t.new, t.out),
            None => (
                if self.sessions[id].cold {
                    cls.initial_tokens.sample(&mut self.work_rng)
                } else {
                    cls.new_tokens.sample(&mut self.work_rng)
                },
                cls.output_tokens.sample(&mut self.work_rng),
            ),
        };
        let sampled = match &self.cfg.work {
            Work::Tokens => (0.0, 0.0),
            Work::Sampled { prefill, decode } => (
                prefill.sample(&mut self.work_rng),
                decode.sample(&mut self.work_rng),
            ),
        };
        let seq = self.next_seq;
        self.next_seq += 1;
        let p = &mut self.sessions[id];
        p.seq = seq;
        p.ready_at = now;
        p.new = new;
        p.out = out;
        p.sampled = sampled;
        p.phase = Phase::Queued;
        p.turn_no += 1;
        self.waiting.push_back(id);
    }

    fn end_session(&mut self, id: usize, now: f64) {
        let kv = self.sessions[id].kv;
        self.used_kv -= kv;
        self.sessions[id].kv = 0.0;
        self.sessions[id].phase = Phase::Dead;
        self.free_slots.push(id);
        self.live -= 1;
        if self.warm {
            self.sessions_done += 1;
        }
        match self.cfg.population {
            Population::Closed { .. } => self.spawn(now, now),
            Population::Open { .. } => {
                if let Some(arrived) = self.entry.pop_front() {
                    self.spawn(now, arrived);
                }
            }
        }
    }

    fn resume_prob(&self, id: usize) -> f64 {
        let p = &self.sessions[id];
        if p.phase == Phase::Tool {
            self.cfg.classes[p.class].resume_prob
        } else {
            1.0
        }
    }

    /// Expected remaining suspension `τ_i`: the class mean tool time in a
    /// tool call; a common constant for sessions waiting for admission.
    fn suspension(&self, id: usize) -> f64 {
        let p = &self.sessions[id];
        if p.phase == Phase::Tool {
            self.cfg.classes[p.class].tool_time.mean()
        } else {
            1.0
        }
    }

    /// Price of a miss that adds `ds` seconds of prefill work to the next
    /// turn of session `id` (see the module doc).
    fn miss_price(&self, id: usize, ds: f64) -> f64 {
        match self.cfg.server {
            Server::Ps { .. } => {
                // κ̂ = L'(ρ) for φ ≡ C: C/(C-ρ)² = 1/(C(1-u)²), u = ρ̂/C.
                let (_, u, _) = self.price.estimates();
                ds / (self.phi.limit() * (1.0 - u).powi(2))
            }
            Server::BlockingPrefill { .. } | Server::Fifo => {
                let p = &self.sessions[id];
                let cls = &self.cfg.classes[p.class];
                let cost = &self.cfg.cost;
                let mut s_h = cost.overhead + cost.prefill(cls.new_tokens.mean(), p.kv);
                if self.cfg.server == Server::Fifo {
                    s_h += cost.decode(cls.output_tokens.mean(), p.kv + cls.new_tokens.mean());
                }
                let r = self.prefill_rate();
                self.price.price(s_h / r, ds / r)
            }
        }
    }

    fn evict_key(&mut self, id: usize) -> f64 {
        let p = &self.sessions[id];
        let kv = p.kv;
        match self.cfg.eviction {
            EvictionPolicy::ShortestFirst => kv,
            EvictionPolicy::LongestFirst => -kv,
            EvictionPolicy::Lru => p.last_used,
            EvictionPolicy::Random => self.flow_rng.random(),
            EvictionPolicy::Density => self.resume_prob(id) * self.cfg.cost.miss_penalty(kv) / kv,
            EvictionPolicy::Priced => {
                self.resume_prob(id) * self.miss_price(id, self.cfg.cost.miss_penalty(kv)) / kv
            }
            EvictionPolicy::PricedMemory => {
                self.resume_prob(id) * self.miss_price(id, self.cfg.cost.miss_penalty(kv))
                    / (kv * self.suspension(id))
            }
            EvictionPolicy::PricedMemoryBlocks => unreachable!("handled by evict_blocks"),
        }
    }

    /// Tokens in the tail block of a resident prefix of `kv` tokens.
    fn tail_block(&self, kv: f64) -> f64 {
        let b = self.cfg.block_tokens;
        let full = ((kv / b).ceil() - 1.0).max(0.0);
        let m = kv - full * b;
        if m < 1e-6 * b { b.min(kv) } else { m }
    }

    /// Price per byte-second of dropping the tail block (`m` tokens) of
    /// session `id`: `q Φ(ΔP) / (m τ)`, `ΔP = prefill(m, kv - m)`.
    fn block_key(&self, id: usize, m: f64) -> f64 {
        let kv = self.sessions[id].kv;
        let dp = self.cfg.cost.prefill(m, kv - m);
        self.resume_prob(id) * self.miss_price(id, dp) / (m * self.suspension(id))
    }

    fn evictable(&self, exclude: usize) -> f64 {
        self.sessions
            .iter()
            .enumerate()
            .filter(|&(i, p)| i != exclude && matches!(p.phase, Phase::Tool | Phase::Queued))
            .map(|(_, p)| p.kv)
            .sum()
    }

    /// Free at least `need` tokens from suspended sessions, tool calls
    /// first, never touching `exclude` or the batch.
    fn evict(&mut self, need: f64, exclude: usize) {
        if self.cfg.eviction == EvictionPolicy::PricedMemoryBlocks {
            return self.evict_blocks(need, exclude);
        }
        let mut freed = 0.0;
        for phase in [Phase::Tool, Phase::Queued] {
            let ids: Vec<usize> = (0..self.sessions.len())
                .filter(|&i| {
                    i != exclude && self.sessions[i].phase == phase && self.sessions[i].kv > 0.0
                })
                .collect();
            let mut keyed: Vec<(f64, usize)> =
                ids.into_iter().map(|i| (self.evict_key(i), i)).collect();
            keyed.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
            for (_, i) in keyed {
                if freed >= need {
                    return;
                }
                let kv = self.sessions[i].kv;
                self.sessions[i].kv = 0.0;
                self.used_kv -= kv;
                freed += kv;
                self.evictions += 1;
            }
        }
        debug_assert!(freed >= need - 1e-6, "evictable was checked");
    }

    /// Block-level eviction: repeatedly drop the tail block with the lowest
    /// price per byte-second, tool calls first.
    fn evict_blocks(&mut self, need: f64, exclude: usize) {
        let mut freed = 0.0;
        for phase in [Phase::Tool, Phase::Queued] {
            while freed < need {
                let mut best: Option<(f64, usize, f64)> = None;
                for i in 0..self.sessions.len() {
                    let p = &self.sessions[i];
                    if i == exclude || p.phase != phase || p.kv <= 0.0 {
                        continue;
                    }
                    let m = self.tail_block(p.kv);
                    let key = self.block_key(i, m);
                    if best.is_none_or(|b| key < b.0) {
                        best = Some((key, i, m));
                    }
                }
                let Some((_, i, m)) = best else { break };
                self.sessions[i].kv -= m;
                self.used_kv -= m;
                freed += m;
                self.evictions += 1;
            }
        }
        debug_assert!(freed >= need - 1e-6, "evictable was checked");
    }

    /// Admit waiting turns in FIFO order while the batch cap and KV memory
    /// allow; the first turn that does not fit blocks the rest.
    fn try_admit(&mut self, s: &mut Scheduler<Ev>) {
        let now = s.now();
        while let Some(&id) = self.waiting.front() {
            if self.admitted() >= self.cap() || (self.blocking() && self.prefilling.is_some()) {
                break;
            }
            let p = &self.sessions[id];
            let target = p.context + p.new + p.out;
            if target > self.cfg.kv_capacity {
                self.waiting.pop_front();
                self.truncated += 1;
                self.end_session(id, now);
                continue;
            }
            let extra = target - p.kv;
            let need = self.used_kv + extra - self.cfg.kv_capacity;
            if need > 0.0 {
                if self.evictable(id) < need {
                    break;
                }
                self.evict(need, id);
            }
            self.waiting.pop_front();
            self.admit(id, target, s);
        }
    }

    fn admit(&mut self, id: usize, target: f64, s: &mut Scheduler<Ev>) {
        let now = s.now();
        if self.cfg.force_miss > 0.0 {
            let p = &self.sessions[id];
            if !p.cold && p.kv >= p.context && self.miss_rng.random::<f64>() < self.cfg.force_miss {
                self.used_kv -= p.kv;
                self.sessions[id].kv = 0.0;
            }
        }
        let cost = &self.cfg.cost;
        let p = &self.sessions[id];
        let hit = !p.cold && p.kv >= p.context;
        let missing = p.context - p.kv;
        let (prefill, decode) = match self.cfg.work {
            Work::Sampled { .. } => p.sampled,
            Work::Tokens => {
                // Re-prefill whatever is not resident, then the new tokens.
                let pre = cost.overhead + cost.prefill(missing + p.new, p.kv);
                let dec = cost.decode(p.out, target);
                (pre, dec)
            }
        };
        let wait = now - p.ready_at;
        let counted = self.warm && p.ready_at >= self.cfg.warmup;
        if counted {
            self.wait.push(wait);
            self.work.push(prefill + decode);
            if !p.cold {
                self.follow_ups += 1;
                if hit {
                    self.hits += 1;
                } else {
                    self.recomputes += 1;
                    self.recomputed_tokens += missing;
                }
            }
        }
        let span = self.trace.as_ref().map(|_| TurnSpan {
            session: p.serial,
            turn: p.turn_no,
            kind: if p.cold {
                TurnKind::Cold
            } else if hit {
                TurnKind::Hit
            } else {
                TurnKind::Miss
            },
            enqueued: p.ready_at,
            admitted: now,
            start: f64::NAN,
            prefill_end: f64::NAN,
            end: f64::NAN,
            context: target,
            prefill_tokens: missing + p.new,
            cached_tokens: p.kv,
            decode_tokens: p.out,
            new_tokens: p.new,
        });
        self.used_kv += target - p.kv;
        let p = &mut self.sessions[id];
        p.span = span;
        p.kv = target;
        p.context = target;
        p.cold = false;
        p.prefill_work = prefill;
        p.decode_work = decode;
        if self.blocking() {
            let r = self.prefill_rate();
            self.price.observe(now, wait, prefill / r);
            self.sessions[id].phase = Phase::Prefill;
            self.prefilling = Some(id);
            self.prefill_started(id, now);
            s.after(prefill / r, Ev::PrefillDone(id));
        } else {
            let c = self.phi.limit();
            let obs_service = if c.is_finite() {
                (prefill + decode) / c
            } else {
                0.0
            };
            self.price.observe(now, wait, obs_service);
            self.join_pool(id, prefill + decode);
        }
        self.dirty = true;
    }

    fn join_pool(&mut self, id: usize, work: f64) {
        self.sessions[id].phase = Phase::Decode;
        self.pool_kv += self.sessions[id].kv;
        self.pool.push(Tag(self.v + work, id));
        self.dirty = true;
    }

    fn prefill_started(&mut self, id: usize, now: f64) {
        if let Some(span) = &mut self.sessions[id].span {
            span.start = now;
        }
    }

    /// Prefill of `id` finished: record TTFT and hand the turn to decode.
    fn first_token(&mut self, id: usize, s: &mut Scheduler<Ev>) {
        let now = s.now();
        if let Some(span) = &mut self.sessions[id].span {
            span.prefill_end = now;
        }
        let p = &self.sessions[id];
        if self.warm && p.ready_at >= self.cfg.warmup {
            self.ttfts.push((p.seq, now - p.ready_at));
        }
        let d = p.decode_work;
        if d > 0.0 {
            self.join_pool(id, d);
        } else {
            self.turn_done(id, s);
        }
        self.dirty = true;
    }

    fn turn_done(&mut self, id: usize, s: &mut Scheduler<Ev>) {
        let now = s.now();
        let p = &mut self.sessions[id];
        p.last_used = now;
        let (seq, ready) = (p.seq, p.ready_at);
        if let (Some(trace), Some(mut span)) = (&mut self.trace, p.span.take()) {
            span.end = now;
            trace.push(span);
        }
        if self.warm {
            self.turns += 1;
            if ready >= self.cfg.warmup {
                self.responses.push((seq, now - ready));
            }
        }
        if self.sessions[id].context > self.cfg.max_context {
            self.end_session(id, now);
            return;
        }
        let think = match (self.replay_turn(id), self.sessions[id].replay) {
            (Some(t), Some((si, ti))) => {
                // The trace decides whether the session continues.
                if ti + 1 >= self.cfg.trace.as_ref().unwrap().sessions[si].turns.len() {
                    self.end_session(id, now);
                    return;
                }
                t.think
            }
            _ => {
                let cls = &self.cfg.classes[self.sessions[id].class];
                cls.tool_time.sample(&mut self.flow_rng)
            }
        };
        self.sessions[id].phase = Phase::Tool;
        s.after(think, Ev::ToolDone(id));
    }

    fn record(&mut self, now: f64) {
        let adm = self.admitted() as f64;
        let waiting = self.waiting.len() as f64;
        self.number.set(now, waiting + adm);
        self.batch.set(now, adm);
        self.pnum.set(
            now,
            waiting + f64::from(u8::from(self.prefilling.is_some())),
        );
        self.dnum.set(now, self.pool.len() as f64);
        self.avail.set(now, 1.0);
        self.busy.set(now, if adm > 0.0 { 1.0 } else { 0.0 });
        self.resident.set(now, self.used_kv);
        self.live_avg.set(now, self.live as f64);
        self.entry_avg.set(now, self.entry.len() as f64);
    }
}

impl Model for Batch {
    type Event = Ev;

    fn handle(&mut self, ev: Ev, s: &mut Scheduler<Ev>) {
        let now = s.now();
        self.advance(now);
        match ev {
            Ev::EndWarmup => {
                self.warm = true;
                for t in [
                    &mut self.number,
                    &mut self.batch,
                    &mut self.pnum,
                    &mut self.dnum,
                    &mut self.avail,
                    &mut self.busy,
                    &mut self.resident,
                    &mut self.live_avg,
                    &mut self.entry_avg,
                ] {
                    t.reset(now);
                }
            }
            Ev::SessionArrival => {
                if let Population::Open { rate } = self.cfg.population {
                    let gap = Dist::exp(1.0 / rate).sample(&mut self.arrivals_rng);
                    s.after(gap, Ev::SessionArrival);
                }
                if self.cfg.max_sessions.is_some_and(|m| self.live >= m) {
                    self.entry.push_back(now);
                } else {
                    self.spawn(now, now);
                }
            }
            Ev::ToolDone(id) => {
                if let Some((si, ti)) = self.sessions[id].replay {
                    // Continuation was decided from the trace at turn end.
                    self.sessions[id].replay = Some((si, ti + 1));
                    self.new_turn(id, now);
                } else {
                    let class = self.sessions[id].class;
                    if self.flow_rng.random::<f64>() >= self.cfg.classes[class].resume_prob {
                        self.end_session(id, now);
                    } else {
                        self.new_turn(id, now);
                    }
                }
            }
            Ev::PrefillDone(id) => {
                debug_assert_eq!(self.prefilling, Some(id));
                self.prefilling = None;
                self.first_token(id, s);
            }
            Ev::Depart(g) => {
                if g != self.generation {
                    return;
                }
                let t = self.pool.pop().expect("scheduled departure has a job");
                self.v = self.v.max(t.0);
                self.pool_kv -= self.sessions[t.1].kv;
                if self.pool.is_empty() {
                    self.pool_kv = 0.0;
                }
                self.dirty = true;
                self.turn_done(t.1, s);
            }
        }
        self.try_admit(s);
        if self.dirty {
            self.reschedule(s);
        }
        self.record(now);
    }
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

/// Run the configured system and report measurement-window statistics.
pub fn simulate(cfg: &BatchConfig) -> BatchReport {
    simulate_inner(cfg, false).0
}

/// As [`simulate`], also returning every turn completed before the horizon
/// (warm-up included), in completion order. Only for the servers with a
/// separate prefill phase, [`Server::BlockingPrefill`].
pub fn simulate_traced(cfg: &BatchConfig) -> (BatchReport, Vec<TurnSpan>) {
    assert!(
        matches!(cfg.server, Server::BlockingPrefill { .. }),
        "tracing needs a server with a separate prefill phase"
    );
    simulate_inner(cfg, true)
}

fn simulate_inner(cfg: &BatchConfig, traced: bool) -> (BatchReport, Vec<TurnSpan>) {
    let mut m = Batch::new(cfg.clone());
    if traced {
        m.trace = Some(Vec::new());
    }
    let mut s = Scheduler::new();
    s.at(cfg.warmup, Ev::EndWarmup);
    match cfg.population {
        Population::Closed { programs } => {
            for _ in 0..programs {
                m.spawn(0.0, 0.0);
            }
            m.try_admit(&mut s);
            m.reschedule(&mut s);
        }
        Population::Open { .. } => s.at(0.0, Ev::SessionArrival),
    }
    let end = run(&mut m, &mut s, cfg.horizon).max(cfg.horizon);
    let span = end - cfg.warmup;
    let mut responses = std::mem::take(&mut m.responses);
    responses.sort_by_key(|r| r.0);
    let mut response = Welford::new();
    responses.iter().for_each(|r| response.push(r.1));
    let xs: Vec<f64> = responses.iter().map(|r| r.1).collect();
    let (response_ci, p99) = ci_and_p99(&xs);
    let mut ttfts = std::mem::take(&mut m.ttfts);
    ttfts.sort_by_key(|r| r.0);
    let mut ttft = Welford::new();
    ttfts.iter().for_each(|r| ttft.push(r.1));
    let ys: Vec<f64> = ttfts.iter().map(|r| r.1).collect();
    let (ttft_ci, ttft_p99) = ci_and_p99(&ys);
    let trace = m.trace.take().unwrap_or_default();
    let report = BatchReport {
        turns: m.turns,
        throughput: m.turns as f64 / span,
        sessions_done: m.sessions_done,
        hit_rate: if m.follow_ups > 0 {
            m.hits as f64 / m.follow_ups as f64
        } else {
            f64::NAN
        },
        response,
        responses,
        response_ci,
        p99,
        ttft,
        ttfts,
        ttft_ci,
        ttft_p99,
        wait: m.wait,
        work: m.work,
        mean_number: m.number.mean(end),
        mean_batch: m.batch.mean(end),
        mean_prefill_number: m.pnum.mean(end),
        mean_decode_number: m.dnum.mean(end),
        mean_availability: m.avail.mean(end),
        utilization: m.busy.mean(end),
        mean_resident_kv: m.resident.mean(end),
        mean_sessions: m.live_avg.mean(end),
        mean_entry_queue: m.entry_avg.mean(end),
        entry_wait: m.entry_wait,
        evictions: m.evictions,
        recomputes: m.recomputes,
        recomputed_tokens: m.recomputed_tokens,
        truncated: m.truncated,
    };
    (report, trace)
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::agentic::{self, AgenticConfig};

    fn from_agentic(a: &AgenticConfig, server: Server) -> BatchConfig {
        BatchConfig {
            population: a.population,
            max_sessions: None,
            trace: None,
            force_miss: 0.0,
            classes: a.classes.clone(),
            cost: a.cost.clone(),
            work: Work::Tokens,
            server,
            batch_cap: None,
            kv_capacity: a.kv_capacity,
            max_context: a.max_context,
            eviction: a.eviction,
            block_tokens: 512.0,
            step_time: None,
            warmup: a.warmup,
            horizon: a.horizon,
            seed: a.seed,
        }
    }

    #[test]
    fn phi_shapes() {
        let s = Phi::Saturating {
            beta: 0.1,
            cap: Some(8),
        };
        assert_eq!(s.rate(0), 0.0);
        assert!((s.rate(1) - 1.0).abs() < 1e-12);
        assert_eq!(s.rate(8), s.rate(100));
        assert!((s.limit() - 8.0 / 1.7).abs() < 1e-12);
        let m = Phi::Saturating {
            beta: 0.0,
            cap: Some(4),
        };
        assert_eq!((m.rate(3), m.rate(9)), (3.0, 4.0));
    }

    #[test]
    fn ps_mean_number_constant_is_mm1() {
        for rho in [0.1, 0.5, 0.9] {
            let l = ps_mean_number(&Phi::Constant(1.0), rho);
            assert!((l - rho / (1.0 - rho)).abs() < 1e-9);
        }
        // φ(n) = min(n, c) is M/M/c.
        let l = ps_mean_number(
            &Phi::Saturating {
                beta: 0.0,
                cap: Some(1_000_000),
            },
            2.0,
        );
        assert!((l - 2.0).abs() < 1e-9, "M/M/∞ mean is ρ, got {l}");
    }

    #[test]
    fn fifo_mode_matches_single_turn_replica() {
        // Same workload as `agentic` with ample memory: both are one turn
        // at a time, so throughput and service agree up to sampling noise.
        let mut a = AgenticConfig::example(16, 1.0e9);
        a.max_context = 2.0e5;
        a.horizon = 4_000.0;
        let ra = agentic::simulate(&a);
        let rb = simulate(&from_agentic(&a, Server::Fifo));
        assert!((ra.throughput - rb.throughput).abs() / ra.throughput < 0.03);
        assert!((ra.response.mean() - rb.response.mean()).abs() / ra.response.mean() < 0.1);
        assert_eq!(rb.hit_rate, 1.0);
        assert!(rb.mean_batch <= 1.0 + 1e-9);
    }

    #[test]
    fn memory_and_cap_are_respected() {
        let mut a = AgenticConfig::example(48, 3.0e5);
        a.horizon = 2_000.0;
        for (server, ev) in [
            (
                Server::Ps {
                    phi: Phi::Constant(1.0),
                },
                EvictionPolicy::ShortestFirst,
            ),
            (
                Server::BlockingPrefill {
                    phi: Phi::Constant(1.0),
                },
                EvictionPolicy::ShortestFirst,
            ),
            (
                Server::Ps {
                    phi: Phi::Constant(1.0),
                },
                EvictionPolicy::PricedMemory,
            ),
            (
                Server::Ps {
                    phi: Phi::Constant(1.0),
                },
                EvictionPolicy::PricedMemoryBlocks,
            ),
        ] {
            let mut c = from_agentic(&a, server);
            c.batch_cap = Some(6);
            c.eviction = ev;
            let mut m = Batch::new(c.clone());
            let mut s = Scheduler::new();
            s.at(c.warmup, Ev::EndWarmup);
            for _ in 0..48 {
                m.spawn(0.0, 0.0);
            }
            m.try_admit(&mut s);
            m.reschedule(&mut s);
            let mut h = 0.0;
            while s.pending() > 0 && h < c.horizon {
                h += 1.0;
                run(&mut m, &mut s, h);
                assert!(m.used_kv <= c.kv_capacity + 1e-6, "{server:?} at {h}");
                assert!(m.admitted() <= 6);
                let sum: f64 = m.sessions.iter().map(|p| p.kv).sum();
                assert!(
                    (sum - m.used_kv).abs() < 1e-3,
                    "{server:?} {ev:?}: KV accounting"
                );
                assert!(m.sessions.iter().all(|p| p.kv <= p.context + 1e-9));
            }
            assert!(m.evictions > 0 && m.turns > 0, "{server:?} {ev:?}");
        }
    }

    #[test]
    fn block_eviction_frees_tail_blocks_only() {
        // Two suspended sessions of 10 000 resident tokens; free 600.
        let a = AgenticConfig::example(2, 1.0e6);
        for (ev, freed, kvs) in [
            // Whole-session policies drop one context.
            (EvictionPolicy::PricedMemory, 10_000.0, [0.0, 10_000.0]),
            // Blocks: the 272-token remainder, then one 512-token block of
            // the same (now cheaper) context.
            (
                EvictionPolicy::PricedMemoryBlocks,
                784.0,
                [9_216.0, 10_000.0],
            ),
        ] {
            let mut c = from_agentic(
                &a,
                Server::Ps {
                    phi: Phi::Constant(1.0),
                },
            );
            c.eviction = ev;
            let mut m = Batch::new(c);
            for _ in 0..2 {
                m.spawn(0.0, 0.0);
            }
            m.waiting.clear();
            for p in &mut m.sessions {
                p.phase = Phase::Tool;
                p.cold = false;
                p.context = 10_000.0;
                p.kv = 10_000.0;
            }
            m.used_kv = 20_000.0;
            m.evict(600.0, usize::MAX);
            assert!((m.used_kv - (20_000.0 - freed)).abs() < 1e-9, "{ev:?}");
            let mut got: Vec<f64> = m.sessions.iter().map(|p| p.kv).collect();
            got.sort_by(f64::total_cmp);
            assert_eq!(got, kvs, "{ev:?}");
        }
        // In a run, partial misses re-prefill less than whole contexts on
        // average.
        let mut a = AgenticConfig::example(48, 3.0e5);
        a.horizon = 2_500.0;
        let mut c = from_agentic(
            &a,
            Server::Ps {
                phi: Phi::Constant(1.0),
            },
        );
        c.batch_cap = Some(6);
        c.eviction = EvictionPolicy::PricedMemoryBlocks;
        let r = simulate(&c);
        assert!(r.recomputes > 0);
        assert!(r.recomputed_tokens / (r.recomputes as f64) < r.mean_resident_kv);
    }

    #[test]
    fn step_time_slows_the_batch() {
        let mut a = AgenticConfig::example(32, 1.0e9);
        a.max_context = 2.0e5;
        a.horizon = 2_000.0;
        let mut c = from_agentic(
            &a,
            Server::Ps {
                phi: Phi::Constant(1.0),
            },
        );
        let fast = simulate(&c);
        c.step_time = Some(StepTime { a: 1.0, b: 1e-6 });
        let slow = simulate(&c);
        assert!(slow.response.mean() > fast.response.mean());
    }

    #[test]
    fn trace_is_consistent_and_does_not_perturb() {
        let mut a = AgenticConfig::example(48, 3.0e5);
        a.horizon = 2_000.0;
        let mut cfg = from_agentic(
            &a,
            Server::BlockingPrefill {
                phi: Phi::Constant(1.0),
            },
        );
        cfg.batch_cap = Some(6);
        cfg.warmup = 0.0;
        let (report, trace) = simulate_traced(&cfg);
        let plain = simulate(&cfg);
        assert_eq!(report.turns, plain.turns);
        assert_eq!(report.responses, plain.responses);
        assert_eq!(trace.len() as u64, report.turns);
        assert!(trace.iter().any(|t| t.kind == TurnKind::Miss));
        let mut last = std::collections::HashMap::new();
        for t in &trace {
            assert!(
                t.enqueued <= t.admitted
                    && t.admitted <= t.start
                    && t.start < t.prefill_end
                    && t.prefill_end <= t.end,
                "{t:?}"
            );
            assert_eq!(t.turn == 1, t.kind == TurnKind::Cold);
            let tokens = t.prefill_tokens + t.cached_tokens + t.decode_tokens;
            assert!((tokens - t.context).abs() < 1e-6 * t.context);
            let prev = last.insert(t.session, (t.turn, t.end));
            if let Some((turn, end)) = prev {
                assert_eq!(t.turn, turn + 1);
                assert!(end <= t.enqueued);
            } else {
                assert_eq!(t.turn, 1);
            }
        }
        // Prefills are served one at a time, in order.
        let mut by_start: Vec<&TurnSpan> = trace.iter().collect();
        by_start.sort_by(|a, b| a.start.total_cmp(&b.start));
        for w in by_start.windows(2) {
            assert!(w[0].prefill_end <= w[1].start + 1e-9);
        }
    }

    #[test]
    fn same_seed_same_result() {
        let a = AgenticConfig::example(16, 4.0e5);
        for server in [
            Server::BlockingPrefill {
                phi: Phi::Constant(1.0),
            },
            Server::Ps {
                phi: Phi::Constant(1.0),
            },
        ] {
            let c = from_agentic(&a, server);
            let (x, y) = (simulate(&c), simulate(&c));
            assert_eq!(x.turns, y.turns);
            assert_eq!(x.responses, y.responses);
        }
    }
}
