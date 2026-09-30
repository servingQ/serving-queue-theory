"""§4.2's trace replay (paper `sec:sim`) on a replica with the vLLM v1
engine's rules: the serQ program `programs/replay_vllm.sq`, on the production
sessions of `workload.weka()`.

The program is the replica of the trace-replay scenario (same corpus,
Poisson session arrivals, live-session cap, batch cap 8, RBLN cost fit,
eviction by price per byte-second) with the engine rules that the
request-for-request comparison of serQ against the real vLLM scheduler
established (`research/seq-replay42.md`). The rows are computed from the
program's per-turn observations: a turn hits iff it reuses its whole
reusable prefix; prefill service in stage time is `work / availability`,
the availability being the share of the iteration budget the decoding turns
leave; the prefill wait is the time to first token less that service (one
FIFO server); the mean number in the prefill stage `L_P` is the TTFT rate
(Little's law). Simulator output on a replayed workload, not a measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache

import serq
import workload
from analytic import finite_source_price, miss_price
from constants import (
    CAL_DECODE_STEP,
    CAL_PREFILL_LINEAR,
    TRACE_CAP_FACTORS,
    TRACE_CAP_OPEN,
    TRACE_HORIZON,
    TRACE_POOLS,
    TRACE_RATES,
    TRACE_WARMUP,
)
from fmt import rround, ssum
from models.agentic import EvictionPolicy
from stats import Estimate, replications

PROGRAM = serq.PROGRAMS / "replay_vllm.sq"
SEEDS = 20  # per replay cell
PRICE_SEEDS = 20  # per forced-miss cell
BLOCK_TOKENS = 16.0


@dataclass(frozen=True)
class TraceRow:
    """One (rate, pool, cap) cell over the seeds."""

    rate: float
    kv: float
    cap: int
    policy: EvictionPolicy
    hit_rate: Estimate
    reused: Estimate  # mean share of the reusable prefix reused
    sessions: Estimate  # mean live sessions
    entry_wait: Estimate
    rho: Estimate  # prefill load in stage time
    cv2: Estimate  # CV² of follow-up prefill work
    mixture_share: Estimate  # share of Var[S] from the hit/miss mixture
    wait: Estimate  # observed mean prefill wait
    pk_wait: Estimate  # PK from the measured λ, E[S], E[S²]
    ttft: Estimate
    ttft_p99: Estimate
    prefill_number: Estimate
    availability: Estimate
    truncated: Estimate
    throughput: Estimate


@dataclass(frozen=True)
class TracePriceRow:
    rate: float
    delta: float
    rho: float  # baseline prefill load
    live: float  # baseline mean live sessions
    rho1: float  # the load the added work implies
    live1: float
    l_p: float
    dl_p: Estimate
    lo: float
    hi: float
    finite: float  # M/M/1//N price of the added mean work
    hit_rate: float


def trace_cap(corpus: workload.TraceCorpus, kv: float, factor: float) -> int:
    """Live-session cap for a pool: `factor · pool / mean final context`, at
    least 1; `TRACE_CAP_OPEN` for an infinite pool."""
    if math.isfinite(kv):
        return max(int(math.floor(factor * kv / corpus.mean_final_context())), 1)
    return TRACE_CAP_OPEN


@dataclass(frozen=True)
class Cell:
    rate: float
    kv: float
    cap: int
    delta: float
    trace: str | None  # corpus file, or the program's own
    p: float  # scheduler estimates of the price key
    tau: float


def _run(c: Cell, seed: int) -> serq.Report:
    return serq.run(
        PROGRAM,
        sets={
            "Lambda": c.rate,
            "cap": float(c.cap),
            "C": c.kv if math.isfinite(c.kv) else 1e15,
            "delta": c.delta,
            "p": c.p,
            "tau": c.tau,
        },
        seed=seed,
        horizon=TRACE_HORIZON,
        warmup=TRACE_WARMUP,
        trace=c.trace,
    )


def _runs(c: Cell, seeds: int) -> list[serq.Report]:
    return serq.parallel(lambda s: _run(c, s), range(1, seeds + 1))


def by_turn(r: serq.Report, name: str) -> dict[tuple[int, int], float]:
    """Per-turn observations by (session, turn), in key order."""
    o = r.observe(name)
    assert o is not None, f"no observation `{name}`"
    d = dict(
        zip(
            zip(o.sessions.tolist(), o.turns.tolist(), strict=True), o.samples.tolist(), strict=True
        )
    )
    return dict(sorted(d.items()))


def mean_obs(r: serq.Report, name: str) -> float:
    o = r.observe(name)
    return 0.0 if o.count == 0 else o.mean


@dataclass(frozen=True)
class Queue:
    """The prefill queue of one run, in stage time."""

    n: int
    lam: float
    es: float
    es2: float
    rho: float
    avail: float
    wait: float
    l_p: float


def queue(r: serq.Report) -> Queue:
    window = TRACE_HORIZON - TRACE_WARMUP
    kind, work, ttft, done = (by_turn(r, k) for k in ("kind", "work", "ttft", "done"))
    # turns with every observation after the warm-up
    keys = [k for k in kind if k in ttft and k in work and k in done]
    # availability: the share of an iteration's token budget the decoding
    # turns leave, 1 - L_D/B, L_D the time-average number decoding
    budget = math.floor(CAL_DECODE_STEP / CAL_PREFILL_LINEAR)
    l_d = ssum([done[k] - ttft[k] for k in keys]) / window
    avail = min(max(1.0 - l_d / budget, 0.05), 1.0)
    n = len(keys)
    s1 = s2 = t = 0.0
    for k in keys:
        st = work[k] / avail
        s1 += st
        s2 += st * st
        t += ttft[k]
    lam = n / window
    nn = float(max(n, 1))
    es, es2 = s1 / nn, s2 / nn
    return Queue(n, lam, es, es2, lam * es, avail, (t - s1) / nn, t / window)


def _mv(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return 0.0, 0.0
    mu = ssum(xs) / len(xs)
    var = ssum([(x - mu) * (x - mu) for x in xs]) / (len(xs) - 1) if len(xs) > 1 else 0.0
    return mu, var


@cache
def trace_row_of(c: Cell) -> TraceRow:
    window = TRACE_HORIZON - TRACE_WARMUP

    def one(r: serq.Report) -> dict:
        q = queue(r)
        kind, work = by_turn(r, "kind"), by_turn(r, "work")
        h, m = [], []
        for k, v in kind.items():
            if k not in work:
                continue
            if int(v) == 1:
                h.append(work[k])
            elif int(v) == 2:
                m.append(work[k])
        p = len(h) / max(len(h) + len(m), 1)
        (mh, vh), (mm, vm) = _mv(h), _mv(m)
        between = p * (1.0 - p) * ((mm - mh) * (mm - mh))
        var = between + p * vh + (1.0 - p) * vm
        mean = p * mh + (1.0 - p) * mm
        ttft = r.observe("ttft")
        return {
            "hit": mean_obs(r, "hit"),
            "reused": mean_obs(r, "reused"),
            "live": r.pool("live").mean_holders,
            "entry": mean_obs(r, "entry_wait"),
            "rho": q.rho,
            "cv2": var / (mean * mean) if mean > 0.0 else 0.0,
            "share": between / var if var > 0.0 else 0.0,
            "wait": q.wait,
            "pk": q.lam * q.es2 / (2.0 * (1.0 - q.rho)) if q.rho < 1.0 else math.inf,
            "ttft": ttft.mean,
            "p99": ttft.p99,
            "lp": q.l_p,
            "avail": q.avail,
            "trunc": float(r.observe("trunc").count),
            "x": r.turns / window,
        }

    ones = [one(r) for r in _runs(c, SEEDS)]

    def est(k):
        return replications([o[k] for o in ones])

    return TraceRow(
        rate=c.rate,
        kv=c.kv,
        cap=c.cap,
        policy=EvictionPolicy.PricedMemoryBlocks,
        hit_rate=est("hit"),
        reused=est("reused"),
        sessions=est("live"),
        entry_wait=est("entry"),
        rho=est("rho"),
        cv2=est("cv2"),
        mixture_share=est("share"),
        wait=est("wait"),
        pk_wait=est("pk"),
        ttft=est("ttft"),
        ttft_p99=est("p99"),
        prefill_number=est("lp"),
        availability=est("avail"),
        truncated=est("trunc"),
        throughput=est("x"),
    )


def weka_cell(rate, kv, cap, delta, corpus, trace=None) -> Cell:
    return Cell(rate, kv, cap, delta, trace, corpus.resume_fraction(), corpus.mean_think())


def trace_row(rate: float, kv: float, cap: int) -> TraceRow:
    """One cell of §4.2's replay table on the WEKA corpus."""
    return trace_row_of(weka_cell(rate, kv, cap, 0.0, workload.weka()))


