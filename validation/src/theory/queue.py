"""Lindley's recursion for the single-server FIFO queue (paper §2.1)."""

from __future__ import annotations

from pyserq import Rng

from fmt import fmax
from theory.dist import Dist


def _init_rng(seed: int, serial: int) -> Rng:
    """IR 11's init stream: SplitMix64(seed, serial, turn=0, kind=1).

    serQ v0.1.3, src/engine/interp.rs::substream. Reproduce only the seed
    derivation here; waiting times still come from Lindley's recursion.
    """
    mask = (1 << 64) - 1
    x = seed
    for v in (serial, 0, 1):
        x = (x + 0x9E37_79B9_7F4A_7C15 + v) & mask
        x = ((x ^ (x >> 30)) * 0xBF58_476D_1CE4_E5B9) & mask
        x = ((x ^ (x >> 27)) * 0x94D0_49BB_1331_11EB) & mask
        x ^= x >> 31
    return Rng(x)


def lindley_waits(
    interarrival: Dist, service: Dist, customers: int, warmup: int, seed: int
) -> list[float]:
    """Waiting times of a single-server FIFO queue by Lindley's recursion
    `W_{n+1} = max(0, W_n + S_n - A_{n+1})`, drawing from the streams serQ's
    `mg1.sq` uses: arrivals from `seed`, service from each session's init
    stream (IR 11), with the first `warmup` of `warmup + customers` dropped.
    An independent check of the event engine: for one server the two agree
    to rounding."""
    arr = Rng(seed)
    total = warmup + customers
    interarrival.sample(arr)  # the first arrival
    out, w = [], 0.0
    for n in range(total):
        out.append(w)
        s = service.sample(_init_rng(seed, n))
        if n + 1 < total:
            a = interarrival.sample(arr)
            w = fmax(w + s - a, 0.0)
    return out[warmup:]
