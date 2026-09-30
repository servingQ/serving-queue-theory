"""Sampled-work FIFO and processor-sharing session checks for the paper.

The arrival, service, feedback and batch-cap behaviour executes in
`programs/batch_sampled.sq`; this module holds its configuration and report
shape, `theory.batch` the capacity `φ` and its closed forms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from sim import laws, serq
from sim.agentic import Closed, Open, Population, ProgramClass
from sim.stats import NAN_ESTIMATE, Estimate, Welford, batch_means, quantile
from theory.batch import Constant, Phi, Saturating
from theory.dist import Deterministic, Dist


@dataclass(frozen=True)
class Fifo:
    """One turn at a time at rate 1 (batch cap 1)."""


@dataclass(frozen=True)
class Ps:
    """Continuous batching with chunked prefill as one PS station."""

    phi: Phi


Server = Fifo | Ps


@dataclass
class BatchConfig:
    population: Population
    classes: list[ProgramClass]
    prefill: Dist  # i.i.d. prefill work per turn
    decode: Dist  # i.i.d. decode work per turn
    server: Server
    batch_cap: int | None  # exact LPS: at most this many turns in the batch
    warmup: float
    horizon: float
    seed: int

    @classmethod
    def poisson_turns(cls, rate: float, service: Dist, server: Server, horizon: float, seed: int):
        """Open Poisson turns (`p = 0`) with i.i.d. work `service`."""
        z = Deterministic(0.0)
        return cls(
            population=Open(rate),
            classes=[ProgramClass(1.0, 0.0, z, z, z, z)],
            prefill=service,
            decode=z,
            server=server,
            batch_cap=None,
            warmup=0.05 * horizon,
            horizon=horizon,
            seed=seed,
        )

    def copy(self, **kw) -> BatchConfig:
        return replace(self, **kw)


@dataclass
class BatchReport:
    turns: int
    throughput: float
    sessions_done: int
    hit_rate: float
    response: Welford
    responses: list[tuple[int, float]]  # (turn key, response), sorted by key
    response_ci: Estimate
    p99: float
    ttft: Welford
    ttfts: list[tuple[int, float]]
    ttft_ci: Estimate
    ttft_p99: float
    wait: Welford
    work: Welford
    mean_number: float
    mean_batch: float
    utilization: float
    mean_sessions: float


def _ordered(o: serq.Observe) -> list[tuple[int, float]]:
    keys = (o.sessions << 32) | o.turns
    order = np.argsort(keys, kind="stable")
    return list(zip(keys[order].tolist(), o.samples[order].tolist(), strict=True))


def _ci_and_p99(xs: np.ndarray) -> tuple[Estimate, float]:
    if len(xs) >= 40:
        return batch_means(xs, 20), quantile(xs, 0.99)
    return NAN_ESTIMATE, math.nan


def _replace(src: str, a: str, b: str) -> str:
    assert a in src, f"batch_sampled.sq lacks {a}"
    return src.replace(a, b, 1)


def simulate(cfg: BatchConfig) -> BatchReport:
    """Run the sampled-work session model in serQ."""
    assert len(cfg.classes) == 1, "sampled-work check has one class"
    cls = cfg.classes[0]
    src = (serq.PROGRAMS / "batch_sampled.sq").read_text()
    if isinstance(cfg.population, Closed):
        src = _replace(src, "arrive poisson(Lambda);", "arrive closed(N);")
    defs = {
        "prefill_work": laws.expr(cfg.prefill),
        "decode_work": laws.expr(cfg.decode),
        "tool_time": laws.expr(cls.tool_time),
    }
    if isinstance(cfg.server, Fifo):
        src = _replace(src, "stage svc : ps(capacity());", "stage svc : fifo;")
        phi, rate = Constant(1.0), 1.0
    else:
        phi = cfg.server.phi
        if isinstance(phi, Saturating):
            defs["capacity"] = "min(present, phi_cap) / (1 + beta * (min(present, phi_cap) - 1))"
        rate = phi.c if isinstance(phi, Constant) else 1.0
    if isinstance(phi, Constant):
        beta, phi_cap = 0.0, math.inf
    else:
        beta, phi_cap = phi.beta, (math.inf if phi.cap is None else float(phi.cap))
    if isinstance(cfg.population, Closed):
        n, lam = float(cfg.population.programs), 1.0
    else:
        n, lam = 1.0, cfg.population.rate
    sets = {
        "Lambda": lam,
        "N": n,
        "p": cls.resume_prob,
        "B": math.inf if cfg.batch_cap is None else float(cfg.batch_cap),
        "beta": beta,
        "phi_cap": phi_cap,
        "service_rate": rate,
    }
    r = serq.run(
        source=src, sets=sets, defs=defs, seed=cfg.seed, warmup=cfg.warmup, horizon=cfg.horizon
    )
    response, ttft = r.observe("response"), r.observe("ttft")
    responses, ttfts = _ordered(response), _ordered(ttft)
    rv = np.array([x[1] for x in responses])
    tv = np.array([x[1] for x in ttfts])
    response_ci, p99 = _ci_and_p99(rv)
    ttft_ci, ttft_p99 = _ci_and_p99(tv)
    batch, svc = r.pool("batch"), r.stage("svc")
    return BatchReport(
        turns=response.count,
        throughput=response.count / (cfg.horizon - cfg.warmup),
        sessions_done=r.ended,
        hit_rate=1.0 if cls.resume_prob > 0.0 else math.nan,
        response=Welford(rv),
        responses=responses,
        response_ci=response_ci,
        p99=p99,
        ttft=Welford(tv),
        ttfts=ttfts,
        ttft_ci=ttft_ci,
        ttft_p99=ttft_p99,
        wait=Welford(r.observe("wait").samples),
        work=Welford(r.observe("work").samples),
        mean_number=batch.mean_queue + batch.mean_used,
        mean_batch=batch.mean_used,
        utilization=svc.utilization,
        mean_sessions=r.mean_live,
    )
