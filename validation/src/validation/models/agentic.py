"""Agent programs sharing one replica with finite KV memory (paper §2.2–2.3, §3).

This is the chain of §2 made executable:

    eviction policy → hit rate p → (E[S], E[S²]) → (ρ, E[Wq]) → throughput

Each program cycles `queue → service (prefill + decode) → tool → queue` and
grows its context every turn; its KV stays resident during the tool call,
which is what creates memory pressure. When a turn needs memory that is not
free, suspended programs are evicted in the order of an `EvictionPolicy`; an
evicted program either loses its KV (its next turn re-prefills the whole
context, a miss) or is written to a slower tier by an `OffloadPolicy`. The
hit rate is not drawn from a fixed `p`: it emerges from memory state. The
program is `programs/agentic_model.seq`; this module renders the
configuration into it and reads the observations back.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum

from .. import seq
from ..analytic import pk_wait
from ..dist import Dist, Uniform, discrete, exp
from ..fmt import number, ssum
from ..stats import NAN_ESTIMATE, Estimate, Welford, batch_means


@dataclass
class CostModel:
    """Per-turn service time: prefilling `new` tokens over `cached` costs
    `overhead + linear·new + quadratic·new·(cached + new/2)`; decoding `out`
    tokens over a context `K` costs `out·(decode_per_token + decode_kv·K)`."""

    overhead: float
    prefill_linear: float
    prefill_quadratic: float
    decode_per_token: float
    decode_kv: float

    def prefill(self, new: float, cached: float) -> float:
        return self.prefill_linear * new + self.prefill_quadratic * new * (cached + 0.5 * new)

    def decode(self, out: float, context: float) -> float:
        return out * (self.decode_per_token + self.decode_kv * context)

    def turn(self, new: float, cached: float, out: float) -> float:
        return self.overhead + self.prefill(new, cached) + self.decode(out, cached + new)

    def miss_penalty(self, c: float) -> float:
        """Extra service a miss pays over a hit for a context of `c` tokens."""
        return self.prefill(c, 0.0)


@dataclass
class ProgramClass:
    weight: float  # relative frequency among new programs
    resume_prob: float  # p_i: another turn when the tool call returns
    initial_tokens: Dist
    new_tokens: Dist
    output_tokens: Dist
    tool_time: Dist


@dataclass(frozen=True)
class Closed:
    """`programs` concurrent programs; a finished one is replaced at once."""

    programs: int


@dataclass(frozen=True)
class Open:
    """New programs arrive as a Poisson process with `rate` per second."""

    rate: float


Population = Closed | Open


class EvictionPolicy(Enum):
    ShortestFirst = "ShortestFirst"
    LongestFirst = "LongestFirst"
    Lru = "Lru"
    Random = "Random"
    Density = "Density"
    Priced = "Priced"
    PricedMemory = "PricedMemory"
    PricedMemoryBlocks = "PricedMemoryBlocks"

    def __str__(self) -> str:  # Rust `{:?}`
        return self.value


class OffloadPolicy(Enum):
    Never = "Never"
    Always = "Always"
    Selective = "Selective"
    Priced = "Priced"


class FetchMode(Enum):
    Async = "Async"
    Blocking = "Blocking"


@dataclass
class AgenticConfig:
    population: Population
    classes: list[ProgramClass]
    cost: CostModel
    kv_capacity: float  # tokens
    max_context: float  # a program ends once its context exceeds this
    eviction: EvictionPolicy
    offload: OffloadPolicy
    tier_bandwidth: float  # tokens per second
    fetch: FetchMode
    warmup: float
    horizon: float
    seed: int

    @classmethod
    def example(cls, programs: int, kv_capacity: float) -> AgenticConfig:
        """A coding-agent-like workload (illustrative, not measured): 20k-token
        initial context, 1k new and 300 output tokens per turn, 90 % resume
        probability, 3 s tool time."""
        return cls(
            population=Closed(programs),
            classes=[
                ProgramClass(
                    1.0, 0.9, Uniform(10_000.0, 30_000.0), exp(1_000.0), exp(300.0), exp(3.0)
                )
            ],
            cost=CostModel(0.005, 2.0e-5, 2.0e-9, 2.0e-4, 0.0),
            kv_capacity=kv_capacity,
            max_context=0.5 * kv_capacity,
            eviction=EvictionPolicy.ShortestFirst,
            offload=OffloadPolicy.Never,
            tier_bandwidth=1.0e6,
            fetch=FetchMode.Async,
            warmup=500.0,
            horizon=5_500.0,
            seed=1,
        )

    def copy(self, **kw) -> AgenticConfig:
        return replace(self, **kw)


@dataclass
class AgenticReport:
    turns: int
    throughput: float
    hit_rate: float
    service: Welford
    waits: list[float]
    wait: Estimate
    response: Welford
    think: Welford
    utilization: float
    mean_resident_kv: float
    mean_programs: float
    evictions: int
    offload_writes: int
    fetches: int
    recomputes: int
    truncated: int
    tier_utilization: float
    recompute_load: float
    stall_load: float
    extra: dict = field(default_factory=dict)

    def pk_wait_prediction(self) -> float:
        """PK from the measured turn rate and service moments (`NaN` when the
        measured load is not below one)."""
        lam = self.throughput
        rho = lam * self.service.mean()
        if rho >= 1.0:
            return math.nan
        return pk_wait(lam, self.service.second_moment(), rho)

    def irtl_residual(self, n: float) -> float:
        """`|N - X(R + Z)| / N` for a closed population of `n` programs."""
        return abs(n - self.throughput * (self.response.mean() + self.think.mean())) / n


def _class_expr(cfg: AgenticConfig, law) -> str:
    classes = list(enumerate(cfg.classes))
    expr = law(classes[-1][1])
    for i, c in reversed(classes[:-1]):
        expr = f"(cls == {i} ? {law(c)} : {expr})"
    return expr


def _replace(src: str, a: str, b: str) -> str:
    assert a in src, f"agentic_model.seq lacks {a}"
    return src.replace(a, b, 1)


_MISS = "(a * size + b * size * size / 2)"
_HIT = "(s0 + a * mean_new + b * mean_new * (size + mean_new / 2) + mean_out * (d + dv * (size + mean_new)))"
_TRANSFER = "(work(link) + size / bw)"


def _source(cfg: AgenticConfig) -> str:
    src = (seq.PROGRAMS / "agentic_model.seq").read_text()
    if isinstance(cfg.population, Open):
        src = _replace(src, "arrive closed(N);", "arrive poisson(Lambda);")
    weights = [c.weight for c in cfg.classes]
    wsum = ssum(weights)
    class_law = (
        "0"
        if len(weights) == 1
        else discrete(
            [float(i) for i in range(len(weights))], [w / wsum for w in weights]
        ).sample_expr()
    )
    src = _replace(
        src,
        "set K = 0; set cold = 1; set p = 0.9;",
        f"set K = 0; set cold = 1; set cls = {class_law}; "
        f"set p = {_class_expr(cfg, lambda c: number(c.resume_prob))}; "
        f"set mean_new = {_class_expr(cfg, lambda c: number(c.new_tokens.mean()))}; "
        f"set mean_out = {_class_expr(cfg, lambda c: number(c.output_tokens.mean()))}; "
        f"set tau = {_class_expr(cfg, lambda c: number(c.tool_time.mean()))};",
    )
    src = _replace(
        src, "~uniform(1e4, 3e4)", _class_expr(cfg, lambda c: c.initial_tokens.sample_expr())
    )
    src = _replace(src, "~exp(1000)", _class_expr(cfg, lambda c: c.new_tokens.sample_expr()))
    src = _replace(src, "~exp(300)", _class_expr(cfg, lambda c: c.output_tokens.sample_expr()))
    src = _replace(src, "~exp(3)", _class_expr(cfg, lambda c: c.tool_time.sample_expr()))
    E = EvictionPolicy
    key = {
        E.ShortestFirst: "evict by (queued, size);",
        E.LongestFirst: "evict by (queued, -size);",
        E.Lru: "evict by (queued, last);",
        E.Random: "evict by (queued, ~uniform(0, 1));",
        E.Density: "evict by (queued, (queued ? 1 : p) * (a + b * size / 2));",
        E.Priced: "evict by (queued, (queued ? 1 : p) * price(svc, s0 + a * mean_new + b * mean_new * (size + mean_new / 2) + mean_out * (d + dv * (size + mean_new)), a * size + b * size * size / 2) / size);",
        E.PricedMemory: "evict by (queued, (queued ? 1 : p) * price(svc, s0 + a * mean_new + b * mean_new * (size + mean_new / 2) + mean_out * (d + dv * (size + mean_new)), a * size + b * size * size / 2) / (size * (queued ? 1 : tau)));",
    }.get(cfg.eviction)
    if key is None:
        raise ValueError("block-level eviction belongs to the batch model")
    src = _replace(src, "evict by (queued, size);", key)
    O, blocking = OffloadPolicy, cfg.fetch == FetchMode.Blocking
    if cfg.offload == O.Never:
        spill = "0"
    elif cfg.offload == O.Always:
        spill = "!queued"
    elif cfg.offload == O.Selective:
        spill = (
            f"!queued && {_TRANSFER} < p * {_MISS}"
            if blocking
            else f"!queued && {_TRANSFER} < p * {_MISS} * (1 + queued(slot))"
        )
    else:
        spill = (
            f"!queued && {_TRANSFER} < {_MISS}"
            if blocking
            else f"!queued && {_TRANSFER} < p * price(svc, {_HIT}, {_MISS})"
        )
    src = _replace(src, "when (0)", f"when ({spill})")
    if cfg.offload == O.Never:
        fetch = "0"
    elif cfg.offload == O.Always:
        fetch = "1"
    elif blocking:
        fetch = "work(link) + K / bw < a * K + b * K * K / 2"
    elif cfg.offload == O.Selective:
        fetch = "work(link) + K / bw < (a * K + b * K * K / 2) * (1 + queued(slot))"
    else:
        fetch = "work(link) + K / bw < price(svc, s0 + a * mean_new + b * mean_new * (K + mean_new / 2) + mean_out * (d + dv * (K + mean_new)), a * K + b * K * K / 2)"
    src = _replace(src, "blocking == 0 && 1", f"blocking == 0 && ({fetch})")
    src = _replace(src, "blocking == 1 && 1", f"blocking == 1 && ({fetch})")
    return src


def simulate(cfg: AgenticConfig) -> AgenticReport:
    """Run the configured agentic system in seQ."""
    assert cfg.classes and cfg.warmup < cfg.horizon
    if isinstance(cfg.population, Closed):
        n, rate = float(cfg.population.programs), 0.05
    else:
        n, rate = 1.0, cfg.population.rate
    c = cfg.cost
    sets = {
        "N": n,
        "Lambda": rate,
        "C": cfg.kv_capacity,
        "maxctx": cfg.max_context,
        "s0": c.overhead,
        "a": c.prefill_linear,
        "b": c.prefill_quadratic,
        "d": c.decode_per_token,
        "dv": c.decode_kv,
        "bw": cfg.tier_bandwidth,
        "blocking": 1.0 if cfg.fetch == FetchMode.Blocking else 0.0,
    }
    r = seq.run(
        source=_source(cfg), sets=sets, seed=cfg.seed, warmup=cfg.warmup, horizon=cfg.horizon
    )

    def values(name):
        o = r.observe(name)
        assert o is not None, f"agentic_model.seq lacks {name}"
        return o.samples

    responses, waits, service = values("response"), values("wait"), values("service")
    think, hits = values("think"), values("hit")
    recompute, stall = values("recompute_work"), values("stall")
    span = cfg.horizon - cfg.warmup
    kv, slot, link = r.pool("kv"), r.pool("slot"), r.stage("link")
    fetched, truncated = r.observe("fetched"), r.observe("truncated")
    return AgenticReport(
        turns=len(responses),
        throughput=len(responses) / span,
        hit_rate=Welford(hits).mean(),
        service=Welford(service),
        wait=batch_means(waits, 20) if len(waits) >= 40 else NAN_ESTIMATE,
        waits=waits,
        response=Welford(responses),
        think=Welford(think),
        utilization=slot.mean_used,
        mean_resident_kv=kv.mean_used + kv.mean_cached,
        mean_programs=r.mean_live,
        evictions=kv.evicted_entries,
        offload_writes=kv.spills,
        fetches=fetched.count if fetched else 0,
        recomputes=int((hits == 0.0).sum()),
        truncated=truncated.count if truncated else 0,
        tier_utilization=link.utilization,
        recompute_load=ssum(recompute) / span,
        stall_load=ssum(stall) / span,
    )
