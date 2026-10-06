#!/usr/bin/env python3
"""Compare a serQ replay of the GPU testbed (`.serq/src/examples/replay/vllm_replay.sq`)
with the measured vLLM runs (`data/exp/gpu/e2b/<run>/rounds.jsonl`,
research/research-plan.md §0), turn by turn.

    python3 scripts/exp/serq_vs_vllm.py --gpu ~/serving-queue-theory-gpu/data/exp/gpu/e2b \
        --serq .serq/src --out data/exp/seq/gpu.txt s50_base s42_base s35_base s30_base s25_base s35_m10

For every run: the serQ program is run with the run's spacing and trace
(`_m10` runs use the forced-miss trace), its observations are dumped, and
the turns are paired by (session, round). Reported inside the analysis
window (90 s after the first arrival to the last arrival): the hit /
partial / miss counts by the rule of `analyze_e2.py` (a follow-up is a
hit if its cached tokens cover the previous prompt plus completion up to
one block), the mean TTFT per class, observed and modelled, the fraction
of turns the two agree on (hit vs not) and the Spearman correlation of
the per-turn TTFTs.
"""
import argparse
import json
import os
import subprocess
import sys

# the CLI of the pinned serQ release (scripts/fetch_serq.sh)
ROOT_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".serq", "bin")
from statistics import mean


def classify(prefix, cached, sub=16):
    if prefix is None:
        return "cold"
    if prefix > 0 and cached >= min(0.9 * prefix, prefix - sub):
        return "hit"
    return "partial" if cached > 0 else "miss"


def spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    if len(xs) < 3:
        return float("nan")
    rx, ry = ranks(xs), ranks(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def load_gpu(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    rows = [r for r in rows if not r.get("error")]
    t0 = min(r["sent_monotonic_s"] for r in rows)
    by = {}
    for r in rows:
        by[(r["session_index"], r["round_index"])] = r
    out = {}
    for (s, k), r in by.items():
        prev = by.get((s, k - 1))
        prefix = None if prev is None else (prev.get("prompt_tokens") or 0) + (prev.get("completion_tokens") or 0)
        out[(s, k)] = dict(
            sent=r["sent_monotonic_s"] - t0,
            ttft=r["ttft_s"],
            cls=classify(prefix, r.get("cached_tokens") or 0),
        )
    last = max(v["sent"] for v in out.values())
    return out, last


def run_serq(serq_dir, trace, spacing, dump):
    prog = os.path.join(serq_dir, "examples", "replay", "vllm_replay.sq")
    os.makedirs(dump, exist_ok=True)
    csv = os.path.abspath(os.path.join(serq_dir, "examples", "replay", "data", trace + ".csv"))
    serq = os.path.join(ROOT_BIN, "serq")
    args = [prog, "--horizon", "6000", "--warmup", "0", "--seed", "1", "--trace", csv, "--set", f"spacing={spacing}"]
    # what ran, as IR (the program with its constants folded and the trace)
    subprocess.run([serq, "ir", *args], check=True, stdout=open(os.path.join(dump, "program.ir.json"), "w"))
    subprocess.run([serq, "run", *args, "--dump", dump], check=True,
                   stdout=open(os.path.join(dump, "report.txt"), "w"))

    def read(name):
        d = {}
        for line in open(os.path.join(dump, f"{name}.csv")).read().splitlines()[1:]:
            t, s, k, v = line.split(",")
            d[(int(s), int(k) - 1)] = float(v)
        return d

    ttft, cached, prefix, sent = read("ttft"), read("cached_tokens"), read("prefix"), read("sent")
    out = {}
    for key, v in ttft.items():
        pre = None if key[1] == 0 else prefix[key]
        out[key] = dict(sent=sent[key], ttft=v, cls=classify(pre, cached[key]))
    return out


def report(name, gpu, model, last):
    lines = [f"== {name}: window 90 s .. {last:.0f} s after the first arrival"]
    keys = [k for k, v in gpu.items() if 90.0 <= v["sent"] <= last and k in model]
    lines.append(f"  turns paired: {len(keys)} (observed {sum(1 for v in gpu.values() if 90.0 <= v['sent'] <= last)}, model {len(model)})")
    for cls in ["cold", "hit", "partial", "miss"]:
        go = [gpu[k]["ttft"] for k in keys if gpu[k]["cls"] == cls]
        mo = [model[k]["ttft"] for k in keys if model[k]["cls"] == cls]
        fo = f"{mean(go):.3f} ({len(go)})" if go else "-"
        fm = f"{mean(mo):.3f} ({len(mo)})" if mo else "-"
        lines.append(f"  {cls:8s} TTFT observed / model: {fo:>16} / {fm:>16}")
    fol = [k for k in keys if k[1] > 0]
    agree = sum(1 for k in fol if (gpu[k]["cls"] == "hit") == (model[k]["cls"] == "hit")) / max(1, len(fol))
    hit_o = sum(1 for k in fol if gpu[k]["cls"] == "hit") / max(1, len(fol))
    hit_m = sum(1 for k in fol if model[k]["cls"] == "hit") / max(1, len(fol))
    lines.append(f"  follow-up hit fraction observed / model: {hit_o:.3f} / {hit_m:.3f}; agreement on hit-vs-not: {agree:.3f}")
    xs = [gpu[k]["ttft"] for k in keys]
    ys = [model[k]["ttft"] for k in keys]
    lines.append(f"  mean TTFT observed / model: {mean(xs):.3f} / {mean(ys):.3f}; Spearman {spearman(xs, ys):.3f}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", required=True)
    ap.add_argument("--serq", default=".serq/src")
    ap.add_argument("--out")
    ap.add_argument("runs", nargs="+")
    args = ap.parse_args()
    texts = []
    for run in args.runs:
        params = json.load(open(os.path.join(args.gpu, run, "params.json")))
        spacing = params["spacing_s"]
        trace = "short_m10" if "m10" in run else "short_base"
        if run.endswith("_s1"):
            trace += "_s1"
        gpu, last = load_gpu(os.path.join(args.gpu, run, "rounds.jsonl"))
        dump = os.path.join("data", "exp", "seq", run)
        model = run_serq(args.serq, trace, spacing, dump)
        texts.append(report(run, gpu, model, last))
        print(texts[-1], flush=True)
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        open(args.out, "w").write("\n".join(texts) + "\n")


if __name__ == "__main__":
    main()