def trace_replay_scenario() -> list[TraceRow]:
    """Every cell of §4.2's replay table."""
    corpus = workload.weka()
    rows = [trace_row_of(weka_cell(r, math.inf, TRACE_CAP_OPEN, 0.0, corpus)) for r in TRACE_RATES]
    rate = TRACE_RATES[-1]
    for kv in (k for k in TRACE_POOLS if math.isfinite(k)):
        for f in TRACE_CAP_FACTORS:
            rows.append(trace_row_of(weka_cell(rate, kv, trace_cap(corpus, kv, f), 0.0, corpus)))
    return rows


@cache
def trace_price_row(rate: float, delta: float) -> TracePriceRow:
    """§4.2's forced-miss table: with no pool limit, a share `delta` of
    follow-up turns reuses nothing (a nonce at the head of the prompt; the
    old blocks stay). The bracket of Prop. price is computed from the
    baseline's measured `λ`, `E[S²]`, `ρ` in stage time and each forced
    turn's own `S^miss` (its work) and `S^hit` (the work had it reused its
    reusable prefix)."""
    corpus = workload.weka()
    window = TRACE_HORIZON - TRACE_WARMUP
    base = _runs(weka_cell(rate, math.inf, TRACE_CAP_OPEN, 0.0, corpus), PRICE_SEEDS)
    forced = _runs(weka_cell(rate, math.inf, TRACE_CAP_OPEN, delta, corpus), PRICE_SEEDS)
    dl = []
    lo_sum = rho_sum = live_sum = hit_sum = 0.0
    rho1_sum = live1_sum = lp_sum = fin_sum = 0.0
    for r0, r1 in zip(base, forced, strict=True):
        q0, q1 = queue(r0), queue(r1)
        f, work, whit = by_turn(r1, "forced"), by_turn(r1, "work"), by_turn(r1, "whit")
        phi_sum = ds_sum = 0.0
        for k, fm in f.items():
            if fm < 1.0 or k not in work or k not in whit:
                continue
            s_miss = work[k] / q0.avail
            s_hit = whit[k] / q0.avail
            phi_sum += miss_price(q0.lam, q0.es2, q0.rho, s_hit, s_miss)
            ds_sum += s_miss - s_hit
        live0 = r0.pool("live").mean_holders
        n_live = int(max(rround(live0), 1.0))
        es1 = q0.es + ds_sum / max(q0.n, 1)
        fin_sum += finite_source_price(n_live, corpus.mean_think(), q0.es, es1)
        dl.append(q1.l_p - q0.l_p)
        lo_sum += phi_sum / window
        rho_sum += q0.rho
        rho1_sum += q0.rho + ds_sum / window
        live_sum += live0
        live1_sum += r1.pool("live").mean_holders
        lp_sum += q0.l_p
        hit_sum += mean_obs(r1, "hit")
    k = float(PRICE_SEEDS)
    rho_m, rho1_m = rho_sum / k, rho1_sum / k
    hi = (1.0 - rho_m) / (1.0 - rho1_m) * lo_sum / k if rho1_m < 1.0 else math.inf
    return TracePriceRow(
        rate=rate,
        delta=delta,
        rho=rho_m,
        live=live_sum / k,
        rho1=rho1_m,
        live1=live1_sum / k,
        l_p=lp_sum / k,
        dl_p=replications(dl),
        lo=lo_sum / k,
        hi=hi,
        finite=fin_sum / k,
        hit_rate=hit_sum / k,
    )


def trace_split_scenario() -> list[tuple[str, TraceRow, float, float]]:
    """§4.2's split-rule sensitivity."""
    out = []
    for name, corpus, path in [
        ("10 min", workload.weka(), workload.WEKA),
        ("30 min", workload.weka_split_30min(), workload.WEKA_30MIN),
    ]:
        c = weka_cell(TRACE_RATES[0], math.inf, TRACE_CAP_OPEN, 0.0, corpus, trace=str(path))
        out.append((name, trace_row_of(c), corpus.mean_turns(), corpus.mean_think()))
    return out
