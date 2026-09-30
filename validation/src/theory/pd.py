"""The capacity of an integer prefill/decode split (Prop. pd)."""

from __future__ import annotations

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
