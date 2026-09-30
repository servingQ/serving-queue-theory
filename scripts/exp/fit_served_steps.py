#!/usr/bin/env python3
"""Fit serQ's step-cost expression to a *served* vLLM engine, from the step
trace written by scripts/exp/lambda/steptrace/sitecustomize.py
(data/exp/gpu_seq/trace/<run>.steps.<pid>: one JSON line per scheduler step
with t_sched, t_done and per request [tokens, computed before, prompt, held]).

The period of step i is t_sched(i+1) - t_sched(i) while the engine stays
busy (gaps above `--idle` seconds are idle time and dropped). Under
asynchronous scheduling the period, not t_done - t_sched, is what a request
waits per step. Fitted form (the one of vllm_replay.sq):
    period = c + d ndec + e kvb + a npre + b attn
Writes the coefficients and the MAPE by step kind as JSON."""
import glob
import json
import sys

import numpy as np


def load(pattern):
    steps = []
    for f in sorted(glob.glob(pattern)):
        steps += [json.loads(l) for l in open(f) if l.strip()]
    steps.sort(key=lambda r: r["t_sched"])
    return steps


def features(r):
    ndec = npre = kvb = 0
    attn = 0.0
    for n, k0, prompt, held in r["reqs"]:
        if k0 < prompt:
            npre += n
            attn += n * (k0 + n / 2)
        else:
            ndec += 1
            kvb += held
    return ndec, kvb, npre, attn


def main():
    pattern = sys.argv[1]
    idle = float(sys.argv[2]) if len(sys.argv) > 2 else 0.2
    steps = load(pattern)
    X, y, kind = [], [], []
    for a, b in zip(steps, steps[1:]):
        p = b["t_sched"] - a["t_sched"]
        if p <= 0 or p > idle:
            continue
        ndec, kvb, npre, attn = features(a)
        X.append([1.0, ndec, kvb, npre, attn])
        y.append(p)
        kind.append("decode" if npre == 0 else ("prefill" if ndec == 0 else "mixed"))
    X, y, kind = np.array(X), np.array(y), np.array(kind)
    w = 1 / y
    coef, *_ = np.linalg.lstsq(X * w[:, None], y * w, rcond=None)
    pred = X @ coef
    mape = {k: float(np.mean(np.abs(pred[kind == k] - y[kind == k]) / y[kind == k])) for k in ["decode", "prefill", "mixed"] if (kind == k).any()}
    out = {"n": int(len(y)), "coef": dict(zip(["c", "d", "e", "a", "b"], map(float, coef))), "mape": mape,
           "median_period_ms": {k: float(1000 * np.median(y[kind == k])) for k in ["decode", "prefill", "mixed"] if (kind == k).any()}}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
