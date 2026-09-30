"""Lindley's recursion for the single-server FIFO queue (paper §2.1)."""

from __future__ import annotations

from pyserq import Rng

from fmt import fmax
from theory.dist import Dist


def lindley_waits(
    interarrival: Dist, service: Dist, customers: int, warmup: int, seed: int
) -> list[float]:
    """Waiting times of a single-server FIFO queue by Lindley's recursion
    `W_{n+1} = max(0, W_n + S_n - A_{n+1})`, drawing from the streams serQ's
    `mg1.sq` uses (`seed`, `seed ^ 0x9E3779B97F4A7C15`), the first `warmup` of
    `warmup + customers` dropped. An independent check of the event engine:
    for one server the two agree to rounding."""
    arr = Rng(seed)
    svc = Rng(seed ^ 0x9E37_79B9_7F4A_7C15)
    total = warmup + customers
    interarrival.sample(arr)  # the first arrival
    out, w = [], 0.0
    for n in range(total):
        out.append(w)
        s = service.sample(svc)
        if n + 1 < total:
            a = interarrival.sample(arr)
            w = fmax(w + s - a, 0.0)
    return out[warmup:]
