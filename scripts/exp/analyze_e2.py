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
import os
import statistics as st


def mva_q(c, n):
    q = 0.0
    for k in range(n):
        q = (k + 1) * (1 + q) / (c + 1 + q)
    return q


def metrics_summary(path, t0, t1, ok):
    """Time-average per-engine gauges over the measurement window. The
    replayer stamps samples with wall time; rounds use time.monotonic, so the
    window is mapped through the offset of the first round."""
    if not os.path.exists(path):
        return {}
    samples = [json.loads(l) for l in open(path) if l.strip()]
    if not samples:
        return {}
    # map monotonic window to wall time using the replayer's meta if present
    meta_path = os.path.join(os.path.dirname(path), "meta.json")
    off = None
    if os.path.exists(meta_path):
        off = json.load(open(meta_path)).get("epoch_minus_monotonic")
    if off is None:
        return {}
    lo, hi = t0 + off, t1 + off
    per = {}
    n = 0
    first, last = {}, {}  # counters at the window's first and last sample, per engine
    counters = ("vllm:request_queue_time_seconds_sum", "vllm:request_queue_time_seconds_count",
                "vllm:request_prefill_time_seconds_sum", "vllm:request_prefill_time_seconds_count",
                "vllm:num_preemptions_total", "vllm:prefix_cache_hits_total", "vllm:prefix_cache_queries_total",
                "vllm:time_to_first_token_seconds_sum", "vllm:time_to_first_token_seconds_count")
    for smp in samples:
        if not (lo <= smp["t"] <= hi):
            continue
        n += 1
        for url, m in smp.items():
            if url == "t":
                continue
            for k, v in m.items():
                name = k.split("{", 1)[0]
                if name in counters and 'engine="' in k:
                    eng = k.split('engine="', 1)[1].split('"', 1)[0]
                    first.setdefault((eng, name), v)
                    last[(eng, name)] = v
        for url, m in smp.items():
            if url == "t":
                continue
            for k, v in m.items():
                if "{" not in k:
                    continue
                name, rest = k.split("{", 1)
                eng = rest.split('engine="', 1)[1].split('"', 1)[0] if 'engine="' in rest else "0"
                d = per.setdefault(eng, {"waiting": 0.0, "kv": 0.0, "running": 0.0})
                if name == "vllm:num_requests_waiting":
                    d["waiting"] += v
                elif name == "vllm:kv_cache_usage_perc":
                    d["kv"] += v
                elif name == "vllm:num_requests_running":
                    d["running"] += v
    if n == 0:
        return {}
    out = {"samples": n, "per_engine": {e: {"waiting_avg": d["waiting"] / n, "kv_usage_avg": d["kv"] / n, "running_avg": d["running"] / n} for e, d in per.items()}}
    for e, d in out["per_engine"].items():
        def delta(name):
            return last.get((e, name), 0.0) - first.get((e, name), 0.0)
        qc, pc = delta("vllm:request_queue_time_seconds_count"), delta("vllm:request_prefill_time_seconds_count")
        d["queue_time_mean"] = delta("vllm:request_queue_time_seconds_sum") / qc if qc > 0 else float("nan")
        d["prefill_time_mean"] = delta("vllm:request_prefill_time_seconds_sum") / pc if pc > 0 else float("nan")
        d["preemptions"] = delta("vllm:num_preemptions_total")
        q = delta("vllm:prefix_cache_queries_total")
        d["prefix_hit_ratio"] = delta("vllm:prefix_cache_hits_total") / q if q > 0 else float("nan")
        d["requests"] = qc
    return out


