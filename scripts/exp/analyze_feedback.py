#!/usr/bin/env python3
"""Miss feedback in the short-context price test (research/analytic-memory.md).

For each pair (baseline arm, forced-miss arm) of the short-context replay:

  * classes of the follow-ups (hit / partial / unforced miss / forced) with the
    rule of analyze_e2.py, the realised forced share delta, the hit rates h0
    (baseline) and h_delta (forced arm);
  * the implied feedback slope, a secant of the feedback map over [h_delta, h0]:
      k = (1 - 1/R) / (1 - delta),  R = (h0 - h_delta) / (delta h0),
    from the affine map of Proposition 4 (direct loss delta h0, total loss
    h0 - h_delta), with a Poisson band on the induced misses;
  * where the misses are: miss share of non-forced follow-ups after a think gap
    of 29 s or more (the trace caps gaps at 30 s) and after shorter gaps;
  * the two candidate channels:
      wait channel  — mean TTFT of the arm (the part of the absence that grows);
      pool channel  — new (non-cached) tokens per second per rank, and for each
                      long-gap follow-up the tokens inserted on its rank during
                      its absence (previous done -> its send) and during its
                      own wait (send -> first token);
  * a threshold (LRU characteristic-time) test of the pool channel: pick the
    capacity C so that the baseline's long-gap miss share equals the share of
    long-gap turns whose absence saw more than C inserted tokens, then predict
    the forced arm's long-gap miss share from its own insertions with the same
    C (fitted on the baseline only).

  python3 scripts/exp/analyze_feedback.py [--json data/exp/e2b/feedback.json]
"""
import argparse
import collections
import json
import math
import statistics as st

R = "data/exp/"
PAIRS = [("s25_base", "s25_m10", "short_m10.jsonl"), ("s25_base_s1", "s25_m10_s1", "short_m10_s1.jsonl"),
         ("s35_base", "s35_m10", "short_m10.jsonl")]


def forced_set(trace):
    s = set()
    for line in open(R + "traces/" + trace):
        d = json.loads(line)
        for k, q in enumerate(d["requests"]):
            if q.get("forced_miss"):
                s.add((d["id"], k))
    return s


def load(tag):
    return [r for r in (json.loads(l) for l in open(R + "e2b/" + tag + "/rounds.jsonl") if l.strip()) if not r.get("error")]


def follow_ups(rows, fs):
    by = collections.defaultdict(list)
    for r in rows:
        by[r["session_id"]].append(r)
    out = []
    for sid, v in by.items():
        v.sort(key=lambda r: r["round_index"])
        for p, r in zip(v, v[1:]):
            c = r.get("cached_tokens") or 0
            pre = (p.get("prompt_tokens") or 0) + (p.get("completion_tokens") or 0)
            if (sid, r["round_index"]) in fs:
                cl = "forced"
            elif c == 0:
                cl = "unforced"
            elif c >= min(0.9 * pre, pre - 512):
                cl = "hit"
            else:
                cl = "partial"
            out.append((cl, p, r))
    return out


def insertions(rows):
    ev = collections.defaultdict(list)
    for r in rows:
        if r.get("first_token_monotonic_s"):
            ev[r["dp_rank_requested"]].append((r["first_token_monotonic_s"],
                                               (r.get("prompt_tokens") or 0) - (r.get("cached_tokens") or 0)))
    for v in ev.values():
        v.sort()
    return ev


def inserted(ev, rank, t0, t1):
    return sum(n for t, n in ev[rank] if t0 < t <= t1)


