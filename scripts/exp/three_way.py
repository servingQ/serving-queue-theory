#!/usr/bin/env python3
"""Three-way comparison of a GPU replay: the measured run, the real vLLM
scheduler under serQ's time model (`.serq/src/tools/vllm_replay_oracle.py`),
and the serQ program (`data/exp/seq/<run>/*.csv` from seq_vs_vllm.py).

    python3 scripts/exp/three_way.py --gpu ~/serving-queue-theory-gpu/data/exp/gpu/e2b s35_base ...

Per source, inside the window (90 s after the first send to the last send
of the measured run): follow-up turns that are full hits (cached >=
min(0.9 prefix, prefix - 16), prefix = previous prompt + completion), mean
cached tokens per follow-up, mean TTFT, and the number of follow-ups whose
cached tokens are below the previous prompt's full blocks (a lost prefix).
"""
import argparse
import json
import os
from statistics import mean


def cls(prefix, cached, sub=16):
    if prefix is None:
        return "cold"
    if prefix > 0 and cached >= min(0.9 * prefix, prefix - sub):
        return "hit"
    return "partial" if cached > 0 else "miss"


def summarise(rows, lo, hi):
    """rows: {(s, k): dict(sent, ttft, prompt, cached, out)} with k from 0."""
    fol = []
    for (s, k), r in rows.items():
        if k == 0 or not (lo <= r["sent"] <= hi):
            continue
        p = rows.get((s, k - 1))
        if p is None:
            continue
        prefix = p["prompt"] + p["out"]
        full = (p["prompt"] // 16) * 16
        fol.append((cls(prefix, r["cached"]), r["cached"], r["ttft"], r["cached"] < full - 16))
    win = [r["ttft"] for r in rows.values() if lo <= r["sent"] <= hi and r["ttft"] is not None]
    return dict(
        n=len(fol),
        hit=sum(1 for f in fol if f[0] == "hit") / max(1, len(fol)),
        lost=sum(1 for f in fol if f[3]),
        cached=mean(f[1] for f in fol) if fol else float("nan"),
        ttft=mean(win) if win else float("nan"),
    )


def load_gpu(path):
    rows = {}
    raw = [json.loads(l) for l in open(path) if l.strip()]
    raw = [r for r in raw if not r.get("error")]
    t0 = min(r["sent_monotonic_s"] for r in raw)
    for r in raw:
        rows[(r["session_index"], r["round_index"])] = dict(
            sent=r["sent_monotonic_s"] - t0, ttft=r["ttft_s"], prompt=r["prompt_tokens"],
            cached=r.get("cached_tokens") or 0, out=r.get("completion_tokens") or 0)
    return rows


def load_oracle(path):
    rows = {}
    for line in open(path).read().splitlines()[1:]:
        s, k, sent, first, done, prompt, cached, out = line.split(",")
        rows[(int(s), int(k) - 1)] = dict(
            sent=float(sent), ttft=float(first) - float(sent) if first != "None" else None,
            prompt=int(prompt), cached=int(cached) if cached != "None" else 0, out=int(out))
    return rows


def load_seq(d):
    def read(name):
        out = {}
        for line in open(os.path.join(d, f"{name}.csv")).read().splitlines()[1:]:
            t, s, k, v = line.split(",")
            out[(int(s), int(k) - 1)] = float(v)
        return out
    ttft, cached, sent, prefix = read("ttft"), read("cached_tokens"), read("sent"), read("prefix")
    rows = {}
    for key in ttft:
        rows[key] = dict(sent=sent[key], ttft=ttft[key], cached=cached[key], prompt=0, out=0)
    # prompt/out of the previous turn from `prefix` (= prev prompt + prev out)
    for (s, k), r in rows.items():
        nxt = (s, k + 1)
        if nxt in prefix:
            r["prompt"], r["out"] = prefix[nxt], 0
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", required=True)
    ap.add_argument("--oracle", default="data/exp/seq/oracle")
    ap.add_argument("--seq", default="data/exp/seq")
    ap.add_argument("--out")
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    lines = ["run       source   follow-ups  full-hit  lost-prefix  mean-cached  mean-TTFT"]
    for run in a.runs:
        g = load_gpu(os.path.join(a.gpu, run, "rounds.jsonl"))
        hi = max(r["sent"] for r in g.values())
        for name, rows in [("measured", g),
                           ("vllm-sim", load_oracle(os.path.join(a.oracle, run + ".csv"))),
                           ("seq", load_seq(os.path.join(a.seq, run)))]:
            m = summarise(rows, 90.0, hi)
            lines.append(f"{run:9s} {name:8s} {m['n']:10d} {m['hit']:9.3f} {m['lost']:12d} {m['cached']:12.0f} {m['ttft']:10.3f}")
    txt = "\n".join(lines)
    print(txt)
    if a.out:
        open(a.out, "w").write(txt + "\n")


if __name__ == "__main__":
    main()
