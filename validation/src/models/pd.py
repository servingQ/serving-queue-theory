"""Aggregated vs prefill/decode-disaggregated serving (Prop. pd).

Aggregated: one pool of `N` devices; a request holds one device for
`prefill + decode + I`. Disaggregated: a tandem `prefill pool (N_P) → KV
link → decode pool (N_D)`, with specialisation gains dividing each phase's
work. `Saturated` load measures capacity (serQ's `pd_tandem.sq`), `Poisson`
load measures latency (`pd_open.sq`). Memory caps are not simulated.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

import serq
from dist import Deterministic, Dist, exp
from fmt import fmax, fmin
from stats import Estimate, Welford, batch_means

MIN_POSITIVE = 2.2250738585072014e-308


@dataclass(frozen=True)
class Aggregated:
    pass


@dataclass(frozen=True)
class Disaggregated:
    prefill_devices: int


Mode = Aggregated | Disaggregated


@dataclass(frozen=True)
class Saturated:
    """`jobs` requests always in the system: measures capacity."""

    jobs: int


@dataclass(frozen=True)
class Poisson:
    """Poisson arrivals at `rate` per second: measures latency."""

    rate: float


Load = Saturated | Poisson


@dataclass
class PdConfig:
    devices: int
    mode: Mode
    load: Load
    prefill: Dist  # mean s_P
    decode: Dist  # mean s_D
    interference: float  # I
    gain_prefill: float
    gain_decode: float
    kv_tokens: Dist  # mean E[K]
    b_net: float  # tokens/s; inf disables the link
    requests: int
    warmup: int
    seed: int

    @classmethod
    def from_means(cls, devices, mode, load, s_p, s_d, interference, gains, b_net, e_k):
        """Exponential work with means `s_P`, `s_D`."""
        return cls(
            devices, mode, load, exp(s_p), exp(s_d), interference, gains[0], gains[1],
            Deterministic(e_k), b_net, 200_000, 20_000, 1,
        )  # fmt: skip

    def copy(self, **kw) -> PdConfig:
        return replace(self, **kw)


@dataclass
class PdReport:
    throughput: float
    latencies: np.ndarray
    latency: Estimate
    station_utilization: list[float]
    latency_stats: Welford


def _source(name: str, cfg: PdConfig) -> str:
    src = serq.program_path(name).read_text()
    for pattern, repl in [
        ("~exp(sP)", cfg.prefill.sample_expr()),
        ("~exp(sD)", cfg.decode.sample_expr()),
        ("~exp(K)", cfg.kv_tokens.sample_expr()),
    ]:
        assert pattern in src, f"{name}.sq lacks {pattern}"
        src = src.replace(pattern, repl, 1)
    return src


def _measured(r: serq.Report, cfg: PdConfig, horizon: float):
    o = r.observe("latency")
    samples, times = o.samples, o.times
    start = min(cfg.warmup, len(samples))
    end = min(start + cfg.requests, len(samples))
    assert end > start, "the PD program produced no measured requests"
    lat = samples[start:end]
    t = times[start:end]
    span = float(t[-1] - t[0]) if len(t) > 1 else horizon
    return lat, span


def simulate(cfg: PdConfig) -> PdReport:
    if isinstance(cfg.load, Saturated):
        return _saturated(cfg, cfg.load.jobs)
    return _poisson(cfg)


def _saturated(cfg: PdConfig, jobs: int) -> PdReport:
    # pd_tandem.sq declares all three stations even on the aggregate path;
    # keep both split pools positive.
    split = isinstance(cfg.mode, Disaggregated)
    npf = cfg.mode.prefill_devices if split else 1
    mean_sp = cfg.prefill.mean() / cfg.gain_prefill
    mean_sd = cfg.decode.mean() / cfg.gain_decode
    if split:
        capacity = fmin(
            fmin(npf / mean_sp, (cfg.devices - npf) / mean_sd), cfg.b_net / cfg.kv_tokens.mean()
        )
    else:
        capacity = cfg.devices / (cfg.prefill.mean() + cfg.decode.mean() + cfg.interference)
    measured = float(max(cfg.requests, 1))
    horizon = 1.2 * (cfg.warmup + measured) / fmax(capacity, MIN_POSITIVE) + 1.0
    sets = {
        "N": float(cfg.devices),
        "NP": float(npf),
        "sP": cfg.prefill.mean(),
        "sD": cfg.decode.mean(),
        "I": cfg.interference,
        "gP": cfg.gain_prefill,
        "gD": cfg.gain_decode,
        "bnet": cfg.b_net,
        "K": cfg.kv_tokens.mean(),
        "jobs": float(jobs),
        "mode": 1.0 if split else 0.0,
    }
    r = serq.run(
        source=_source("pd_tandem", cfg), sets=sets, seed=cfg.seed, warmup=0.0, horizon=horizon
    )
    lat, span = _measured(r, cfg, horizon)
    if split:
        util = [
            (r.stage(n).utilization if r.stage(n) else 0.0) for n in ("prefill", "link", "decode")
        ]
    else:
        util = [r.stage("agg").utilization if r.stage("agg") else 0.0]
    return PdReport(
        len(lat) / fmax(span, MIN_POSITIVE), lat, batch_means(lat, 20), util, Welford(lat)
    )


def _poisson(cfg: PdConfig) -> PdReport:
    rate = cfg.load.rate
    if isinstance(cfg.mode, Disaggregated):
        npf, split = cfg.mode.prefill_devices, True
        assert 0 < npf < cfg.devices
    else:
        npf, split = 1, False
    horizon = 1.5 * max(cfg.warmup + cfg.requests, 1) / rate + 100.0
    sets = {
        "N": float(cfg.devices),
        "NP": float(npf),
        "Lambda": rate,
        "sP": cfg.prefill.mean(),
        "sD": cfg.decode.mean(),
        "I": cfg.interference,
        "gP": cfg.gain_prefill,
        "gD": cfg.gain_decode,
        "bnet": cfg.b_net,
        "K": cfg.kv_tokens.mean(),
        "mode": 1.0 if split else 0.0,
    }
    r = serq.run(
        source=_source("pd_open", cfg), sets=sets, seed=cfg.seed, warmup=0.0, horizon=horizon
    )
    lat, span = _measured(r, cfg, horizon)

    def u(name, servers):
        s = r.stage(name)
        return 0.0 if s is None else fmin(s.throughput * s.mean_service / servers, 1.0)

    if split:
        util = [u("prefill", npf), u("link", 1), u("decode", cfg.devices - npf)]
    else:
        util = [u("agg", cfg.devices)]
    return PdReport(
        len(lat) / fmax(span, MIN_POSITIVE), lat, batch_means(lat, 20), util, Welford(lat)
    )


def split_capacity(cfg: PdConfig, prefill_devices: int) -> float:
    """`min(N_P g_P / s_P, N_D g_D / s_D, B_net / E[K])` of an integer split."""
    n_p = float(prefill_devices)
    n_d = float(cfg.devices - prefill_devices)
    return fmin(
        fmin(
            n_p * cfg.gain_prefill / cfg.prefill.mean(), n_d * cfg.gain_decode / cfg.decode.mean()
        ),
        cfg.b_net / cfg.kv_tokens.mean(),
    )
