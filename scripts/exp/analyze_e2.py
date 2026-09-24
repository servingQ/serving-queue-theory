#!/usr/bin/env python3
"""E2 analysis: from a replay run (rounds.jsonl of replay_text_trace.py) and the
E1 fit, compute per run

  * live sessions over time (from sent/done timestamps and think gaps), mean N̄;
  * per-request hit/miss from cached_tokens (hit: cached ≥ 90 % of the prefix);
  * prefill work per request from the fitted cost model P(n, K) with
    n = prompt_tokens − cached_tokens, K = cached_tokens (a miss re-prefills
    the whole prompt);
  * arrival rate λ (requests/s in the measurement window), E[S], E[S²], ρ,
    the open PK wait λE[S²]/(2(1−ρ)), the observed mean queueing wait
    W_obs = TTFT − P(n, K), and the finite-source prediction of
    Proposition finite (M/M/1//N with N = N̄ rounded, Z = mean gap between a
    session's requests, mean work E[S]);
  * the split of Var[S] into the append and the hit/miss mixture.

Usage:
  python3 scripts/exp/analyze_e2.py --fit data/exp/e1/fit.json data/exp/e2/*/rounds.jsonl
where fit.json holds {"c0":..,"a":..,"b":..} from probe_prefill.py.
"""
import argparse
import json
import statistics as st


def mva_q(c, n):
    q = 0.0
    for k in range(n):
        q = (k + 1) * (1 + q) / (c + 1 + q)
    return q


def analyze(path, fit):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    ok = [r for r in rows if r.get("ttft_s") is not None and r.get("prompt_tokens")]
    if not ok:
        print(path, "no rows")
        return
    t0 = min(r["sent_monotonic_s"] for r in ok)
    t1 = max(r["done_monotonic_s"] for r in ok)
    window = t1 - t0
    # live sessions: a session is live from its first sent to its last done
    by_sess = {}
    for r in ok:
        s = by_sess.setdefault(r["session_index"], [1e18, -1e18, []])
        s[0] = min(s[0], r["sent_monotonic_s"])
        s[1] = max(s[1], r["done_monotonic_s"])
        s[2].append(r)
    live_time = sum(s[1] - s[0] for s in by_sess.values())
    n_bar = live_time / window
    # think gaps between a session's requests
    gaps = []
    for s in by_sess.values():
        rs = sorted(s[2], key=lambda r: r["sent_monotonic_s"])
        gaps += [b["sent_monotonic_s"] - a["done_monotonic_s"] for a, b in zip(rs, rs[1:])]
    z = st.fmean(gaps) if gaps else float("nan")
    c0, a, b = fit["c0"], fit["a"], fit["b"]
    S, hits, misses, waits, ttfts = [], [], [], [], []
    for r in ok:
        pt = r["prompt_tokens"]
        cached = r.get("cached_tokens") or 0
        n = max(pt - cached, 1)
        K = cached
        work = c0 + a * n + b * n * (K + n / 2)
        S.append(work)
        ttfts.append(r["ttft_s"])
        waits.append(max(r["ttft_s"] - work, 0.0))
        first = r.get("round_index", 0) == 0 or r is min(by_sess[r["session_index"]][2], key=lambda x: x["sent_monotonic_s"])
        if not first:
            (hits if cached >= 0.9 * (pt - n) and cached > 0 else misses).append(work)
    lam = len(ok) / window
    es = st.fmean(S)
    es2 = st.fmean(x * x for x in S)
    rho = lam * es
    pk = lam * es2 / (2 * (1 - rho)) if rho < 1 else float("inf")
    n_round = max(1, round(n_bar))
    q_prev = mva_q(z / es, n_round - 1) if z == z else float("nan")
    w_fin = q_prev * es
    # variance split among follow-up turns
    if hits and misses:
        p = len(hits) / (len(hits) + len(misses))
        mh, mm = st.fmean(hits), st.fmean(misses)
        vh = st.pvariance(hits) if len(hits) > 1 else 0.0
        vm = st.pvariance(misses) if len(misses) > 1 else 0.0
        between = p * (1 - p) * (mm - mh) ** 2
        within = p * vh + (1 - p) * vm
        share = between / (between + within) if between + within > 0 else float("nan")
    else:
        p, share = float("nan"), float("nan")
    print(f"{path}")
    print(f"  requests {len(ok)}  window {window:.0f}s  λ {lam:.3f}/s  N̄ {n_bar:.1f}  Z {z:.1f}s  hit rate (follow-ups) {p:.3f}")
    print(f"  E[S] {es:.3f}s  CV² {es2 / es**2 - 1:.2f}  ρ {rho:.2f}  mixture share of Var[S] {share:.2f}")
    print(f"  TTFT mean {st.fmean(ttfts):.3f}s p50 {st.median(ttfts):.3f}s p99 {sorted(ttfts)[int(0.99 * (len(ttfts) - 1))]:.3f}s")
    print(f"  W_obs (TTFT − P) mean {st.fmean(waits):.3f}s   PK open {pk:.3f}s   finite-source M/M/1//{n_round} {w_fin:.3f}s")
    return dict(path=path, requests=len(ok), window=window, lam=lam, n_bar=n_bar, z=z, hit=p, es=es, cv2=es2 / es**2 - 1,
                rho=rho, share=share, ttft=st.fmean(ttfts), w_obs=st.fmean(waits), pk=pk, w_fin=w_fin, n_round=n_round)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", required=True)
    ap.add_argument("--out")
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    fit = json.load(open(a.fit))
    res = [analyze(p, fit) for p in a.runs]
    if a.out:
        json.dump([r for r in res if r], open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
