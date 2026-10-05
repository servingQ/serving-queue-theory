#!/usr/bin/env python3
"""Lecture 7's discrete-event check on vLLM v1's engine rules (serQ #120).

Runs `lectures/queueing-serving/programs/metastable.sq` (N sessions in a closed
loop, a KV pool smaller than all contexts, vLLM's admission and block LRU)
with the pinned serQ CLI (`make serq`): a load sweep from a cold and from a
warm cache, and normal load -> burst -> normal load. Simulation output, not
measurements (rule 7). Writes research/metastability-serq.json; the figures
and tables are drawn by scripts/metastability_figs.py.
  python3 scripts/metastability_serq.py [--serq .serq/bin/serq]
"""
import argparse
import csv
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROG = ROOT / 'lectures/queueing-serving/programs/metastable.sq'
SEEDS = [1, 2, 3, 4, 5]
WARM = dict(Zwarm=200, twarm=300)   # a light first 300 s fills the cache with hits


def run(serq, seed, horizon, win, report=False, **settings):
    """Full-reuse hit rate and mean TTFT in windows of `win` seconds (and the
    run's JSON report if asked)."""
    with tempfile.TemporaryDirectory() as d:
        cmd = [str(serq), 'run', str(PROG), '--seed', str(seed), '--horizon', str(horizon),
               '--warmup', '0', '--dump', d, '--json']
        for k, v in settings.items():
            cmd += ['--set', f'{k}={v}']
        rep = json.loads(subprocess.check_output(cmd, text=True))
        bins = np.arange(0, horizon + win, win)

        def series(name):
            rows = list(csv.DictReader(open(Path(d) / f'{name}.csv')))
            t = np.array([float(r['time']) for r in rows])
            v = np.array([float(r['value']) for r in rows])
            i = np.digitize(t, bins) - 1
            return [float(v[i == k].mean()) if (i == k).any() else None
                    for k in range(len(bins) - 1)]
        out = (series('full_hit'), series('ttft'))
        return out + (rep,) if report else out


def tail_mean(xs, start):
    xs = [x for x in xs[start:] if x is not None]
    return float(np.mean(xs))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serq', type=Path, default=ROOT / '.serq/bin/serq')
    args = ap.parse_args()
    runtime = subprocess.check_output([str(args.serq), '--version'], text=True).strip()
    out = dict(note='serQ simulation of metastable.sq; not measurements',
                runtime=runtime, seeds=SEEDS, sweep=[], burst=[])
    # engine seconds per hit and per miss turn, from two loads: utilisation /
    # turn rate = h S_hit + (1 - h) S_miss at each, h the full-reuse rate
    rows = []
    for Z in [4, 1.5]:
        h, _, rep = run(args.serq, 1, 4000, 100, report=True, Z=Z)
        eng = next(x for x in rep['stages'] if x['name'] == 'engine')
        thk = next(x for x in rep['stages'] if x['name'] == 'think')
        rows.append((tail_mean(h, 20), eng['utilization'] / thk['throughput']))
    (h1, e1), (h2, e2) = rows
    s_miss = (e1 * h2 - e2 * h1) / (h2 - h1)
    s_hit = (e1 - (1 - h1) * s_miss) / h1
    out['engine_seconds'] = dict(points=rows, S_hit=s_hit, S_miss=s_miss)
    print(out['engine_seconds'], flush=True)
    # load sweep: mean over 2000-4000 s, cold start vs warm start
    for Z in [1.5, 2, 2.5, 3, 3.5, 4, 6, 8]:
        row = dict(Z=Z)
        for start in ['cold', 'warm']:
            hit, ttft = [], []
            for s in SEEDS:
                h, t = run(args.serq, s, 4000, 100, Z=Z, **(WARM if start == 'warm' else {}))
                hit.append(tail_mean(h, 20)); ttft.append(tail_mean(t, 20))
            row[start] = dict(hit=float(np.mean(hit)), hit_sd=float(np.std(hit)),
                              ttft=float(np.mean(ttft)), ttft_sd=float(np.std(ttft)))
        out['sweep'].append(row)
        print(row, flush=True)
    # burst: Z = 4 s, then 1.5 s for B seconds from t = 1000 s, then 4 s again
    win = 25
    for B in [0, 60, 300]:
        H = np.array([[np.nan if x is None else x for x in
                       run(args.serq, s, 3000, win, Z=4, Zb=1.5, t1=1000, B=B)[0]] for s in SEEDS])
        h = np.nanmean(H, 0)
        base = float(np.nanmean(h[500 // win:1000 // win]))
        end = 1000 + B
        t = np.arange(len(h)) * win
        # end of the first window after the burst whose hit rate is back within 0.05
        rec = 0.0 if B == 0 else next((float(tt + win - end) for tt, x in zip(t, h)
                                       if tt >= end and abs(x - base) <= 0.05), None)
        out['burst'].append(dict(B=B, base_hit=base, min_hit=float(np.nanmin(h[1000 // win:])),
                                 recovery_s=rec, window_s=win, hit=[float(x) for x in h]))
        print(B, base, rec, flush=True)
    path = ROOT / 'research/metastability-serq.json'
    path.write_text(json.dumps(out, indent=1) + '\n')
    print(f'wrote {path.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
