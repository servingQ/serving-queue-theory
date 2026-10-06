"""Routing follow-up turns across replicas (paper §3.3, Prop. routing).

The executable deployment is serQ's `routing.sq`; this module keeps the
configuration and report types used by the paper tables.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from fmt import number, rround
from sim import laws, serq
from sim.agentic import CostModel, ProgramClass
from sim.stats import Estimate, Welford
from theory.dist import Uniform, exp


class RoutePolicy(Enum):
    Affinity = 0  # always the replica holding the KV
    LeastLoaded = 1  # least unfinished work, ignoring the KV
    LeastLoadedFetch = 2  # least unfinished work; fetch the state when cheaper
    Myopic = 3  # min_j W_j + S_j
    Lookahead = 4  # min_j W_j + S_j + M_j + F_j, F_j = 0


@dataclass
class RoutingConfig:
    replicas: int
    program_rate: float
    cls: ProgramClass
    cost: CostModel
    policy: RoutePolicy
    hot_fraction: float  # share of new programs placed on replica 0
    migrate_bandwidth: float  # tokens/s
    warmup: float
    horizon: float
    seed: int

    @classmethod
    def example(cls, program_rate: float, policy: RoutePolicy) -> RoutingConfig:
        """Four replicas, half of the new programs on replica 0 (illustrative)."""
        return cls(
            replicas=4,
            program_rate=program_rate,
            cls=ProgramClass(
                1.0, 0.9, Uniform(5_000.0, 15_000.0), exp(500.0), exp(200.0), exp(2.0)
            ),
            cost=CostModel(0.005, 2.0e-5, 2.0e-9, 2.0e-4, 0.0),
            policy=policy,
            hot_fraction=0.5,
            migrate_bandwidth=2.0e6,
            warmup=500.0,
            horizon=10_500.0,
            seed=1,
        )

    def copy(self, **kw) -> RoutingConfig:
        return replace(self, **kw)


@dataclass
class RoutingReport:
    turns: int
    responses: list[float]
    response: Estimate
    p99: float
    hit_rate: float
    migrations: int
    recomputes: int
    utilization: list[float]
    service: Welford
    mean_context: float
    link_utilization: float


def simulate(cfg: RoutingConfig) -> RoutingReport:
    assert cfg.replicas == 4, "routing.sq currently declares four replicas"
    defs = {
        "initial_tokens": laws.expr(cfg.cls.initial_tokens),
        "new_tokens": laws.expr(cfg.cls.new_tokens),
        "output_tokens": laws.expr(cfg.cls.output_tokens),
        "tool_time": laws.expr(cfg.cls.tool_time),
    }
    c = cfg.cost
    sets = {
        "rate": number(cfg.program_rate),
        "hot": number(cfg.hot_fraction),
        "policy": str(cfg.policy.value),
        "s0": number(c.overhead),
        "a": number(c.prefill_linear),
        "b": number(c.prefill_quadratic),
        "d": number(c.decode_per_token),
        "dv": number(c.decode_kv),
        "p": number(cfg.cls.resume_prob),
        "bw": number(cfg.migrate_bandwidth),
    }
    r = serq.run(
        serq.program_path("routing"),
        sets=sets,
        defs=defs,
        seed=cfg.seed,
        warmup=cfg.warmup,
        horizon=cfg.horizon,
    )
    response, hitrate = r.observe("response"), r.observe("hit")
    migration = r.observe("migration")
    hits = int(rround(hitrate.mean * hitrate.count))
    service = r.observe("service")
    context = r.observe("context")
    link = r.stage("link")
    return RoutingReport(
        turns=r.turns,
        responses=response.samples,
        response=Estimate(response.mean, response.ci),
        p99=response.p99,
        hit_rate=hitrate.mean,
        migrations=migration.count if migration else 0,
        recomputes=max(hitrate.count - hits, 0),
        utilization=[s.utilization for s in r.stages_named("rep")],
        service=Welford(service.samples if service else []),
        mean_context=context.mean if context else 0.0,
        link_utilization=link.utilization if link else 0.0,
    )
