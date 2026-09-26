#!/usr/bin/env python3
"""E2b: derive the short-context replay trace (the PK regime) from the 50k
coding-agent trace that E2 replays.

Why. On the testbed a rank's KV pool holds 52 blocks of 4096 tokens, two to
four 50k contexts, so in E2 the pool binds before the prefill queue does and
the open regime of the PK formula is never reached. With contexts of a few
thousand tokens a rank holds 15 to 25 sessions and the prefill queue can be
loaded to rho = 0.5 to 0.7 with the decode batch cap (8 per rank) still
slack. Decode dominates a real turn (mean 1.1k output tokens at 60 ms per
token), so the output is capped too; the appends keep the real trace's
spread, scaled down.

Construction, per source session and copy:
  * a 4-token session nonce heads every prompt of the session, so no two
    sessions (or copies) share a prefix and every first turn is cold;
  * turn 1 is the first INIT tokens of the source's first prompt;
  * turn k appends the first n'_k tokens of what the source turn k added
    beyond its common prefix with turn k-1, with n'_k = the source append
    scaled so that the mean append is APPEND_MEAN (clipped to
    [APPEND_MIN, APPEND_MAX]); so turn k-1's prompt is a prefix of turn
    k's and a resident prefix is a full hit;
  * out = min(out, OUT_CAP); think_time is the source's (already capped at
    30 s in the source file);
  * with --miss-share d, each follow-up turn is chosen with probability d
    (seeded) as a forced miss: a fresh 2-token nonce is put at the head of
    that turn's prompt and of every later prompt of the session, so the
    turn recomputes its whole context once and the session hits again from
    then on; the request carries "forced_miss": true;
  * session ids are salted so that the replayer's crc32 pinning spreads
    sessions round-robin over the DP ranks.

Usage:
  python3 scripts/exp/make_short_trace.py --out data/exp/traces/short_base.jsonl
  python3 scripts/exp/make_short_trace.py --miss-share 0.10 --out data/exp/traces/short_m10.jsonl
"""
import argparse
import json
import random
import statistics as st
import zlib

SRC = "/mnt/shared_data/groups/fsw_serv/fsw-415/cc_traj_50k_think30s.jsonl"


def common_prefix(a, b):
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def salt_id(base, rank, dp):
    k = 0
    while True:
        cand = f"{base}~{k}"
        if zlib.crc32(cand.encode()) % dp == rank:
            return cand
        k += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", required=True)
    ap.add_argument("--copies", type=int, default=9)
    ap.add_argument("--init", type=int, default=2000, help="tokens of the first prompt")
    ap.add_argument("--append-mean", type=int, default=1000)
    ap.add_argument("--append-min", type=int, default=32)
    ap.add_argument("--append-max", type=int, default=4000)
    ap.add_argument("--out-cap", type=int, default=32)
    ap.add_argument("--miss-share", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dp-size", type=int, default=4)
    a = ap.parse_args()

    src = [json.loads(l) for l in open(a.src) if l.strip()]
    raw_apps = []
    for s in src:
        rq = s["requests"]
        for p, q in zip(rq, rq[1:]):
            raw_apps.append(len(q["prompt_ids"]) - common_prefix(p["prompt_ids"], q["prompt_ids"]))
    scale = a.append_mean / st.fmean(raw_apps)
    rng = random.Random(a.seed)

    out = []
    idx = 0
    n_forced = 0
    for c in range(a.copies):
        for s in src:
            rq = s["requests"]
            vocab = [t for t in rq[-1]["prompt_ids"] if t > 100]
            nonce = [rng.choice(vocab) for _ in range(4)]
            prompts = []
            prev_src = None
            for k, q in enumerate(rq):
                ids = q["prompt_ids"]
                if k == 0:
                    cur = nonce + ids[: a.init]
                else:
                    cp = common_prefix(prev_src, ids)
                    raw = ids[cp:]
                    n1 = max(a.append_min, min(a.append_max, round(len(raw) * scale)))
                    piece = raw[:n1] if len(raw) >= n1 else ids[-n1:]
                    cur = prompts[-1] + piece
                prompts.append(cur)
                prev_src = ids
            head = []
            reqs = []
            for k, (q, p) in enumerate(zip(rq, prompts)):
                forced = k > 0 and rng.random() < a.miss_share
                if forced:
                    head = [rng.choice(vocab), rng.choice(vocab)] + head
                    n_forced += 1
                pid = head + p
                reqs.append(
                    {
                        "t": 0.0,
                        "type": q["type"],
                        "model": q["model"],
                        "in": len(pid),
                        "out": min(q["out"], a.out_cap),
                        "think_time": q["think_time"],
                        "forced_miss": forced,
                        "prompt_ids": pid,
                    }
                )
            sid = salt_id(f"{s['id']}#c{c}", idx % a.dp_size, a.dp_size)
            out.append({"id": sid, "format": "text-v1", "source": s["source"] + "-short", "models": s["models"], "requests": reqs})
            idx += 1

    with open(a.out, "w") as f:
        for s in out:
            f.write(json.dumps(s, separators=(",", ":")) + "\n")
    ins = [q["in"] for s in out for q in s["requests"]]
    apps = [b["in"] - a_["in"] for s in out for a_, b in zip(s["requests"], s["requests"][1:])]
    firsts = [s["requests"][0]["in"] for s in out]
    lasts = [s["requests"][-1]["in"] for s in out]
    outs = [q["out"] for s in out for q in s["requests"]]
    print(
        f"wrote {a.out}: {len(out)} sessions, {len(ins)} turns, append scale {scale:.3f}; "
        f"context first {st.median(firsts):.0f} / last {st.median(lasts):.0f} (median), max {max(ins)}; "
        f"append mean {st.fmean(apps):.0f} median {st.median(apps):.0f} max {max(apps)}; out mean {st.fmean(outs):.1f}; "
        f"forced misses {n_forced} ({100 * n_forced / max(1, len(apps)):.1f} % of follow-ups); "
        f"ranks {[sum(1 for s in out if zlib.crc32(s['id'].encode()) % a.dp_size == r) for r in range(a.dp_size)]}"
    )


if __name__ == "__main__":
    main()
