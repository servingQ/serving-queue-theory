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
                d = per.setdefault(eng, {"waiting": 0.0, "kv": 0.0, "running": 0.0, "running_max": 0.0, "kv_wait": 0.0, "n_wait": 0, "_w": 0.0, "_k": 0.0, "n_cap": 0})
                if name == "vllm:num_requests_waiting":
                    d["waiting"] += v
                    d["_w"] = v
                elif name == "vllm:kv_cache_usage_perc":
                    d["kv"] += v
                    d["_k"] = v
                elif name == "vllm:num_requests_running":
                    d["running"] += v
                    d["running_max"] = max(d["running_max"], v)
                    if v >= 8:
                        d["n_cap"] += 1
            # after the sample: occupancy in the samples where a request waited
            for d in per.values():
                if d["_w"] > 0:
                    d["kv_wait"] += d["_k"]
                    d["n_wait"] += 1
    if n == 0:
        return {}
    tot_w = sum(d["kv_wait"] for d in per.values())
    tot_n = sum(d["n_wait"] for d in per.values())
    out = {"pooled_kv_when_waiting": (tot_w / tot_n) if tot_n else float("nan"), "samples": n, "per_engine": {e: {"waiting_avg": d["waiting"] / n, "kv_usage_avg": d["kv"] / n, "running_avg": d["running"] / n,
                                             "running_max": d["running_max"], "cap_share": d["n_cap"] / n, "kv_when_waiting": (d["kv_wait"] / d["n_wait"]) if d["n_wait"] else float("nan"),
                                             "wait_share": d["n_wait"] / n} for e, d in per.items()}}
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


