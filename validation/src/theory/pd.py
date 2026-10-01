"""The capacity of an integer prefill/decode split (Prop. pd), and the
decode load of the processor-sharing idealisation the colocated-vs-split
comparison is measured against (`DecodeScaling.lean`, issue #28)."""

from __future__ import annotations

import math

from fmt import fmin


def split_capacity(
    devices: int,
    prefill_devices: int,
    s_p: float,
    s_d: float,
    g_p: float,
    g_d: float,
    b_net: float,
    e_k: float,
) -> float:
    """`min(N_P g_P / s_P, N_D g_D / s_D, B_net / E[K])` of an integer split."""
    n_p = float(prefill_devices)
    n_d = float(devices - prefill_devices)
    return fmin(fmin(n_p * g_p / s_p, n_d * g_d / s_d), b_net / e_k)


def floor_exp_mean(mean: float) -> float:
    """`E[floor(X)]` for `X` exponential with the given mean:
    `sum_{k >= 1} P(X >= k) = 1 / (e^{1/mean} - 1)`."""
    return 1.0 / math.expm1(1.0 / mean)


def ps_decode_load(rate: float, mean_gaps: float, tok: float, capacity: float) -> float:
    """The load of a PS decode station: `rate * E[o - 1] * tok / capacity`,
    with `tok` the time of one decode token at a whole engine. `pd_ps.sq`'s
    colocated station has arrivals `rate / N` and capacity `f`, the pooled
    one arrivals `rate` and capacity `N f`: the same load (`psWeight_scale`)."""
    return rate * mean_gaps * tok / capacity
