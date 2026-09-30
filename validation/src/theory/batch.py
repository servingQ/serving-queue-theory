"""The processor-sharing capacity `φ(n)` of the sampled-work checks, the
mean number at a PS queue with that capacity, and FIFO admission by
footprint (§2, Props. price, decode, footprint)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from pyserq import Rng

from theory.analytic import stationary_mean
from theory.dist import Dist


@dataclass(frozen=True)
class Constant:
    """`φ(n) = c` for `n ≥ 1`: plain processor sharing at rate `c`."""

    c: float

    def __repr__(self) -> str:  # Rust `{:?}`
        from fmt import dbg

        return f"Constant({dbg(self.c)})"


@dataclass(frozen=True)
class Saturating:
    """`φ(n) = m/(1+β(m-1))`, `m = min(n, cap)`."""

    beta: float
    cap: int | None

    def __repr__(self) -> str:
        from fmt import dbg

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


def fifo_admitted(capacity: float, footprint: Dist, rng: Rng) -> int:
    """Requests admitted, in FIFO order, into `capacity` until the first
    whose footprint (drawn from `footprint`) does not fit."""
    used, n = 0.0, 0
    while True:
        k = footprint.sample(rng)
        if used + k > capacity:
            return n
        used += k
        n += 1
