#!/usr/bin/env python3
"""E2b price test: the rise of the prefill stage under forced misses against
the bracket of Proposition price (and the finite-source price of Proposition
finite), from a baseline replay and a forced-miss replay of the same
short-context trace (scripts/exp/make_short_trace.py) at the same spacing.

Per DP rank (each rank is its own prefill queue; sessions are pinned):
  baseline   λ, E[S], E[S²] from the E1 cost model at the observed cached
             length, ρ = λE[S], the open PK wait W, the observed wait
             (TTFT − S), the server's queue time, L_P = λ E[TTFT] (Little:
             number in the prefill stage), interarrival CV²;
  forced     the same, and for every forced turn i (flagged in the trace)
             S_i^hit = P(n_i, K_i) with the intended append n_i onto the
             previous prompt K_i, S_i^miss = P(K_i + n_i, 0), and
             Φ_i = ΔS_i + λ((S^miss)² − (S^hit)²)/(2(1−ρ)) + λWΔS_i/(1−ρ)
             with the baseline's λ, ρ, W;
  bracket    lo = Σ_i Φ_i / window (= λ Σ q_i Φ_i), ρ' = ρ + Σ_i ΔS_i / window,
             hi = (1−ρ)/(1−ρ') lo; observed ΔL_P = L_P' − L_P; the
             finite-source price Q_N(E[S] + added work per turn) − Q_N(E[S])
             with N = round(N̄) and Z = decode + think; cap = N̄' − L_P.
Ranks are summed for the totals (the bracket is additive over queues).

The measurement window is [first arrival + WARMUP, last arrival] in both
arms, by the time a request was sent, so the ramp-up and the drain are
left out.

Usage:
  python3 scripts/exp/analyze_price.py --fit data/exp/e1/fit.json \
      --base data/exp/e2b/s15_base/rounds.jsonl --forced data/exp/e2b/s15_m10/rounds.jsonl \
      --trace data/exp/traces/short_m10.jsonl --out data/exp/e2b/price_s15.json
"""
import argparse
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(__file__))
from analyze_e2 import metrics_summary, mva_q  # noqa: E402

WARMUP = 90.0


def load_rounds(path):
    rows = []
    for l in open(path):
        if not l.strip():
            continue
        try:
            rows.append(json.loads(l))
        except json.JSONDecodeError:
            pass
    return [r for r in rows if r.get("ttft_s") is not None and r.get("prompt_tokens") and not r.get("error")]


def work(fit, n, K):
    return fit["c0"] + fit["a"] * n + fit["b"] * n * (K + n / 2)


