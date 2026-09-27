#!/usr/bin/env python3
"""Analyse the decode-stretch probe (scripts/exp/probe_decode.py).

  A  decode step time on rank 0 against b and K: for each run, the window in
     which all b requests decode (after the last first token, before the first
     completion); the step time is the median inter-chunk gap of the requests
     inside the window (one token per request per step);
  B  rank 0's step time (4 x 16k) against rank 1's load b1;
  C  rank 0's token gaps while rank 1 prefills: tokens emitted during the peer's
     prefill interval, their mean gap, and the largest gap;
  D  rank 0's largest gap while rank 0 prefills another request (the pause);
  E  prefill time on rank 0 alone and with a peer prefilling, against E1.

  python3 scripts/exp/analyze_decode.py --fit data/exp/e1/fit.json --json data/exp/decode/summary.json \
      --fit-out data/exp/decode/fit.json data/exp/decode/probes.jsonl
"""
import argparse
import json
import statistics as st


def gaps_in(times, lo, hi):
    ts = [t for t in times if lo <= t <= hi]
    return [b - a for a, b in zip(ts, ts[1:])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", required=True)
    ap.add_argument("--json")
    ap.add_argument("--fit-out", help="write the lockstep step model here")
    ap.add_argument("--form", choices=["v1", "max", "v2"], default="v2",
                    help="v1: the pre-registered choice (probes A, B, E); v2: post hoc, adds probe F")
    ap.add_argument("probes")
    args = ap.parse_args()
    fit = json.load(open(args.fit))
    P = lambda n, K=0: fit["c0"] + fit["a"] * n + fit["b"] * n * (K + n / 2)
    rows = [json.loads(l) for l in open(args.probes) if l.strip()]
    runs = {}
    for r in rows:
        key = (r["exp"], json.dumps(r["cfg"], sort_keys=True))
        runs.setdefault(key, []).append(r)
    out = {"A": [], "B": [], "C": [], "D": [], "E": [], "F": [], "G": []}
    for (exp, cfg), rs in sorted(runs.items()):
        cfg = json.loads(cfg)
        if any(r.get("error") for r in rs):
            print("error in", exp, cfg)
            continue
        if exp in ("A", "B", "F"):
            r0 = [r for r in rs if r["rank"] == 0]
            lo = max(r["t_first"] for r in rs)
            hi = min(r["t_done"] for r in rs if len(r["times"]) > 1)
            g = [x for r in r0 for x in gaps_in(r["times"], lo, hi)]
            step = st.median(g) if g else float("nan")
            rec = dict(cfg=cfg, step=step, window=hi - lo, n=len(g), p90=sorted(g)[int(0.9 * (len(g) - 1))] if g else float("nan"))
            out[exp].append(rec)
        elif exp == "C":
            dec = [r for r in rs if r["rank"] == 0][0]
            pf = [r for r in rs if r["rank"] == 1][0]
            base = gaps_in(dec["times"], dec["t_first"] + 1.0, pf["t_send"])
            during = gaps_in(dec["times"], pf["t_send"], pf["t_first"])
            out["C"].append(dict(cfg=cfg, base_step=st.median(base) if base else float("nan"),
                                 prefill_s=pf["t_first"] - pf["t_send"], prefill_E1=P(cfg["n"]),
                                 tokens_during=len(during) + 1 if during else 0,
                                 gap_during=st.mean(during) if during else float("nan"),
                                 max_gap=max(during) if during else float("nan")))
        elif exp == "D":
            dec = sorted((r for r in rs if r["rank"] == 0), key=lambda r: r["t_send"])
            d, p = dec[0], dec[1]
            during = gaps_in(d["times"], p["t_send"] - 0.5, p["t_first"] + 0.5)
            out["D"].append(dict(cfg=cfg, prefill_s=p["t_first"] - p["t_send"], prefill_E1=P(cfg["n"]),
                                 max_gap=max(during) if during else float("nan"),
                                 base_step=st.median(gaps_in(d["times"], d["t_first"] + 1.0, p["t_send"]))))
        elif exp == "G":
            r0 = [r for r in rs if r["rank"] == 0][0]
            peers = [r for r in rs if r["rank"] != 0]
            overlap = min([r["t_first"] for r in peers], default=None)
            out["G"].append(dict(cfg=cfg, prefill_s=r0["t_first"] - r0["t_send"], prefill_E1=P(r0["K"]),
                                 peers_done_before=sum(1 for r in peers if r["t_first"] < r0["t_first"])))
        elif exp == "E":
            r0 = [r for r in rs if r["rank"] == 0][0]
            out["E"].append(dict(cfg=cfg, prefill_s=r0["t_first"] - r0["t_send"], prefill_E1=P(r0["K"])))
    print("A: decode step (s) on rank 0, others idle   [K, b: median gap, p90, window s]")
    for x in out["A"]:
        c = x["cfg"]
        print(f"  K={c['K']:6d} b={c['b']} rep={c['rep']}: {x['step']:.4f}  p90 {x['p90']:.4f}  window {x['window']:.1f}s  n {x['n']}")
    print("B: rank 0 (4 x 16k) step against rank 1 load b1")
    for x in out["B"]:
        print(f"  b1={x['cfg']['b1']} rep={x['cfg']['rep']}: {x['step']:.4f}  p90 {x['p90']:.4f}")
    print("F: all ranks decoding at once (rank-0 step)")
    for x in out["F"]:
        c = x["cfg"]
        print(f"  K={c['K']:6d} b={c['b']} ranks={c['ranks']} rep={c['rep']}: {x['step']:.4f}  p90 {x['p90']:.4f}")
    print("C: rank 0 decode while rank 1 prefills")
    for x in out["C"]:
        print(f"  n={x['cfg']['n']} rep={x['cfg']['rep']}: base step {x['base_step']:.4f}; peer prefill {x['prefill_s']:.2f}s (E1 {x['prefill_E1']:.2f}); "
              f"tokens during {x['tokens_during']}, mean gap {x['gap_during']:.3f}, max gap {x['max_gap']:.2f}")
    print("D: rank 0 decode while rank 0 prefills")
    for x in out["D"]:
        print(f"  n={x['cfg']['n']} rep={x['cfg']['rep']}: prefill {x['prefill_s']:.2f}s (E1 {x['prefill_E1']:.2f}); max decode gap {x['max_gap']:.2f}s; base step {x['base_step']:.4f}")
    print("G: prefill on rank 0 with k-1 peers prefilling")
    for x in out["G"]:
        c = x["cfg"]
        print(f"  n0={c['n0']:6d} n1={c['n1']:6d} k={c['k']} rep={c['rep']}: {x['prefill_s']:.3f}s (E1 {x['prefill_E1']:.3f}, ratio {x['prefill_s'] / x['prefill_E1']:.2f})")
    print("E: prefill on rank 0")
    for x in out["E"]:
        print(f"  peer={x['cfg']['peer']} rep={x['cfg']['rep']}: {x['prefill_s']:.2f}s (E1 {x['prefill_E1']:.2f}, ratio {x['prefill_s'] / x['prefill_E1']:.2f})")
    if args.json:
        json.dump(out, open(args.json, "w"), indent=1)
    if args.fit_out:
        out["c0"] = fit["c0"]
        f = {"v2": fit_step_model_v2, "max": fit_step_model_max, "v1": fit_step_model}[args.form](out)
        json.dump(f, open(args.fit_out, "w"), indent=1)
        print("step model:", f)


def lstsq(X, y):
    n = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) for j in range(n)] for i in range(n)]
    v = [sum(r[i] * t for r, t in zip(X, y)) for i in range(n)]
    for i in range(n):
        p = A[i][i]
        A[i] = [a / p for a in A[i]]; v[i] /= p
        for k in range(n):
            if k != i:
                f = A[k][i]
                A[k] = [a - f * b for a, b in zip(A[k], A[i])]; v[k] -= f * v[i]
    return v


