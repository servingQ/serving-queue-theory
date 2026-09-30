"""Where the price of a miss is paid, on a replica with the vLLM v1 engine's
rules: the serQ program `programs/price_vllm.sq` (Props. price and decode;
the check `prefill_pays_the_miss`, `tab:sim-ps` rows 8-9).

Poisson turns with no memory limit and the testbed's cost model. A turn
prefills `HIT_TOKENS` (a hit) or `MISS_TOKENS` (a miss), decided by one
uniform draw at arrival, so that the run with a share `δ` of forced misses
sees the same arrivals and draws (common random numbers; the differences
are paired by turn). The prefill stage's mean availability
`r̄ = 1 - L_D/B` turns work into stage time, as in §2.2. Simulator output,
not a measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache

import serq
from analytic import miss_price, num_in_system
from constants import CAL_DECODE_STEP, CAL_PREFILL_LINEAR, CAL_PREFILL_QUADRATIC
from fmt import ssum
from models.batch import paired_differences
from stats import Estimate, batch_means

PROGRAM = serq.PROGRAMS / "price_vllm.sq"
HIT_TOKENS = 512.0
MISS_TOKENS = 5120.0
MISS_SHARE = 0.2
LOAD = 0.6  # prefill load of the baseline, λ E[P]
HORIZON = 500_000.0
WARMUP = 2_000.0


def work(n: float) -> float:
    """Prefill work (s) of `n` tokens on an empty context."""
    return CAL_PREFILL_LINEAR * n + CAL_PREFILL_QUADRATIC * n * n / 2.0


def rate() -> float:
    return LOAD / ((1.0 - MISS_SHARE) * work(HIT_TOKENS) + MISS_SHARE * work(MISS_TOKENS))


def _run(delta: float) -> serq.Report:
    return serq.run(
        PROGRAM,
        sets={
            "Lambda": rate(),
            "pmiss": MISS_SHARE,
            "delta": delta,
            "hitn": HIT_TOKENS,
            "missn": MISS_TOKENS,
        },
        seed=1,
        horizon=HORIZON,
        warmup=WARMUP,
    )


def per_turn(r: serq.Report, name: str) -> list[tuple[int, float]]:
    """An observation per turn, sorted (stably) by session serial."""
    o = r.observe(name)
    assert o is not None, f"no observation `{name}`"
    v = list(zip(o.sessions.tolist(), o.samples.tolist(), strict=True))
    v.sort(key=lambda x: x[0])
    return v


def pair(a, b) -> list[tuple[int, float, float]]:
    """The turns with both observations: (serial, a, b)."""
    i = j = 0
    out = []
    while i < len(a) and j < len(b):
        if a[i][0] < b[j][0]:
            i += 1
        elif a[i][0] > b[j][0]:
            j += 1
        else:
            out.append((a[i][0], a[i][1], b[j][1]))
            i += 1
            j += 1
    return out


@dataclass(frozen=True)
class PriceRun:
    avail: float  # mean prefill availability of the baseline, r̄
    rho_p: float  # effective prefill load λE[P]/r̄
    l_p: Estimate  # baseline number in the prefill stage, λ·TTFT
    l_p_theory: float  # M/G/1 prediction at service P/r̄
    dl_p: Estimate  # rise of the prefill-stage number (paired)
    lo: float
    hi: float
    dl_d: Estimate  # change of the decode-stage number (paired)
    l_d: Estimate  # its baseline level


@cache
def price_scenario(delta: float) -> PriceRun:
    window = HORIZON - WARMUP
    budget = math.floor(CAL_DECODE_STEP / CAL_PREFILL_LINEAR)
    r0, r1 = serq.parallel(_run, [0.0, delta])
    t0, t1 = per_turn(r0, "ttft"), per_turn(r1, "ttft")
    w0, resp0, resp1 = per_turn(r0, "work"), per_turn(r0, "response"), per_turn(r1, "response")
    lam = len(t0) / window

    def scale(xs):
        return [lam * x for x in xs]

    def dec(t, r):
        return [(s, rr - tt) for s, tt, rr in pair(t, r)]

    d0, d1 = dec(t0, resp0), dec(t1, resp1)
    l_d_mean = ssum([x[1] for x in d0]) / window
    avail = min(max(1.0 - l_d_mean / budget, 0.05), 1.0)
    n = float(len(w0))
    ep = ssum([x[1] for x in w0]) / n / avail
    m2 = ssum([x[1] * x[1] for x in w0]) / n / (avail * avail)
    rho = lam * ep
    s_h, s_m = work(HIT_TOKENS) / avail, work(MISS_TOKENS) / avail
    phi = miss_price(lam, m2, rho, s_h, s_m)
    lo = lam * delta * phi
    rho1 = rho + lam * delta * (s_m - s_h)
    return PriceRun(
        avail=avail,
        rho_p=rho,
        l_p=batch_means(scale([x[1] for x in t0]), 20),
        l_p_theory=num_in_system(lam, m2, rho),
        dl_p=batch_means(scale(paired_differences(t0, t1)), 20),
        lo=lo,
        hi=(1.0 - rho) / (1.0 - rho1) * lo if rho1 < 1.0 else math.inf,
        dl_d=batch_means(scale(paired_differences(d0, d1)), 20),
        l_d=batch_means(scale([x[1] for x in d0]), 20),
    )