def analyze(path, fit, args):
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
    if args.warmup > 0:
        # Stationary window: from WARMUP after the first arrival to the last
        # arrival, by the time a request was sent (E2b); the default window
        # (first sent to last done) is the whole transient run (E2).
        firsts = [r["sent_monotonic_s"] for r in ok if r.get("round_index") == 0]
        t0, t1 = min(firsts) + args.warmup, max(firsts)
        ok = [r for r in ok if t0 <= r["sent_monotonic_s"] <= t1]
        if len(ok) < 50:
            print(path, "too few requests in the window (run incomplete?)")
            return
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
    # Time a session spends away from the prefill queue between two of its
    # turns: from the end of a turn's prefill (its first token) to the next
    # arrival, i.e. decode plus tool/think time. This is the Z of the
    # finite-source model (the source station is decode + think).
    def away_gaps(rs):
        rs = sorted(rs, key=lambda r: r["sent_monotonic_s"])
        return [b["sent_monotonic_s"] - (a.get("first_token_monotonic_s") or a["done_monotonic_s"]) for a, b in zip(rs, rs[1:])]

    def think_gaps(rs):
        rs = sorted(rs, key=lambda r: r["sent_monotonic_s"])
        return [b["sent_monotonic_s"] - a["done_monotonic_s"] for a, b in zip(rs, rs[1:])]

    gaps, thinks = [], []
    for s in by_sess.values():
        gaps += away_gaps(s[2])
        thinks += think_gaps(s[2])
    z = st.fmean(gaps) if gaps else float("nan")
    think = st.fmean(thinks) if thinks else float("nan")
    # door (admission) wait recorded by the replayer, session sojourn including it
    door = [r.get("admission_wait_s") or 0.0 for r in ok]
    door_mean = st.fmean(door)
    sojourn = []
    for sx, sv in by_sess.items():
        first = min(sv[2], key=lambda r: r["sent_monotonic_s"])
        sojourn.append(sv[1] - (first["sent_monotonic_s"] - (first.get("admission_wait_s") or 0.0)))
    sojourn_mean = st.fmean(sojourn)
    # previous round of each request (for the hit classification)
    prev_of = {}
    for sv in by_sess.values():
        rs = sorted(sv[2], key=lambda r: r["sent_monotonic_s"])
        for a_, b_ in zip(rs, rs[1:]):
            prev_of[id(b_)] = a_
    itls = [r["itl_mean_s"] for r in ok if r.get("itl_mean_s") and (r.get("completion_tokens") or 0) >= 32]
    itl_mean = st.fmean(itls) if itls else float("nan")
    itls_all = [r["itl_mean_s"] for r in ok if r.get("itl_mean_s") and (r.get("completion_tokens") or 0) >= 2]
    itl_all = st.fmean(itls_all) if itls_all else float("nan")
    c0, a, b = fit["c0"], fit["a"], fit["b"]
    S, hits, misses, waits, ttfts = [], [], [], [], []
    ttft_hit, ttft_miss, ttft_first, ttft_partial = [], [], [], []
    for r in ok:
        pt = r["prompt_tokens"]
        cached = r.get("cached_tokens") or 0
        n = max(pt - cached, 1)
        K = cached
        work = c0 + a * n + b * n * (K + n / 2)
        S.append(work)
        ttfts.append(r["ttft_s"])
        waits.append(max(r["ttft_s"] - work, 0.0))
        prev = prev_of.get(id(r))
        first = prev is None
        if not first:
            # A follow-up turn's resident prefix is the previous prompt plus the
            # previous completion; a hit is a cached length covering ≥ 90 % of
            # it (cached_tokens is rounded down to the sub-block).
            # cached_tokens is rounded down to the sub-block (512 tokens on
            # this stack), so a resident prefix of a few thousand tokens
            # reports less than 90 % of itself: a hit is a cached length of
            # at least 90 % of the prefix or of the prefix less one
            # sub-block, whichever is smaller (the same rule as before at
            # 50k contexts).
            prefix = (prev.get("prompt_tokens") or 0) + (prev.get("completion_tokens") or 0)
            is_hit = prefix > 0 and cached >= min(0.9 * prefix, prefix - args.subblock)
            (hits if is_hit else misses).append(work)
            if is_hit:
                ttft_hit.append(r["ttft_s"])
            elif cached > 0:
                ttft_partial.append(r["ttft_s"])  # part of the prefix evicted
            else:
                ttft_miss.append(r["ttft_s"])  # nothing resident: a full recompute
        else:
            ttft_first.append(r["ttft_s"])
        r["_cls"] = "first" if first else ("hit" if is_hit else ("partial" if cached > 0 else "miss"))
        r["_start"] = r["first_token_monotonic_s"] - work
        r["_think"] = None if first else r["sent_monotonic_s"] - prev["done_monotonic_s"]
    # Who waits: for each follow-up class, the share of turns that arrived while
    # another request of their rank was sent and not yet started (a queue), and
    # the mean think time before the turn; and the share of the run during which
    # some rank was prefilling (the ranks step in lockstep, so a prefill on any
    # rank stalls every rank's decode).
    queue_at, think_of = {}, {}
    for rk_ in {r.get("dp_rank_requested") for r in ok}:
        lst = sorted((r for r in ok if r.get("dp_rank_requested") == rk_), key=lambda r: r["sent_monotonic_s"])
        for j, r in enumerate(lst):
            if r["_cls"] == "first":
                continue
            qd = any(x["sent_monotonic_s"] < r["sent_monotonic_s"] < x["_start"] for x in lst[:j])
            queue_at.setdefault(r["_cls"], []).append(qd)
            think_of.setdefault(r["_cls"], []).append(r["_think"])
    iv = sorted((r["_start"], r["first_token_monotonic_s"]) for r in ok)
    busy, (cs, ce) = 0.0, iv[0]
    for s_, e_ in iv[1:]:
        if s_ > ce:
            busy += ce - cs
            cs, ce = s_, e_
        else:
            ce = max(ce, e_)
    busy += ce - cs
    t_end = max(r["done_monotonic_s"] for r in ok if r.get("done_monotonic_s"))
    any_prefill = busy / (t_end - iv[0][0])
    who_waits = {c: dict(queue=st.fmean(v), think=st.fmean(think_of[c])) for c, v in queue_at.items()}
    print(f"  arrived to a queue / think before: " + "  ".join(f"{c} {w['queue']:.2f} / {w['think']:.1f}s" for c, w in who_waits.items())
          + f"   some rank prefilling {any_prefill:.2f} of the run")
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
            gaps_r += away_gaps(by_sess[sx][2])
        z_r = st.fmean(gaps_r) if gaps_r else z
        n_r = max(1, round(live_r))
        w_fin_r = mva_q(z_r / es_r, n_r - 1) * es_r if z_r == z_r else float("nan")
        arr = sorted(ok[i]["sent_monotonic_s"] for i in idx)
        ia = [b_ - a_ for a_, b_ in zip(arr, arr[1:])]
        cv2_arr_r = st.pvariance(ia) / st.fmean(ia) ** 2 if len(ia) > 2 and st.fmean(ia) > 0 else float("nan")
        per_rank.append(dict(rank=rk, requests=len(idx), lam=lam_r, es=es_r, rho=rho_r, pk=pk_r, n_bar=live_r,
                             n_round=n_r, z=z_r, w_fin=w_fin_r, w_obs=st.fmean(waits[i] for i in idx), cv2_arr=cv2_arr_r))
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
            pr["running_max"] = mrk["running_max"]
            pr["cap_share"] = mrk["cap_share"]
            pr["kv_when_waiting"] = mrk["kv_when_waiting"]
            pr["wait_share"] = mrk["wait_share"]
    wsum = sum(pr["requests"] for pr in per_rank)
    rho = sum(pr["rho"] * pr["requests"] for pr in per_rank) / wsum
    pk = sum(pr["pk"] * pr["requests"] for pr in per_rank) / wsum
    w_fin = sum(pr["w_fin"] * pr["requests"] for pr in per_rank) / wsum
    n_round = sum(pr["n_round"] * pr["requests"] for pr in per_rank) / wsum
    rho_lo, rho_hi = min(pr["rho"] for pr in per_rank), max(pr["rho"] for pr in per_rank)
    cv2_arr = sum(pr["cv2_arr"] * pr["requests"] for pr in per_rank if pr["cv2_arr"] == pr["cv2_arr"]) / wsum
    w_admit = (sum(pr.get("w_admit", 0.0) * pr["requests"] for pr in per_rank) / wsum) if metrics else float("nan")
    kv_usage = (sum(pr.get("kv_usage_avg", 0.0) * pr["requests"] for pr in per_rank) / wsum) if metrics else float("nan")
    q_srv = (sum(pr.get("queue_time_mean", 0.0) * pr["requests"] for pr in per_rank) / wsum) if metrics else float("nan")
    pf_srv = (sum(pr.get("prefill_time_mean", 0.0) * pr["requests"] for pr in per_rank) / wsum) if metrics else float("nan")
    preempt = sum(pr.get("preemptions", 0.0) for pr in per_rank) if metrics else float("nan")
    token_hit = (sum(pr.get("prefix_hit_ratio", 0.0) * pr["requests"] for pr in per_rank) / wsum) if metrics else float("nan")
    running_max = max((pr.get("running_max", 0.0) for pr in per_rank), default=float("nan")) if metrics else float("nan")
    cap_share = max((pr.get("cap_share", 0.0) for pr in per_rank), default=float("nan")) if metrics else float("nan")
    # pooled over ranks: mean occupancy of the (rank, sample) pairs with a request waiting
    kvp = metrics.get("pooled_kv_when_waiting", float("nan")) if metrics else float("nan")
    kv_when_waiting = (kvp, kvp)
    pf_over_es = pf_srv / es if es > 0 else float("nan")
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
    print(f"  requests {len(ok)}  window {window:.0f}s  λ {lam:.3f}/s  N̄ {n_bar:.1f}  Z (decode+think) {z:.1f}s  think {think:.1f}s  full-hit rate (follow-ups) {p:.3f}")
    print(f"  door wait mean {door_mean:.1f}s  session sojourn incl. door {sojourn_mean:.0f}s  ITL mean {itl_mean:.3f}s")
    print(f"  E[S] {es:.3f}s  CV² {es2 / es**2 - 1:.2f}  mixture share of Var[S] {share:.2f}")
    mh = st.fmean(ttft_hit) if ttft_hit else float("nan")
    mm = st.fmean(ttft_miss) if ttft_miss else float("nan")
    mf = st.fmean(ttft_first) if ttft_first else float("nan")
    mp = st.fmean(ttft_partial) if ttft_partial else float("nan")
    print(f"  TTFT by class: first turns {mf:.1f}s ({len(ttft_first)})  follow-up hits {mh:.1f}s ({len(ttft_hit)})  partial {mp:.1f}s ({len(ttft_partial)})  follow-up misses {mm:.1f}s ({len(ttft_miss)})")
    print(f"  TTFT mean {st.fmean(ttfts):.3f}s p50 {st.median(ttfts):.3f}s p99 {sorted(ttfts)[int(0.99 * (len(ttfts) - 1))]:.3f}s")
    print(f"  per-rank ρ {rho_lo:.2f}–{rho_hi:.2f} (request-weighted mean {rho:.2f}); ranks {len(per_rank)}")
    print(f"  server view: mean admission wait (Little, per rank) {w_admit:.1f}s   KV usage {100 * kv_usage:.0f}%   "
          f"queue time {q_srv:.1f}s   prefill time {pf_srv:.1f}s (= {pf_over_es:.2f} E[S])   preemptions {preempt:.0f}   token hit ratio {token_hit:.2f}")
    print(f"  running max per rank {running_max:.0f}   KV usage while a request waited (pooled) {100 * kv_when_waiting[0]:.0f}%")
    print(f"  W_obs (TTFT − P) mean {st.fmean(waits):.3f}s   PK open (per rank, mean) {pk:.3f}s   finite-source M/M/1//N per rank (N̄≈{n_round:.1f}) {w_fin:.3f}s")
    return dict(path=path, params=params, n_err=n_err, requests=len(ok), window=window, lam=lam, n_bar=n_bar, z=z, hit=p, es=es, cv2=es2 / es**2 - 1,
                rho=rho, share=share, ttft=st.fmean(ttfts), ttft_p50=st.median(ttfts),
                ttft_p99=sorted(ttfts)[int(0.99 * (len(ttfts) - 1))], w_obs=st.fmean(waits), pk=pk, w_fin=w_fin, n_round=n_round,
                rho_lo=rho_lo, rho_hi=rho_hi, cv2_arr=cv2_arr, per_rank=per_rank, w_admit=w_admit, kv_usage=kv_usage, q_srv=q_srv, pf_srv=pf_srv, preempt=preempt, token_hit=token_hit,
                hits=len(hits), misses=len(misses), ttft_hit=mh, ttft_miss=mm, ttft_first=mf, n_first=len(ttft_first),
                ttft_partial=mp, n_partial=len(ttft_partial), n_miss=len(ttft_miss),
                think=think, door=door_mean, sojourn=sojourn_mean, itl=itl_mean, itl_all=itl_all, running_max=running_max, cap_share=cap_share,
                kv_when_waiting=kv_when_waiting[0], pf_over_es=pf_over_es, who_waits=who_waits, any_prefill=any_prefill)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", required=True)
    ap.add_argument("--out")
    ap.add_argument("--subblock", type=int, default=512, help="prefix-cache granularity in tokens")
    ap.add_argument("--warmup", type=float, default=0.0, help="seconds after the first arrival at which the window starts (0: whole run)")
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    fit = json.load(open(a.fit))
    res = [analyze(p, fit, a) for p in a.runs]
    if a.out:
        json.dump([r for r in res if r], open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
