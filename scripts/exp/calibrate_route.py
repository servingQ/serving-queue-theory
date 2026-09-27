#!/usr/bin/env python3
"""Calibrate the two overhead constants of route/programs/vllm_replay.route
(c_it: fixed seconds per iteration, c0: seconds per request outside the
engine) on the light-load A100 runs and report every run.

    python3 scripts/exp/calibrate_route.py --gpu ~/serving-queue-theory-gpu/data/exp/gpu/e2b \
        --fit s50_base s42_base --check s35_base s30_base s25_base s35_m10 s42_m10 s25_m10

For each (c_it, c0) on the grid the program replays the fit runs; the pair
with the smallest mean |log(model TTFT / measured TTFT)| over their
windows is kept, then every run is reported with it (window: 90 s after
the first send to the last send; full hit as in analyze_e2.py)."""
import argparse
import json
import math
import os
import subprocess
import tempfile

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def measured(gpu, run):
    rows = [json.loads(l) for l in open(os.path.join(gpu, run, "rounds.jsonl")) if l.strip()]
    rows = [r for r in rows if not r.get("error")]
    t0 = min(r["sent_monotonic_s"] for r in rows)
    by = {(r["session_index"], r["round_index"]): r for r in rows}
    hi = max(r["sent_monotonic_s"] - t0 for r in rows)
    tt, fol, hits = [], 0, 0
    for (s, k), r in by.items():
        if not 90 <= r["sent_monotonic_s"] - t0 <= hi:
            continue
        tt.append(r["ttft_s"])
        p = by.get((s, k - 1))
        if p is not None:
            pre = (p.get("prompt_tokens") or 0) + (p.get("completion_tokens") or 0)
            fol += 1
            hits += (r.get("cached_tokens") or 0) >= min(0.9 * pre, pre - 16)
    return sum(tt) / len(tt), hits / max(1, fol), hi, json.load(open(os.path.join(gpu, run, "params.json")))["spacing_s"]


def model(run, spacing, hi, c_it, c0, tmp):
    trace = "short_m10" if "m10" in run else "short_base"
    if run.endswith("_s1"):
        trace += "_s1"
    csv = os.path.abspath(os.path.join(ROOT, "route", "programs", "data", trace + ".csv"))
    src = open(os.path.join(ROOT, "route", "programs", "vllm_replay.route")).read()
    src = src.replace('trace "data/short_base.csv" ordered;', f'trace "{csv}" ordered;')
    prog = os.path.join(tmp, "p.route")
    open(prog, "w").write(src)
    d = os.path.join(tmp, "d")
    subprocess.run([os.path.join(ROOT, "route", "target", "release", "route"), "run", prog,
                    "--set", f"spacing={spacing}", "--set", f"c_it={c_it}", "--set", f"c0={c0}",
                    "--dump", d], check=True, stdout=subprocess.DEVNULL)

    def rd(n):
        out = {}
        for l in open(os.path.join(d, n + ".csv")).read().splitlines()[1:]:
            t, s, k, v = l.split(",")
            out[(int(s), int(k))] = float(v)
        return out

    tt, sent, cached, prefix = rd("ttft"), rd("sent"), rd("cached_tokens"), rd("prefix")
    win = [k for k in tt if 90 <= sent[k] <= hi]
    fol = [k for k in win if k[1] > 1]
    hit = sum(1 for k in fol if cached[k] >= min(0.9 * prefix[k], prefix[k] - 16)) / max(1, len(fol))
    return sum(tt[k] for k in win) / len(win), hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", required=True)
    ap.add_argument("--fit", nargs="+", required=True)
    ap.add_argument("--check", nargs="+", default=[])
    ap.add_argument("--out")
    a = ap.parse_args()
    meas = {r: measured(a.gpu, r) for r in a.fit + a.check}
    best = None
    with tempfile.TemporaryDirectory() as tmp:
        for c_it in [0.0, 0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.008, 0.010, 0.0139]:
            for c0 in [0.02, 0.03, 0.04, 0.05, 0.06, 0.07]:
                err = 0.0
                for r in a.fit:
                    mt, _, hi, sp = meas[r]
                    t, _ = model(r, sp, hi, c_it, c0, tmp)
                    err += abs(math.log(t / mt))
                err /= len(a.fit)
                if best is None or err < best[0]:
                    best = (err, c_it, c0)
        err, c_it, c0 = best
        lines = [f"calibrated on {', '.join(a.fit)}: c_it = {c_it} s, c0 = {c0} s (mean |log ratio| {err:.3f})",
                 "run          role   TTFT measured / model   full-hit measured / model"]
        for r in a.fit + a.check:
            mt, mh, hi, sp = meas[r]
            t, h = model(r, sp, hi, c_it, c0, tmp)
            lines.append(f"{r:12s} {'fit' if r in a.fit else 'check':5s} {mt:8.3f} / {t:8.3f}        {mh:.3f} / {h:.3f}")
    txt = "\n".join(lines)
    print(txt)
    if a.out:
        open(a.out, "w").write(txt + "\n")


if __name__ == "__main__":
    main()