def arm_stats(tag, fs):
    rows = load(tag)
    fu = follow_ups(rows, fs)
    cnt = collections.Counter(c for c, _, _ in fu)
    ev = insertions(rows)
    t0 = min(r["sent_monotonic_s"] for r in rows)
    t1 = max(r.get("done_monotonic_s") or 0 for r in rows)
    new = sum((r.get("prompt_tokens") or 0) - (r.get("cached_tokens") or 0) + (r.get("completion_tokens") or 0)
              for r in rows)
    tt = [r["ttft_s"] for r in rows if r.get("ttft_s")]
    long_gap, short_gap = [], []
    absence = []                      # (class, tokens inserted during absence, during own wait)
    for c, p, r in fu:
        if c == "forced":
            continue
        gap = r["sent_monotonic_s"] - p["done_monotonic_s"]
        (long_gap if gap >= 29.0 else short_gap).append(c)
        if gap >= 29.0 and r.get("first_token_monotonic_s") and c in ("hit", "unforced"):
            rk = r["dp_rank_requested"]
            absence.append((c, inserted(ev, rk, p["done_monotonic_s"], r["sent_monotonic_s"]),
                            inserted(ev, rk, r["sent_monotonic_s"], r["first_token_monotonic_s"] - 1e-9)))
    return dict(tag=tag, counts=dict(cnt), n=sum(cnt.values()), ttft=st.mean(tt),
                new_per_rank=new / (t1 - t0) / 4,
                long_n=len(long_gap), long_miss=sum(c == "unforced" for c in long_gap) / max(1, len(long_gap)),
                short_n=len(short_gap), short_miss=sum(c == "unforced" for c in short_gap) / max(1, len(short_gap)),
                absence=absence)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    out = []
    C_ref = {}
    for b, f, tr in PAIRS:
        fs = forced_set(tr)
        A, B = arm_stats(b, set()), arm_stats(f, fs)
        F = B["counts"].get("forced", 0)
        delta = F / B["n"]
        h0 = A["counts"].get("hit", 0) / A["n"]
        hd = B["counts"].get("hit", 0) / B["n"]
        scale = (B["n"] - F) / A["n"]
        uf, ub = B["counts"].get("unforced", 0), A["counts"].get("unforced", 0)
        induced = uf - ub * scale
        # Poisson variance of the induced count, both arms: var = uf + scale^2 ub; with no
        # misses in either arm the 95 % upper limit of a Poisson count of 0 (3.0) is used
        sd = math.sqrt(uf + scale ** 2 * ub)
        half95 = 1.96 * sd if (uf + ub) > 0 else 3.0

        def k_of(loss):
            Rr = loss / (delta * h0) if delta * h0 > 0 else float("nan")
            return (1 - 1 / Rr) / (1 - delta) if Rr and Rr > 0 else float("nan")
        k = k_of(h0 - hd)
        band = half95 / B["n"]                                # as a change of the hit rate
        rec = dict(pair=(b, f), delta=delta, h0=h0, h_delta=hd, induced=induced, k_secant=k,
                   k_lo=max(0.0, k_of(h0 - hd - band)) if (uf + ub) > 0 else 0.0, k_hi=k_of(h0 - hd + band),
                   base=A, forced=B)
        # threshold test of the pool channel: C from the baseline's long-gap miss share
        ab = sorted(x[1] for x in A["absence"])
        if ab and A["long_miss"] > 0:
            q = 1 - A["long_miss"]
            C = ab[min(len(ab) - 1, int(q * len(ab)))]
            af = [x[1] for x in B["absence"]]
            rec["pool_C_tokens"] = C
            rec["pool_pred_long_miss"] = sum(x > C for x in af) / len(af) if af else float("nan")
            # in sample: how many of the baseline's long-gap misses had more than C inserted?
            rec["pool_base_misses_above_C"] = (sum(1 for x in A["absence"] if x[0] == "unforced" and x[1] > C),
                                               sum(1 for x in A["absence"] if x[0] == "unforced"))
            C_ref[b] = C
        elif C_ref:                                         # a load with no misses: apply the seed-0 2.5 s threshold
            rec["pool_C_from_other_load"] = C_ref.get("s25_base", next(iter(C_ref.values())))
        if "pool_C_from_other_load" in rec:
            C = rec["pool_C_from_other_load"]
            rec["pool_above_C_other_load"] = {arm["tag"]: (sum(1 for x in arm["absence"] if x[1] > C),
                                                           sum(1 for x in arm["absence"] if x[1] > C and x[0] == "unforced"))
                                              for arm in (A, B)}
            print(f"  2.5 s threshold C = {C:.0f} applied here: absences above C (misses among them) "
                  + "  ".join(f"{t}: {n} ({m})" for t, (n, m) in rec["pool_above_C_other_load"].items()))
        for arm in (A, B):
            ab_ = arm["absence"]
            arm["absence_summary"] = {c: dict(n=sum(1 for x in ab_ if x[0] == c),
                                              think_median=st.median([x[1] for x in ab_ if x[0] == c]) if any(x[0] == c for x in ab_) else float("nan"),
                                              wait_mean=st.mean([x[2] for x in ab_ if x[0] == c]) if any(x[0] == c for x in ab_) else float("nan"))
                                      for c in ("hit", "unforced")}
            del arm["absence"]
        out.append(rec)
        print(f"{b} -> {f}: delta {delta:.3f}  h0 {h0:.4f}  h_delta {hd:.4f}  induced {induced:.0f}  "
              f"k (secant) {k:.3f} [{rec['k_lo']:.3f}, {rec['k_hi']:.3f}]")
        for arm in (A, B):
            s = arm["absence_summary"]
            print(f"  {arm['tag']:12s} mean TTFT {arm['ttft']:.2f}s  new tokens/s/rank {arm['new_per_rank']:.0f}  "
                  f"long-gap miss {arm['long_miss']:.3f} (n {arm['long_n']})  short-gap miss {arm['short_miss']:.4f} (n {arm['short_n']})  "
                  f"tokens inserted during absence (median) hit {s['hit']['think_median']:.0f} / miss {s['unforced']['think_median']:.0f}; "
                  f"during own wait (mean) hit {s['hit']['wait_mean']:.0f} / miss {s['unforced']['wait_mean']:.0f}")
        if "pool_C_tokens" in rec:
            ia, na = rec["pool_base_misses_above_C"]
            print(f"  pool threshold C = {rec['pool_C_tokens']:.0f} tokens (baseline); in sample {ia} of {na} baseline long-gap "
                  f"misses are above C; forced arm long-gap miss predicted {rec['pool_pred_long_miss']:.3f}, observed {B['long_miss']:.3f}")

    if args.json:
        json.dump(out, open(args.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
