//! Routing follow-up turns across replicas (paper §3.3, Prop. routing).
//!
//! `J` single-server FIFO replicas with unbounded KV memory. A program's KV
//! lives on the replica that served its last turn. For each follow-up turn
//! a [`RoutePolicy`] picks a replica; a turn served away from the KV either
//! recomputes the prefix (a miss) or, if the policy allows, migrates the KV
//! over a shared FIFO link first.
//!
//! New programs are placed with a skew (`hot_fraction` of them on replica
//! 0), standing in for tenant or prefix-hash affinity. Under strict session
//! affinity that skew is permanent, which is the situation Prop. routing
//! (ii) is about.
//!
//! Queue waits are exact: a FIFO single server's wait is its unfinished
//! work, tracked as the time it next becomes idle.

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};

use crate::analytic::{lookahead_cost, myopic_cost};
use crate::dist::Dist;
use crate::models::agentic::{CostModel, ProgramClass};
use crate::stats::{Estimate, Welford, batch_means, quantile};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RoutePolicy {
    /// Always the replica holding the KV (session affinity, `M = ∞`).
    Affinity,
    /// Least unfinished work, ignoring where the KV is.
    LeastLoaded,
    /// Least unfinished work; off-home the state is fetched over the link
    /// when that is cheaper than recomputing it (a shared KV store). The
    /// "always move" alternative of Prop. routing (i), against which the
    /// inversion load `ρ*` is defined.
    LeastLoadedFetch,
    /// KV-aware myopic: `min_j W_j + S_j`, with `S_j` a miss off-home.
    Myopic,
    /// `min_j W_j + S_j + M_j + F_j` with `F_j = 0`, where moving may
    /// either recompute or migrate the KV (whichever is cheaper).
    Lookahead,
}

#[derive(Clone, Debug)]
pub struct RoutingConfig {
    pub replicas: usize,
    /// Program arrivals per second (Poisson).
    pub program_rate: f64,
    pub class: ProgramClass,
    pub cost: CostModel,
    pub policy: RoutePolicy,
    /// Fraction of new programs placed on replica 0; the rest uniformly.
    pub hot_fraction: f64,
    /// Migration link bandwidth, tokens/s.
    pub migrate_bandwidth: f64,
    pub warmup: f64,
    pub horizon: f64,
    pub seed: u64,
}

impl RoutingConfig {
    /// Four replicas, half of the new programs on replica 0. Illustrative
    /// numbers, not measured.
    pub fn example(program_rate: f64, policy: RoutePolicy) -> Self {
        Self {
            replicas: 4,
            program_rate,
            class: ProgramClass {
                weight: 1.0,
                resume_prob: 0.9,
                initial_tokens: Dist::Uniform {
                    lo: 5_000.0,
                    hi: 15_000.0,
                },
                new_tokens: Dist::exp(500.0),
                output_tokens: Dist::exp(200.0),
                tool_time: Dist::exp(2.0),
            },
            cost: CostModel {
                overhead: 0.005,
                prefill_linear: 2.0e-5,
                prefill_quadratic: 2.0e-9,
                decode_per_token: 2.0e-4,
                decode_kv: 0.0,
            },
            policy,
            hot_fraction: 0.5,
            migrate_bandwidth: 2.0e6,
            warmup: 500.0,
            horizon: 10_500.0,
            seed: 1,
        }
    }
}

#[derive(Clone, Debug)]
pub struct RoutingReport {
    pub turns: u64,
    /// Ready-to-done time of follow-up turns, completion order.
    pub responses: Vec<f64>,
    pub response: Estimate,
    pub p99: f64,
    pub hit_rate: f64,
    pub migrations: u64,
    pub recomputes: u64,
    /// Busy fraction per replica.
    pub utilization: Vec<f64>,
    pub service: Welford,
    /// Mean context (tokens) of follow-up turns at their routing decision:
    /// what a migration would move.
    pub mean_context: f64,
}