def per_rank(rows, fit, spacing, metrics_path=None):
    """Window statistics per rank, plus session bookkeeping."""
    t_first = min(r["sent_monotonic_s"] for r in rows if r["round_index"] == 0)
    t_last_arrival = max(r["sent_monotonic_s"] for r in rows if r["round_index"] == 0)
    w0, w1 = t_first + WARMUP, t_last_arrival
    window = w1 - w0
    by_sess = {}
    for r in rows:
        by_sess.setdefault(r["session_index"], []).append(r)
    for v in by_sess.values():
        v.sort(key=lambda r: r["sent_monotonic_s"])
    inwin = [r for r in rows if w0 <= r["sent_monotonic_s"] <= w1]
    metrics = metrics_summary(metrics_path, w0, w1, inwin) if metrics_path else {}
    out = {}
    for rk in sorted({r["dp_rank_requested"] for r in rows}):
        rs = [r for r in inwin if r["dp_rank_requested"] == rk]
        if not rs:
            continue
        S = [work(fit, max(r["prompt_tokens"] - (r.get("cached_tokens") or 0), 1), r.get("cached_tokens") or 0) for r in rs]
        lam = len(rs) / window
        es = st.fmean(S)
        es2 = st.fmean(x * x for x in S)
        rho = lam * es
        pk = lam * es2 / (2 * (1 - rho)) if rho < 1 else float("inf")
        ttft = [r["ttft_s"] for r in rs]
        wobs = st.fmean(max(t - s, 0.0) for t, s in zip(ttft, S))
        # live sessions of this rank in the window, and Z = decode + think
        sess = {r["session_index"] for r in rs}
        live = 0.0
        gaps = []
        for sx in sess:
            v = by_sess[sx]
            a, b = v[0]["sent_monotonic_s"], v[-1]["done_monotonic_s"]
            live += max(0.0, min(b, w1) - max(a, w0))
            gaps += [q["sent_monotonic_s"] - (p.get("first_token_monotonic_s") or p["done_monotonic_s"]) for p, q in zip(v, v[1:])]
        n_bar = live / window
        z = st.fmean(gaps) if gaps else float("nan")
        arr = sorted(r["sent_monotonic_s"] for r in rs)
        ia = [b - a for a, b in zip(arr, arr[1:])]
        cv2_arr = (st.pvariance(ia) / st.fmean(ia) ** 2) if len(ia) > 2 and st.fmean(ia) > 0 else float("nan")
        mrk = metrics.get("per_engine", {}).get(str(rk), {}) if metrics else {}
        out[rk] = dict(
            rank=rk, requests=len(rs), lam=lam, es=es, es2=es2, cv2=es2 / es**2 - 1, rho=rho, pk=pk,
            ttft=st.fmean(ttft), ttft_p99=sorted(ttft)[int(0.99 * (len(ttft) - 1))], w_obs=wobs,
            l_p=lam * st.fmean(ttft), n_bar=n_bar, z=z, cv2_arr=cv2_arr,
            w_srv=mrk.get("queue_time_mean", float("nan")), pf_srv=mrk.get("prefill_time_mean", float("nan")),
            running_max=mrk.get("running_max", float("nan")), kv=mrk.get("kv_usage_avg", float("nan")),
            rows=rs,
        )
    return out, window, (w0, w1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--forced", required=True)
    ap.add_argument("--trace", required=True, help="the forced-miss trace (forced_miss flags, intended n and K)")
    ap.add_argument("--out")
    a = ap.parse_args()
    fit = json.load(open(a.fit))
    params = json.load(open(os.path.join(os.path.dirname(a.base), "params.json")))
    spacing = float(params.get("spacing_s", 0))
    base_rows = load_rounds(a.base)
    forced_rows = load_rounds(a.forced)
    # forced turns: by session id and round index, from the trace
    forced_turns = {}
    for l in open(a.trace):
        s = json.loads(l)
        for k, q in enumerate(s["requests"]):
            if q.get("forced_miss"):
                prev = s["requests"][k - 1]["in"]
                forced_turns[(s["id"], k)] = (q["in"] - prev, prev)  # intended append n, previous prompt K
    B, window, win = per_rank(base_rows, fit, spacing, os.path.join(os.path.dirname(a.base), "metrics.jsonl"))
    F, window_f, win_f = per_rank(forced_rows, fit, spacing, os.path.join(os.path.dirname(a.forced), "metrics.jsonl"))
    ranks = sorted(set(B) & set(F))
    per = []
    SUB = 512

    def classify(rows):
        """Follow-up classes of an arm: forced (in the trace), unforced miss
        (nothing resident), partial, hit; returns per turn (class, n, K)."""
        by = {}
        for r in rows:
            by.setdefault(r["session_id"], []).append(r)
        out = {}
        for sid, v in by.items():
            v.sort(key=lambda r: r["round_index"])
            for pr_, r in zip(v, v[1:]):
                cached = r.get("cached_tokens") or 0
                prefix = (pr_.get("prompt_tokens") or 0) + (pr_.get("completion_tokens") or 0)
                key = (sid, r["round_index"])
                if key in forced_turns:
                    cls = "forced"
                elif cached == 0:
                    cls = "unforced"
                elif cached >= min(0.9 * prefix, prefix - SUB):
                    cls = "hit"
                else:
                    cls = "partial"
                out[id(r)] = (cls, r["prompt_tokens"] - prefix, prefix)
        return out

    cls_b, cls_f = classify(base_rows), classify(forced_rows)

    def price(b, n_i, K_i):
        s_hit = work(fit, max(n_i, 1), K_i)
        s_miss = work(fit, K_i + max(n_i, 1), 0)
        ds = s_miss - s_hit
        own = ds
        hol = b["lam"] * (s_miss**2 - s_hit**2) / (2 * (1 - b["rho"]))
        load = b["lam"] * b["pk"] * ds / (1 - b["rho"])
        load_srv = b["lam"] * (b["w_srv"] if b["w_srv"] == b["w_srv"] else b["pk"]) * ds / (1 - b["rho"])
        return ds, own, hol, load, load_srv

    for rk in ranks:
        b, f = B[rk], F[rk]
        acc = {}  # class -> [count, ds_sum, own, hol, load, load_srv]
        for arm, rows, cls in (("f", f["rows"], cls_f), ("b", b["rows"], cls_b)):
            for r in rows:
                c = cls.get(id(r))
                if c is None:
                    continue
                k = (arm, c[0])
                a_ = acc.setdefault(k, [0, 0.0, 0.0, 0.0, 0.0, 0.0])
                a_[0] += 1
                if c[0] in ("forced", "unforced"):
                    n_i, K_i = c[1], c[2]
                    if c[0] == "forced":
                        n_i, K_i = forced_turns[(r["session_id"], r["round_index"])]
                    ds, own, hol, load, load_srv = price(b, n_i, K_i)
                    a_[1] += ds
                    a_[2] += own
                    a_[3] += hol
                    a_[4] += load
                    a_[5] += load_srv
        fo = acc.get(("f", "forced"), [0] * 6)
        uf = acc.get(("f", "unforced"), [0] * 6)
        ub = acc.get(("b", "unforced"), [0] * 6)
        # forced turns only (what the change asked for)
        lo_forced = (fo[2] + fo[3] + fo[4]) / window_f
        # every miss the change caused: forced plus the unforced misses net of the baseline's own
        net = [fo[i] + uf[i] - ub[i] for i in range(1, 6)]
        lo = sum(net[1:4]) / window_f
        lo_srv = (net[1] + net[2] + net[4]) / window_f
        own, hol, load = net[1] / window_f, net[2] / window_f, net[3] / window_f
        rho1 = b["rho"] + net[0] / window_f
        hi = (1 - b["rho"]) / (1 - rho1) * lo if rho1 < 1 else float("inf")
        dl = f["l_p"] - b["l_p"]
        # who pays: the rise of L_P borne by turns that did not miss (hits, partials, first turns)
        def l_by(rows, cls, want):
            sel = [r["ttft_s"] for r in rows if (cls.get(id(r), ("first",))[0] in want)]
            return len(sel) / window_f * st.fmean(sel) if sel else 0.0
        bystander = l_by(f["rows"], cls_f, ("hit", "partial", "first")) - l_by(b["rows"], cls_b, ("hit", "partial", "first"))
        n_live = max(1, round(b["n_bar"]))
        es1 = b["es"] + net[0] / max(1, f["requests"])
        fin = (mva_q(b["z"] / es1, n_live) - mva_q(b["z"] / b["es"], n_live)) if b["z"] == b["z"] else float("nan")
        per.append(dict(rank=rk, n_forced=fo[0], n_unforced_f=uf[0], n_unforced_b=ub[0], lo=lo, lo_forced=lo_forced, lo_srv=lo_srv, hi=hi,
                        own=own, hol=hol, load=load, rho=b["rho"], rho1=rho1, l_p=b["l_p"], l_p1=f["l_p"], dl_p=dl, bystander=bystander,
                        fin=fin, cap=f["n_bar"] - b["l_p"],
                        base={k: v for k, v in b.items() if k != "rows"}, forced={k: v for k, v in f.items() if k != "rows"}))
    tot = dict(
        lo=sum(p["lo"] for p in per), lo_forced=sum(p["lo_forced"] for p in per), lo_srv=sum(p["lo_srv"] for p in per),
        hi=sum(p["hi"] for p in per), dl_p=sum(p["dl_p"] for p in per),
        own=sum(p["own"] for p in per), hol=sum(p["hol"] for p in per), load=sum(p["load"] for p in per),
        bystander=sum(p["bystander"] for p in per),
        l_p=sum(p["l_p"] for p in per), fin=sum(p["fin"] for p in per), cap=sum(p["cap"] for p in per),
        n_forced=sum(p["n_forced"] for p in per), n_unforced_f=sum(p["n_unforced_f"] for p in per), n_unforced_b=sum(p["n_unforced_b"] for p in per),
    )
    res = dict(spacing_s=spacing, window_s=window, base=os.path.dirname(a.base), forced=os.path.dirname(a.forced),
               per_rank=per, total=tot)
    print(f"spacing {spacing} s, window {window:.0f} s, forced turns {tot['n_forced']}, unforced misses base {tot['n_unforced_b']} -> forced arm {tot['n_unforced_f']}")
    for p in per:
        b = p["base"]
        print(f"  rank {p['rank']}: λ {b['lam']:.2f}/s ρ {b['rho']:.2f}→{p['rho1']:.2f}  W_obs {b['w_obs']:.2f} W_srv {b['w_srv']:.2f} PK {b['pk']:.2f}  CV²arr {b['cv2_arr']:.2f}  "
              f"L_P {p['l_p']:.2f}→{p['l_p1']:.2f} ΔL_P {p['dl_p']:.2f}  bracket [{p['lo']:.2f}, {p['hi']:.2f}] (forced only lo {p['lo_forced']:.2f}; W=srv lo {p['lo_srv']:.2f})  "
              f"own/HOL/load {p['own']:.2f}/{p['hol']:.2f}/{p['load']:.2f}  bystanders {p['bystander']:.2f}  fin {p['fin']:.2f} cap {p['cap']:.2f}")
    print(f"  total: ΔL_P {tot['dl_p']:.2f}  bracket [{tot['lo']:.2f}, {tot['hi']:.2f}] (forced only lo {tot['lo_forced']:.2f})  own/HOL/load {tot['own']:.2f}/{tot['hol']:.2f}/{tot['load']:.2f}  bystanders {tot['bystander']:.2f}  fin {tot['fin']:.2f}  cap {tot['cap']:.2f}")
    if a.out:
        json.dump(res, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