def fit_step_model_v2(summary):
    """Post hoc (after v1 failed; see docs/memory-model.md), from probes A, B, F
    only: tau = alpha + beta * max_r bucket(b_r) + gamma * max_r sum_i K_i
    + delta * (active ranks - 1); leave-one-configuration-out CV MAPE 0.044,
    the best of six forms. All ranks pad to the largest bucket; attention is
    local to a rank, so the slowest rank's context sets the step."""
    bucket = lambda b: 0 if b == 0 else (1 if b == 1 else (4 if b <= 4 else 8))
    X, y = [], []
    for x in summary["A"]:
        c = x["cfg"]
        X.append([1.0, bucket(c["b"]), c["b"] * c["K"], 0.0]); y.append(x["step"])
    for x in summary["B"]:
        b1 = x["cfg"]["b1"]
        X.append([1.0, max(4, bucket(b1)), 4 * 16384, 1.0 if b1 else 0.0]); y.append(x["step"])
    for x in summary["F"]:
        c = x["cfg"]
        X.append([1.0, bucket(c["b"]), c["b"] * c["K"], c["ranks"] - 1.0]); y.append(x["step"])
    v = lstsq(X, y)
    solo = [e["prefill_s"] for e in summary["E"] if e["cfg"]["peer"] == 0]
    duo = [e["prefill_s"] for e in summary["E"] if e["cfg"]["peer"] == 1]
    f = {"form": "v2", "alpha": v[0], "beta_bucket": v[1], "gamma_ctx": v[2], "delta_rank": v[3],
         "prefill_stretch_2": st.mean(duo) / st.mean(solo), "chunk": 512,
         "source": "data/exp/decode/probes.jsonl (probes A, B, E, F; G for the stretch table)"}
    if summary.get("G"):                      # measured prefill stretch by the number of ranks prefilling
        c0 = summary.get("c0", 0.0)          # engine time only: remove the client/frontend intercept
        net = lambda x: (x["prefill_s"] - c0) / (x["prefill_E1"] - c0)
        f["prefill_stretch"] = [1.0] + [
            st.mean(net(x) for x in summary["G"] if x["cfg"]["k"] == k)
            / st.mean(net(x) for x in summary["G"] if x["cfg"]["k"] == 1) for k in (2, 3, 4)]
    return f


