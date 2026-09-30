"""The synthetic eviction and admission experiment of the paper (App. B,
`tab:sim-evict-dyn`, `tab:sim-admission`, `fig:sim-admission`) on a replica
with the vLLM v1 engine's rules: the seQ program `programs/open_vllm.seq`.

The workload has two classes of open sessions; the engine rules are those of
`programs/replay_vllm.seq`; the time model is the testbed's cost fit. Every
policy is run with the end of a session known (its blocks dropped), so that
the eviction order is the only difference; LRU (vLLM's order) and the
byte-second price are also run with the end unknown, as vLLM's engine is.
Simulator output on a synthetic workload, not a measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache

from . import seq
from .constants import CAL_DECODE_STEP, CAL_PREFILL_LINEAR, OPEN_CAP, OPEN_CAPS, OPEN_SEEDS
from .fmt import ssum
from .models.agentic import EvictionPolicy as P
from .stats import Estimate, replications

PROGRAM = seq.PROGRAMS / "open_vllm.seq"
# Session arrival rates (per s): at the default cap and the priced order, the
# first is at the edge of the eviction window, the second deep inside it.
RATES = (0.03, 0.05)
HORIZON = 21_000.0
WARMUP = 1_000.0
POLICIES = (P.ShortestFirst, P.Density, P.Priced, P.PricedMemory, P.PricedMemoryBlocks, P.Lru)
END_UNKNOWN = (P.Lru, P.PricedMemory)  # also run with the end unknown
SWEEP = (P.ShortestFirst, P.Density, P.PricedMemory)  # the other caps
_CODE = {
    P.ShortestFirst: 0.0,
    P.Density: 1.0,
    P.Priced: 2.0,
    P.PricedMemory: 3.0,
    P.PricedMemoryBlocks: 4.0,
    P.Lru: 5.0,
}


@dataclass(frozen=True)
class OpenEvictRow:
    """One (cap, load, policy, end rule) cell over `OPEN_SEEDS` seeds."""

    cap: int
    rate: float
    policy: P
    end_known: bool
    throughput: Estimate
    hit_rate: Estimate
    ttft: Estimate
    ttft_p99: Estimate
    response: Estimate
    p99: Estimate
    availability: Estimate
    entry_wait: Estimate
    collapsed: int  # seeds whose follow-ups reused under half their prefix


def _run(cap: int, rate: float, policy: P, end_known: bool, seed: int) -> seq.Report:
    return seq.run(
        PROGRAM,
        sets={
            "Lambda": rate,
            "cap": float(cap),
            "policy": _CODE[policy],
            "keep_cache": 0.0 if end_known else 1.0,
        },
        seed=seed,
        horizon=HORIZON,
        warmup=WARMUP,
    )


@cache
def open_row(cap: int, rate: float, policy: P, end_known: bool) -> OpenEvictRow:
    window = HORIZON - WARMUP
    budget = math.floor(CAL_DECODE_STEP / CAL_PREFILL_LINEAR)

    def one(seed):
        r = _run(cap, rate, policy, end_known, seed)
        ttft, resp = r.observe("ttft"), r.observe("response")
        entry, hit, reused = r.observe("entry_wait"), r.observe("hit"), r.observe("reused")
        # decode time per second (Little: the mean number decoding)
        l_d = (ssum(resp.samples) - ssum(ttft.samples)) / window
        return {
            "x": resp.count / window,
            "hit": hit.mean if hit.count > 0 else 1.0,
            "ttft": ttft.mean,
            "ttft_p99": ttft.p99,
            "response": resp.mean,
            "p99": resp.p99,
            "avail": min(max(1.0 - l_d / budget, 0.05), 1.0),
            "entry": entry.mean if entry.count > 0 else 0.0,
            "reused": reused.mean if reused.count > 0 else 1.0,
        }

    ones = seq.parallel(one, range(1, OPEN_SEEDS + 1))

    def est(k):
        return replications([o[k] for o in ones])

    return OpenEvictRow(
        cap=cap,
        rate=rate,
        policy=policy,
        end_known=end_known,
        throughput=est("x"),
        hit_rate=est("hit"),
        ttft=est("ttft"),
        ttft_p99=est("ttft_p99"),
        response=est("response"),
        p99=est("p99"),
        availability=est("avail"),
        entry_wait=est("entry"),
        # under block eviction a miss is often partial: a seed thrashes when
        # follow-up turns reuse less than half of their reusable prefix
        collapsed=sum(1 for o in ones if o["reused"] < 0.5),
    )


@cache
def eviction_open_scenario() -> tuple[OpenEvictRow, ...]:
    """All policies at the default cap with the end known, LRU and the
    byte-second price there with the end unknown, `SWEEP` at the other caps
    with the end known; both loads."""
    cells = []
    for cap in OPEN_CAPS:
        for rate in RATES:
            if cap == OPEN_CAP:
                cells += [(cap, rate, p, True) for p in POLICIES]
                cells += [(cap, rate, p, False) for p in END_UNKNOWN]
            else:
                cells += [(cap, rate, p, True) for p in SWEEP]
    return tuple(open_row(*c) for c in cells)
