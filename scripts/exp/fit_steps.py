#!/usr/bin/env python3
"""Fit the step-cost expression of .serq/src/examples/replay/vllm_replay.sq to the
A100 step sweeps (data/exp/gpu_seq/steps.jsonl, scripts/exp/lambda/serq_cases.py).

Two forms, both in serQ's step quantities (ntok, npre, ndec, kvb = KV held by
the scheduled decoders, attn = sum over prefill chunks n (K + n/2)):
  sum: t = c + d ndec + e kvb + a npre + b attn
  max: t = c + max(w + e kvb + d ndec, a ntok + b attn)
Prints the coefficients (seconds) and the MAPE by step kind; writes fit.json."""
import json
import sys

import numpy as np

rows = [json.loads(l) for l in open(sys.argv[1] if len(sys.argv) > 1 else "data/exp/gpu_seq/steps.jsonl")]
rows = [r for r in rows if r["batch"][0] > 0 and r["step"] > 2]
t = np.array([r["t_ms"] / 1000 for r in rows])
ndec = np.array([r["ndec"] for r in rows], float)
kvb = np.array([r["kvb"] for r in rows], float)
npre = np.array([r["npre"] for r in rows], float)
attn = np.array([sum(n * (k + n / 2) for n, k in r["pre"]) for r in rows], float)
ntok = npre + ndec
kind = np.array(["decode" if r["npre"] == 0 else ("prefill" if r["ndec"] == 0 else "mixed") for r in rows])

X = np.stack([np.ones_like(t), ndec, kvb, npre, attn], 1)
w = 1 / t  # relative error
coef, *_ = np.linalg.lstsq(X * w[:, None], t * w, rcond=None)
pred = X @ coef


def mape(p):
    return {k: float(np.mean(np.abs(p[kind == k] - t[kind == k]) / t[kind == k])) for k in ["decode", "prefill", "mixed"]}


out = {"sum": dict(zip(["c", "d", "e", "a", "b"], map(float, coef))), "sum_mape": mape(pred), "n": len(rows)}
print(json.dumps(out, indent=1))
json.dump(out, open("data/exp/gpu_seq/fit.json", "w"), indent=1)
