#!/usr/bin/env python3
"""E1 on one replica group: fit the prefill cost model P(n, K) = a n + b n (K + n/2)
from time-to-first-token of single requests sent to an idle server.

Two kinds of probe, each sent alone (the previous one has finished):
  cold   : a fresh random prompt of n tokens (no cached prefix)   -> P(n, 0)
  append : a prefix of K tokens is sent once to warm the cache, then the same
           prefix plus n new tokens                               -> P(n, K)
Every request streams and records TTFT; `cached_tokens` from the usage block
(server started with --enable-prompt-tokens-details) confirms the hit.

Writes one JSON line per probe to --out (kind, n, K, ttft_s, cached_tokens,
prompt_tokens) and prints the least-squares fit of (a, b) and its residuals.

  python3 scripts/exp/probe_prefill.py --base-url http://127.0.0.1:8010/v1 \
      --model MiniMaxAI/MiniMax-M2.7 --out data/exp/e1/probes.jsonl
"""
import argparse
import json
import os
import random
import time
import urllib.request


DP_RANK = None  # X-data-parallel-rank header; without it vLLM's balancer may send the
# warm and the append request to different ranks and the prefix is never a hit.


def stream_ttft(base, model, prompt_ids, max_tokens=1, timeout=1800):
    body = json.dumps({
        "model": model,
        "prompt": prompt_ids,
        "max_tokens": max_tokens,
        "stream": True,
        "ignore_eos": True,
        "temperature": 0.0,
        "stream_options": {"include_usage": True},
    }).encode()
    req = urllib.request.Request(base + "/completions", data=body,
                                 headers={"Content-Type": "application/json", **({"X-data-parallel-rank": str(DP_RANK)} if DP_RANK is not None else {})})
    t0 = time.perf_counter()
    ttft = None
    usage = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            obj = json.loads(payload)
            if ttft is None and obj.get("choices") and obj["choices"][0].get("text", "") != "":
                ttft = time.perf_counter() - t0
            if ttft is None and obj.get("choices") and obj["choices"][0].get("finish_reason"):
                ttft = time.perf_counter() - t0
            if obj.get("usage"):
                usage = obj["usage"]
    done = time.perf_counter() - t0
    cached = None
    if usage and usage.get("prompt_tokens_details"):
        cached = usage["prompt_tokens_details"].get("cached_tokens")
    return ttft if ttft is not None else done, done, usage.get("prompt_tokens") if usage else None, cached


def rand_ids(rng, n, lo=1000, hi=150000):
    return [rng.randrange(lo, hi) for _ in range(n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8010/v1")
    ap.add_argument("--model", default="MiniMaxAI/MiniMax-M2.7")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cold", default="1024,4096,16384,32768,65536,98304")
    ap.add_argument("--prefixes", default="16384,49152,90112")
    ap.add_argument("--appends", default="512,2048,8192")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dp-rank", type=int, default=None, help="pin every probe to this DP rank")
    a = ap.parse_args()
    global DP_RANK
    DP_RANK = a.dp_rank
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    rng = random.Random(a.seed)
    rows = []
    out = open(a.out, "a")

    def record(**kw):
        kw["t_unix"] = time.time()
        rows.append(kw)
        out.write(json.dumps(kw) + "\n")
        out.flush()
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in kw.items() if k != "t_unix"})

    # warm-up request (compile paths), not recorded
    stream_ttft(a.base_url, a.model, rand_ids(rng, 512))
    for n in [int(x) for x in a.cold.split(",") if x]:
        for r in range(a.repeats):
            ids = rand_ids(rng, n)
            ttft, done, pt, cached = stream_ttft(a.base_url, a.model, ids)
            record(kind="cold", n=n, K=0, rep=r, ttft_s=ttft, total_s=done, prompt_tokens=pt, cached_tokens=cached)
    for K in [int(x) for x in a.prefixes.split(",") if x]:
        for n in [int(x) for x in a.appends.split(",")]:
            for r in range(a.repeats):
                prefix = rand_ids(rng, K)
                ttft0, _, pt0, cached0 = stream_ttft(a.base_url, a.model, prefix)
                record(kind="warm", n=K, K=0, rep=r, ttft_s=ttft0, total_s=0.0, prompt_tokens=pt0, cached_tokens=cached0)
                ttft, done, pt, cached = stream_ttft(a.base_url, a.model, prefix + rand_ids(rng, n))
                record(kind="append", n=n, K=K, rep=r, ttft_s=ttft, total_s=done, prompt_tokens=pt, cached_tokens=cached)
    fit(rows)


def fit(rows):
    """Least squares for P(n,K) = c0 + a n + b n (K + n/2) on cold and append
    probes whose cached_tokens confirm the prefix (or all, if not reported)."""
    import statistics as st
    pts = []
    for r in rows:
        if r["kind"] == "cold":
            pts.append((r["n"], 0.0, r["ttft_s"]))
        elif r["kind"] == "append":
            K = r["K"]
            c = r.get("cached_tokens")
            if c is not None and c < 0.5 * K:
                continue  # the prefix was not (fully) cached; skip
            pts.append((r["n"], float(K), r["ttft_s"]))
    if len(pts) < 4:
        print("too few probes to fit")
        return
    # normal equations for [c0, a, b]
    X = [[1.0, n, n * (K + n / 2)] for n, K, _ in pts]
    y = [t for _, _, t in pts]
    import itertools
    def matmul_T(X, y):
        return [sum(X[i][j] * y[i] for i in range(len(X))) for j in range(3)]
    XtX = [[sum(X[i][j] * X[i][k] for i in range(len(X))) for k in range(3)] for j in range(3)]
    Xty = matmul_T(X, y)
    # solve 3x3 by Gaussian elimination
    M = [XtX[j] + [Xty[j]] for j in range(3)]
    for c in range(3):
        p = max(range(c, 3), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        for r in range(3):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [M[r][k] - f * M[c][k] for k in range(4)]
    c0, a, b = [M[j][3] / M[j][j] for j in range(3)]
    pred = [c0 + a * n + b * n * (K + n / 2) for n, K, _ in pts]
    mape = st.fmean(abs(p - t) / t for p, (_, _, t) in zip(pred, pts))
    print(f"fit: c0={c0:.4f} s, a={a:.3e} s/token, b={b:.3e} s/token^2, K_c=a/b={a / b if b else float('inf'):.0f} tokens, MAPE {100 * mape:.1f}% over {len(pts)} probes")


if __name__ == "__main__":
    main()