def analyze(path, fit):
    rows = []
    for l in open(path):
        if not l.strip():
            continue
        try:
            rows.append(json.loads(l))
        except json.JSONDecodeError:
            pass  # a truncated last line (the writer was killed mid-record)
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
    ttft_hit, ttft_miss, ttft_first = [], [], []
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
            is_hit = cached >= 0.9 * (pt - n) and cached > 0
            (hits if is_hit else misses).append(work)
            (ttft_hit if is_hit else ttft_miss).append(r["ttft_s"])
        else:
            ttft_first.append(r["ttft_s"])
    # Each DP rank has its own prefill queue and KV pool: compute λ, ρ, the PK
    # wait and the finite-source wait per rank, then average over ranks
    # weighted by requests. Sessions are pinned to a rank by the replayer.
    lam = len(ok) / window
    es = st.fmean(S)
    es2 = st.fmean(x * x for x in S)
    per_rank = []
    ranks = sorted({r.get("dp_rank_requested") for r in ok}, key=lambda x: (x is None, x))
    for rk in ranks:
        idx = [i for i, r in enumerate(ok) if r.get("dp_rank_requested") == rk]
        Sr = [S[i] for i in idx]
        lam_r = len(idx) / window
        es_r = st.fmean(Sr)
        es2_r = st.fmean(x * x for x in Sr)
        rho_r = lam_r * es_r
        pk_r = lam_r * es2_r / (2 * (1 - rho_r)) if rho_r < 1 else float("inf")
        sess_r = {ok[i]["session_index"] for i in idx}
        live_r = sum(by_sess[sx][1] - by_sess[sx][0] for sx in sess_r) / window
        gaps_r = []
        for sx in sess_r:
            rs = sorted(by_sess[sx][2], key=lambda r: r["sent_monotonic_s"])
            gaps_r += [b["sent_monotonic_s"] - a["done_monotonic_s"] for a, b in zip(rs, rs[1:])]
        z_r = st.fmean(gaps_r) if gaps_r else z
        n_r = max(1, round(live_r))
        w_fin_r = mva_q(z_r / es_r, n_r - 1) * es_r if z_r == z_r else float("nan")
        per_rank.append(dict(rank=rk, requests=len(idx), lam=lam_r, es=es_r, rho=rho_r, pk=pk_r, n_bar=live_r,
                             n_round=n_r, z=z_r, w_fin=w_fin_r, w_obs=st.fmean(waits[i] for i in idx)))
    # Server-side view from the /metrics samples beside rounds.jsonl: the
    # time-average number of requests waiting per engine (Little's law then
    # gives the mean admission wait per request), KV usage and preemptions.
    metrics = metrics_summary(os.path.join(os.path.dirname(path), "metrics.jsonl"), t0, t1, ok)
    for pr in per_rank:
        mrk = metrics.get("per_engine", {}).get(str(pr["rank"]))
        if mrk:
            pr["waiting_avg"] = mrk["waiting_avg"]
            pr["w_admit"] = mrk["waiting_avg"] / pr["lam"] if pr["lam"] > 0 else float("nan")
            pr["kv_usage_avg"] = mrk["kv_usage_avg"]
            pr["queue_time_mean"] = mrk["queue_time_mean"]
            pr["prefill_time_mean"] = mrk["prefill_time_mean"]
            pr["preemptions"] = mrk["preemptions"]
            pr["prefix_hit_ratio"] = mrk["prefix_hit_ratio"]
    wsum = sum(pr["requests"] for pr in per_rank)
    rho = sum(pr["rho"] * pr["requests"] for pr in per_rank) / wsum
    pk = sum(pr["pk"] * pr["requests"] for pr in per_rank) / wsum
    w_fin = sum(pr["w_fin"] * pr["requests"] for pr in per_rank) / wsum
    n_round = sum(pr["n_round"] * pr["requests"] for pr in per_rank) / wsum
    rho_lo, rho_hi = min(pr["rho"] for pr in per_rank), max(pr["rho"] for pr in per_rank)
    w_admit = (sum(pr.get("w_admit", 0.0) * pr["requests"] for pr in per_rank) / wsum) if metrics else float("nan")
    kv_usage = (sum(pr.get("kv_usage_avg", 0.0) * pr["requests"] for pr in per_rank) / wsum) if metrics else float("nan")
    q_srv = (sum(pr.get("queue_time_mean", 0.0) * pr["requests"] for pr in per_rank) / wsum) if metrics else float("nan")
    pf_srv = (sum(pr.get("prefill_time_mean", 0.0) * pr["requests"] for pr in per_rank) / wsum) if metrics else float("nan")
    preempt = sum(pr.get("preemptions", 0.0) for pr in per_rank) if metrics else float("nan")
    token_hit = (sum(pr.get("prefix_hit_ratio", 0.0) * pr["requests"] for pr in per_rank) / wsum) if metrics else float("nan")
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
    params = {}
    ppath = os.path.join(os.path.dirname(path), "params.json")
    if os.path.exists(ppath):
        params = json.load(open(ppath))
    n_err = len(rows) - len(ok)
    print(f"{path}  {params}")
    print(f"  requests {len(ok)}  window {window:.0f}s  λ {lam:.3f}/s  N̄ {n_bar:.1f}  Z {z:.1f}s  hit rate (follow-ups) {p:.3f}")
    print(f"  E[S] {es:.3f}s  CV² {es2 / es**2 - 1:.2f}  mixture share of Var[S] {share:.2f}")
    mh = st.fmean(ttft_hit) if ttft_hit else float("nan")
    mm = st.fmean(ttft_miss) if ttft_miss else float("nan")
    mf = st.fmean(ttft_first) if ttft_first else float("nan")
    print(f"  TTFT by class: first turns {mf:.1f}s ({len(ttft_first)})  follow-up hits {mh:.1f}s ({len(ttft_hit)})  follow-up misses {mm:.1f}s ({len(ttft_miss)})")
    print(f"  TTFT mean {st.fmean(ttfts):.3f}s p50 {st.median(ttfts):.3f}s p99 {sorted(ttfts)[int(0.99 * (len(ttfts) - 1))]:.3f}s")
    print(f"  per-rank ρ {rho_lo:.2f}–{rho_hi:.2f} (request-weighted mean {rho:.2f}); ranks {len(per_rank)}")
    print(f"  server view: mean admission wait (Little, per rank) {w_admit:.1f}s   KV usage {100 * kv_usage:.0f}%   "
          f"queue time {q_srv:.1f}s   prefill time {pf_srv:.1f}s   preemptions {preempt:.0f}   token hit ratio {token_hit:.2f}")
    print(f"  W_obs (TTFT − P) mean {st.fmean(waits):.3f}s   PK open (per rank, mean) {pk:.3f}s   finite-source M/M/1//N per rank (N̄≈{n_round:.1f}) {w_fin:.3f}s")
    return dict(path=path, params=params, n_err=n_err, requests=len(ok), window=window, lam=lam, n_bar=n_bar, z=z, hit=p, es=es, cv2=es2 / es**2 - 1,
                rho=rho, share=share, ttft=st.fmean(ttfts), ttft_p50=st.median(ttfts),
                ttft_p99=sorted(ttfts)[int(0.99 * (len(ttfts) - 1))], w_obs=st.fmean(waits), pk=pk, w_fin=w_fin, n_round=n_round,
                rho_lo=rho_lo, rho_hi=rho_hi, per_rank=per_rank, w_admit=w_admit, kv_usage=kv_usage, q_srv=q_srv, pf_srv=pf_srv, preempt=preempt, token_hit=token_hit,
                hits=len(hits), misses=len(misses), ttft_hit=mh, ttft_miss=mm, ttft_first=mf, n_first=len(ttft_first))


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
