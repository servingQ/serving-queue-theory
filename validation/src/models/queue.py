"""Open G/G/c FIFO service centre (paper §2.1–2.2).

With exponential interarrivals and `servers = 1` this is the M/G/1 queue of
the PK formula; with exponential service it is M/M/1. Non-Poisson arrivals
(e.g. `hyperexp_balanced`) leave the model of Props. mm1–cache and enter the
regime of Kingman's bound. serQ's `mg1.sq` draws interarrival and service
times from separate streams, so two runs that differ only in the service law
see the same arrivals (common random numbers).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

import serq
from dist import Dist, exp
from fmt import fmax, ssum
from rng import StdRng
from stats import Estimate, Welford, batch_means


@dataclass
class QueueConfig:
    interarrival: Dist
    service: Dist
    servers: int
    customers: int  # customers whose statistics are recorded
    warmup: int  # customers discarded at the start
    seed: int

    @classmethod
    def mg1(cls, lam: float, service: Dist, customers: int, seed: int) -> QueueConfig:
        """M/G/1 with Poisson arrivals at rate `lam`."""
        return cls(exp(1.0 / lam), service, 1, customers, customers // 10, seed)

    def offered_load(self) -> float:
        return self.service.mean() / (self.interarrival.mean() * self.servers)


@dataclass
class QueueReport:
    waits: np.ndarray  # recorded customers, arrival order
    sojourns: np.ndarray
    wait: Estimate
    sojourn: Estimate
    mean_in_system: float
    arrival_rate: float
    utilization: float
    service: Welford

    def little_residual(self) -> float:
        """Little's law residual `|L - λW| / L`."""
        lw = self.arrival_rate * self.sojourn.mean
        return abs(self.mean_in_system - lw) / self.mean_in_system


def _by_arrival(o: serq.Observe) -> tuple[np.ndarray, np.ndarray]:
    """Values and record times, sorted by session serial."""
    order = np.argsort(o.sessions, kind="stable")
    return o.samples[order], o.times[order]


def _source(cfg: QueueConfig) -> str:
    src = serq.program_path("mg1").read_text()
    src = src.replace("stage svc : fifo;", f"stage svc : fifo({cfg.servers});")
    assert "arrive poisson(lam);" in src, "mg1.sq arrival declaration changed"
    src = src.replace("arrive poisson(lam);", f"arrive renewal({cfg.interarrival.sample_expr()});")
    start = src.find("    set s = law ==")
    assert start >= 0, "mg1 service sampler"
    end = src.index(";", start) + 1
    return src[:start] + f"    set s = {cfg.service.sample_expr()};" + src[end:]


def simulate(cfg: QueueConfig) -> QueueReport:
    """Run serQ's `mg1.sq` with the configured laws on a finite input stream
    of `warmup + customers` arrivals, drained before the report."""
    assert cfg.servers >= 1 and cfg.customers >= 20
    total = cfg.warmup + cfg.customers
    source = _source(cfg)
    rho = cfg.offered_load()
    if rho < 1.0:
        drain = 20.0 * cfg.service.mean() / max(1.0 - rho, 0.01)
    else:
        drain = 20.0 * total * cfg.interarrival.mean()
    margin = max(10.0 * math.sqrt(total), 100.0)
    horizon = cfg.interarrival.mean() * (total + margin) + drain
    attempts = 0
    while True:
        try:
            report = serq.run(
                source=source, seed=cfg.seed, warmup=0.0, horizon=horizon, arrivals=total
            )
            break
        except serq.SerqError as e:
            # IR 6 rejects partial finite runs; replay the same seed with a
            # longer deadline only when arrival generation or drain timed out.
            msg = str(e)
            deadline = "reached before requested arrivals" in msg or "failed to drain" in msg
            attempts += 1
            assert deadline and attempts < 8, f"mg1.sq: {msg}"
        horizon *= 2.0
    waits, _ = _by_arrival(report.observe("wait"))
    sojourns, completions = _by_arrival(report.observe("sojourn"))
    services, _ = _by_arrival(report.observe("service"))
    assert len(waits) >= total and len(sojourns) >= total and len(services) >= total, (
        "mg1.sq did not drain all requested arrivals"
    )
    start = completions[cfg.warmup] - sojourns[cfg.warmup]
    end = completions[total - 1] - sojourns[total - 1]
    span = end - start

    def overlap(a, b):
        return np.maximum(np.minimum(b, end) - np.maximum(a, start), 0.0)

    c, s, v = completions[:total], sojourns[:total], services[:total]
    mean_in_system = ssum(overlap(c - s, c)) / span
    utilization = ssum(overlap(c - v, c)) / span / cfg.servers
    waits = waits[cfg.warmup : total]
    sojourns = sojourns[cfg.warmup : total]
    return QueueReport(
        waits=waits,
        sojourns=sojourns,
        wait=batch_means(waits, 20),
        sojourn=batch_means(sojourns, 20),
        mean_in_system=float(mean_in_system),
        arrival_rate=(cfg.customers - 1) / float(span),
        utilization=float(utilization),
        service=Welford(services[cfg.warmup : total]),
    )


def lindley_waits(cfg: QueueConfig) -> list[float]:
    """Waiting times of a single-server FIFO queue by Lindley's recursion
    `W_{n+1} = max(0, W_n + S_n - A_{n+1})`, drawing from the streams serQ's
    `mg1.sq` uses (`seed`, `seed ^ 0x9E3779B97F4A7C15`). An independent
    check of the event engine: for one server the two agree to rounding."""
    arr = StdRng.seed_from_u64(cfg.seed)
    svc = StdRng.seed_from_u64(cfg.seed ^ 0x9E37_79B9_7F4A_7C15)
    total = cfg.warmup + cfg.customers
    cfg.interarrival.sample(arr)  # the first arrival
    out, w = [], 0.0
    for n in range(total):
        out.append(w)
        s = cfg.service.sample(svc)
        if n + 1 < total:
            a = cfg.interarrival.sample(arr)
            w = fmax(w + s - a, 0.0)
    return out[cfg.warmup :]