def fit_step_model_max(summary):
    """Post hoc (review round 4): the rule the pre-registration named, a maximum
    over ranks, fitted on the probes available at registration (A, B):
    tau = alpha + beta * max_r bucket(b_r) + gamma * max_r sum_i K_i."""
    bucket = lambda b: 0 if b == 0 else (1 if b == 1 else (4 if b <= 4 else 8))
    X, y = [], []
    for x in summary["A"]:
        c = x["cfg"]
        X.append([1.0, bucket(c["b"]), c["b"] * c["K"]]); y.append(x["step"])
    for x in summary["B"]:
        b1 = x["cfg"]["b1"]
        X.append([1.0, max(4, bucket(b1)), 4 * 16384]); y.append(x["step"])
    v = lstsq(X, y)
    solo = [e["prefill_s"] for e in summary["E"] if e["cfg"]["peer"] == 0]
    duo = [e["prefill_s"] for e in summary["E"] if e["cfg"]["peer"] == 1]
    return {"form": "max", "alpha": v[0], "beta_bucket": v[1], "gamma_ctx": v[2],
            "prefill_stretch_2": st.mean(duo) / st.mean(solo), "chunk": 512,
            "source": "data/exp/decode/probes.jsonl (probes A, B, E)"}


def fit_step_model(summary):
    """Least-squares decode step model from probes A and B (numpy-free):
    tau = alpha + beta * sum_r bucket(b_r) + gamma * sum_r sum_i K_i, chosen by
    leave-one-configuration-out cross-validation among seven forms (MAPE 0.041);
    plus the prefill stretch when two ranks prefill (probe E)."""
    bucket = lambda b: 0 if b == 0 else (1 if b == 1 else (4 if b <= 4 else 8))
    X, y = [], []
    for x in summary["A"]:
        c = x["cfg"]
        X.append([1.0, bucket(c["b"]), c["b"] * c["K"]]); y.append(x["step"])
    for x in summary["B"]:
        b1 = x["cfg"]["b1"]
        X.append([1.0, bucket(4) + bucket(b1), 4 * 16384 + b1 * 2048]); y.append(x["step"])
    # normal equations, 3x3
    n = 3
    A = [[sum(r[i] * r[j] for r in X) for j in range(n)] for i in range(n)]
    v = [sum(r[i] * t for r, t in zip(X, y)) for i in range(n)]
    for i in range(n):                       # Gauss-Jordan
        p = A[i][i]
        A[i] = [a / p for a in A[i]]; v[i] /= p
        for k in range(n):
            if k != i:
                f = A[k][i]
                A[k] = [a - f * b for a, b in zip(A[k], A[i])]; v[k] -= f * v[i]
    solo = [e["prefill_s"] for e in summary["E"] if e["cfg"]["peer"] == 0]
    duo = [e["prefill_s"] for e in summary["E"] if e["cfg"]["peer"] == 1]
    return {"alpha": v[0], "beta_bucket": v[1], "gamma_ctx": v[2],
            "prefill_stretch_2": st.mean(duo) / st.mean(solo),
            "chunk": 512, "source": "data/exp/decode/probes.jsonl (probes A, B, E)"}


if __name__ == "__main__":
    main()
