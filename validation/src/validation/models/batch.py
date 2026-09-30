"""Sampled-work FIFO and processor-sharing session checks for the paper.

The arrival, service, feedback and batch-cap behaviour executes in
`programs/batch_sampled.seq`; this module holds its configuration, report
shape and analytic helpers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from .. import seq
from ..analytic import stationary_mean
from ..dist import Deterministic, Dist
from ..rng import StdRng
from ..stats import NAN_ESTIMATE, Estimate, Welford, batch_means, quantile
from .agentic import Closed, Open, Population, ProgramClass


@dataclass(frozen=True)
class Constant:
    """`φ(n) = c` for `n ≥ 1`: plain processor sharing at rate `c`."""

    c: float

    def __repr__(self) -> str:  # Rust `{:?}`
        from ..fmt import dbg

        return f"Constant({dbg(self.c)})"


@dataclass(frozen=True)
class Saturating:
    """`φ(n) = m/(1+β(m-1))`, `m = min(n, cap)`."""

    beta: float
    cap: int | None

    def __repr__(self) -> str:
        from ..fmt import dbg

        cap = "None" if self.cap is None else f"Some({self.cap})"
        return f"Saturating {{ beta: {dbg(self.beta)}, cap: {cap} }}"


Phi = Constant | Saturating


def phi_rate(phi: Phi, n: int) -> float:
    if n == 0:
        return 0.0
    if isinstance(phi, Constant):
        return phi.c
    m = float(n if phi.cap is None else min(n, phi.cap))
    return m / (1.0 + phi.beta * (m - 1.0))


def phi_limit(phi: Phi) -> float:
    """`sup_n φ(n)`."""
    if isinstance(phi, Constant):
        return phi.c
    if phi.cap is not None:
        return phi_rate(phi, phi.cap)
    if phi.beta > 0.0:
        return 1.0 / phi.beta
    return math.inf


def ps_mean_number(phi: Phi, rho: float) -> float:
    """Mean number at a PS queue of capacity `φ` and offered load `ρ`:
    `Σ n π(n)`, `π(n) ∝ ρⁿ / Π_{k≤n} φ(k)`; for `φ ≡ C` this is `ρ/(C-ρ)`."""
    assert rho < phi_limit(phi), f"load {rho} ≥ capacity {phi_limit(phi)}"
    w, z = [1.0], 1.0
    for n in range(1, 10_000_000):
        wn = w[n - 1] * rho / phi_rate(phi, n)
        w.append(wn)
        z += wn
        if wn < 1e-16 * z and n > 10:
            break
    return stationary_mean(w, 1.0)


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


def _ordered(o: seq.Observe) -> list[tuple[int, float]]:
    keys = (o.sessions << 32) | o.turns
    order = np.argsort(keys, kind="stable")
    return list(zip(keys[order].tolist(), o.samples[order].tolist(), strict=True))


def _ci_and_p99(xs: np.ndarray) -> tuple[Estimate, float]:
    if len(xs) >= 40:
        return batch_means(xs, 20), quantile(xs, 0.99)
    return NAN_ESTIMATE, math.nan


def _replace(src: str, a: str, b: str) -> str:
    assert a in src, f"batch_sampled.seq lacks {a}"
    return src.replace(a, b, 1)


def simulate(cfg: BatchConfig) -> BatchReport:
    """Run the sampled-work session model in seQ."""
    assert len(cfg.classes) == 1, "sampled-work check has one class"
    cls = cfg.classes[0]
    src = (seq.PROGRAMS / "batch_sampled.seq").read_text()
    if isinstance(cfg.population, Closed):
        src = _replace(src, "arrive poisson(Lambda);", "arrive closed(N);")
    src = _replace(src, "~exp(1)", cfg.prefill.sample_expr())
    src = _replace(src, "~det(0)", cfg.decode.sample_expr())
    src = _replace(src, "run tool (~det(0));", f"run tool ({cls.tool_time.sample_expr()});")
    if isinstance(cfg.server, Fifo):
        src = _replace(src, "stage svc : ps(service_rate);", "stage svc : fifo;")
        phi, rate = Constant(1.0), 1.0
    else:
        phi = cfg.server.phi
        if isinstance(phi, Saturating):
            src = _replace(
                src,
                "stage svc : ps(service_rate);",
                "stage svc : ps(min(n, phi_cap) / (1 + beta * (min(n, phi_cap) - 1)));",
            )
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
    r = seq.run(source=src, sets=sets, seed=cfg.seed, warmup=cfg.warmup, horizon=cfg.horizon)
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


def paired_differences(a, b) -> list[float]:
    """Per-turn differences `b - a` of two per-turn series sorted by key,
    paired by key (runs with common random numbers)."""
    i = j = 0
    out = []
    while i < len(a) and j < len(b):
        if a[i][0] < b[j][0]:
            i += 1
        elif a[i][0] > b[j][0]:
            j += 1
        else:
            out.append(b[j][1] - a[i][1])
            i += 1
            j += 1
    return out


def fifo_admitted(capacity: float, footprint: Dist, rng: StdRng) -> int:
    """Requests admitted, in FIFO order, into `capacity` until the first
    whose footprint (drawn from `footprint`) does not fit."""
    used, n = 0.0, 0
    while True:
        k = footprint.sample(rng)
        if used + k > capacity:
            return n
        used += k
        n += 1