struct Prog {
    home: usize,
    context: f64,
}

#[derive(Clone, Copy)]
enum Choice {
    Hit,
    Recompute,
    Migrate,
}

pub fn simulate(cfg: &RoutingConfig) -> RoutingReport {
    use crate::engine::{Model, Scheduler, run};

    struct Sim {
        cfg: RoutingConfig,
        rng: StdRng,
        progs: Vec<Prog>,
        free_at: Vec<f64>,
        link_free_at: f64,
        ready_at: Vec<f64>,
        first: Vec<bool>,
        responses: Vec<f64>,
        busy: Vec<f64>,
        follow_ups: u64,
        hits: u64,
        migrations: u64,
        recomputes: u64,
        service: Welford,
        turns: u64,
        context: Welford,
    }

    impl Sim {
        fn place(&mut self) -> usize {
            if self.rng.random::<f64>() < self.cfg.hot_fraction {
                0
            } else {
                self.rng.random_range(0..self.cfg.replicas)
            }
        }

        fn wait(&self, j: usize, now: f64) -> f64 {
            (self.free_at[j] - now).max(0.0)
        }

        fn route(&mut self, id: usize, now: f64, new: f64, out: f64) -> (usize, Choice, f64) {
            let c = self.progs[id].context;
            let home = self.progs[id].home;
            let hit_s = self.cfg.cost.turn(new, c, out);
            let miss_s = self.cfg.cost.turn(c + new, 0.0, out);
            let link_wait = (self.link_free_at - now).max(0.0);
            let migrate = link_wait + c / self.cfg.migrate_bandwidth;
            let j_range = 0..self.cfg.replicas;
            let pick = |cost: &dyn Fn(usize) -> (f64, Choice)| {
                j_range
                    .clone()
                    .map(|j| (j, cost(j)))
                    .min_by(|a, b| a.1.0.total_cmp(&b.1.0).then(a.0.cmp(&b.0)))
                    .map(|(j, (_, ch))| (j, ch))
                    .expect("replicas > 0")
            };
            let (j, choice) = match self.cfg.policy {
                RoutePolicy::Affinity => (home, Choice::Hit),
                RoutePolicy::LeastLoaded => {
                    let (j, _) = pick(&|j| (self.wait(j, now), Choice::Hit));
                    (
                        j,
                        if j == home {
                            Choice::Hit
                        } else {
                            Choice::Recompute
                        },
                    )
                }
                RoutePolicy::LeastLoadedFetch => {
                    let (j, _) = pick(&|j| (self.wait(j, now), Choice::Hit));
                    if j == home {
                        (j, Choice::Hit)
                    } else if migrate < miss_s - hit_s {
                        (j, Choice::Migrate)
                    } else {
                        (j, Choice::Recompute)
                    }
                }
                RoutePolicy::Myopic => pick(&|j| {
                    if j == home {
                        (myopic_cost(self.wait(j, now), hit_s), Choice::Hit)
                    } else {
                        (myopic_cost(self.wait(j, now), miss_s), Choice::Recompute)
                    }
                }),
                RoutePolicy::Lookahead => pick(&|j| {
                    let w = self.wait(j, now);
                    if j == home {
                        (lookahead_cost(w, hit_s, 0.0, 0.0), Choice::Hit)
                    } else {
                        // Migration overlaps the queue wait at the target.
                        let mig = w.max(migrate) + hit_s;
                        let rec = lookahead_cost(w, miss_s, 0.0, 0.0);
                        if mig < rec {
                            (mig, Choice::Migrate)
                        } else {
                            (rec, Choice::Recompute)
                        }
                    }
                }),
            };
            let s = match choice {
                Choice::Hit => hit_s,
                Choice::Recompute => miss_s,
                Choice::Migrate => hit_s,
            };
            (j, choice, s)
        }
    }

    enum Ev {
        Arrival,
        Ready(usize),
        Done(usize),
    }

    impl Model for Sim {
        type Event = Ev;

        fn handle(&mut self, ev: Ev, s: &mut Scheduler<Ev>) {
            let now = s.now();
            let warm = now >= self.cfg.warmup;
            match ev {
                Ev::Arrival => {
                    s.after(
                        Dist::exp(1.0 / self.cfg.program_rate).sample(&mut self.rng),
                        Ev::Arrival,
                    );
                    let home = self.place();
                    self.progs.push(Prog { home, context: 0.0 });
                    self.ready_at.push(now);
                    self.first.push(true);
                    let id = self.progs.len() - 1;
                    s.at(now, Ev::Ready(id));
                }
                Ev::Ready(id) => {
                    self.ready_at[id] = now;
                    let first = self.first[id];
                    let cls = &self.cfg.class;
                    let new = if first {
                        cls.initial_tokens.sample(&mut self.rng)
                    } else {
                        cls.new_tokens.sample(&mut self.rng)
                    };
                    let out = cls.output_tokens.sample(&mut self.rng);
                    let (j, choice, svc, start) = if first {
                        let j = self.progs[id].home;
                        let svc = self.cfg.cost.turn(new, 0.0, out);
                        (j, Choice::Recompute, svc, self.free_at[j].max(now))
                    } else {
                        if warm {
                            self.context.push(self.progs[id].context);
                        }
                        let (j, choice, svc) = self.route(id, now, new, out);
                        let mut ready = now;
                        if let Choice::Migrate = choice {
                            let c = self.progs[id].context;
                            let st = self.link_free_at.max(now);
                            self.link_free_at = st + c / self.cfg.migrate_bandwidth;
                            ready = self.link_free_at;
                        }
                        (j, choice, svc, self.free_at[j].max(ready))
                    };
                    self.free_at[j] = start + svc;
                    if warm {
                        self.busy[j] += svc;
                        self.service.push(svc);
                        if !first {
                            self.follow_ups += 1;
                            match choice {
                                Choice::Hit => self.hits += 1,
                                Choice::Migrate => {
                                    self.hits += 1;
                                    self.migrations += 1
                                }
                                Choice::Recompute => self.recomputes += 1,
                            }
                        }
                    }
                    let p = &mut self.progs[id];
                    p.home = j;
                    p.context += new + out;
                    s.at(self.free_at[j], Ev::Done(id));
                }
                Ev::Done(id) => {
                    let first = std::mem::replace(&mut self.first[id], false);
                    if warm {
                        self.turns += 1;
                        if !first {
                            self.responses.push(now - self.ready_at[id]);
                        }
                    }
                    if self.rng.random::<f64>() < self.cfg.class.resume_prob {
                        let z = self.cfg.class.tool_time.sample(&mut self.rng);
                        s.after(z, Ev::Ready(id));
                    }
                }
            }
        }
    }

    let mut m = Sim {
        cfg: cfg.clone(),
        rng: StdRng::seed_from_u64(cfg.seed),
        progs: vec![],
        free_at: vec![0.0; cfg.replicas],
        link_free_at: 0.0,
        ready_at: vec![],
        first: vec![],
        responses: vec![],
        busy: vec![0.0; cfg.replicas],
        follow_ups: 0,
        hits: 0,
        migrations: 0,
        recomputes: 0,
        service: Welford::new(),
        turns: 0,
        context: Welford::new(),
    };
    let mut s = Scheduler::new();
    s.at(0.0, Ev::Arrival);
    run(&mut m, &mut s, cfg.horizon);
    let span = cfg.horizon - cfg.warmup;
    RoutingReport {
        turns: m.turns,
        response: batch_means(&m.responses, 20),
        p99: quantile(&m.responses, 0.99),
        responses: m.responses,
        hit_rate: m.hits as f64 / m.follow_ups.max(1) as f64,
        migrations: m.migrations,
        recomputes: m.recomputes,
        utilization: m.busy.iter().map(|b| b / span).collect(),
        service: m.service,
        mean_context: m.context.mean(),
    }
}
