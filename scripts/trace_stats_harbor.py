#!/usr/bin/env python3
"""Workload statistics from Harbor agent trajectories (ATIF v1.x).

Reads `agent/trajectory.json` under one or more Harbor job directories
(e.g. `swebenchpro__claude-code`) and reports, per session and pooled, the
quantities the paper's formulation (§2) takes as inputs:

* turns per session, sub-agent (sidechain) count;
* context growth K_t (prompt tokens of the t-th LLM call), new tokens
  n_t = K_t - K_{t-1} - o_{t-1}, output tokens o_t;
* inter-call intervals (decode + tool + client time between consecutive
  main-agent LLM calls), a proxy for tool time τ_i;
* the resident-KV integral ∫K(t)dt per session vs the naive E[D]E[K]
  (paper §2.1, Campbell's theorem);
* hit/miss prefill work under the cost model P(n,K) = a n + b n (K + n/2)
  for a sweep of the crossover context K_c = a/b (context at which the
  attention term equals the dense term), and the CV² of the hit/miss
  mixture at several hit rates (paper Eq. cv2), split into the share of
  variance from the mixture vs from the spread of (n, K) alone.

Traces are workload measurements, not serving-system measurements: nothing
here is a TTFT or a throughput. Cache-hit fields are zero in these logs
(the gateway does not report them), so hits/misses are *policy outcomes
assumed*, not observed.

Usage: scripts/trace_stats_harbor.py JOBDIR [JOBDIR ...] [--tex OUTDIR]
"""
import argparse
import glob
import json
import math
import os
import statistics as st
from datetime import datetime


def parse_ts(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def load_session(path):
    d = json.load(open(path))
    main = []  # main-agent LLM calls in order
    side = 0
    for s in d['steps']:
        if s.get('source') != 'agent' or 'metrics' not in s:
            continue
        if s.get('extra', {}).get('is_sidechain'):
            side += 1
            continue
        m = s['metrics']
        main.append((parse_ts(s['timestamp']), m['prompt_tokens'], m['completion_tokens']))
    if len(main) < 2:
        return None
    ts = [t for t, _, _ in main]
    K = [k for _, k, _ in main]
    o = [c for _, _, c in main]
    n = [K[0]] + [max(K[t] - K[t - 1] - o[t - 1], 0) for t in range(1, len(K))]
    gaps = [ts[t] - ts[t - 1] for t in range(1, len(ts))]
    D = ts[-1] - ts[0]
    # resident KV integral: K_t held from call t until call t+1 (token-seconds)
    kv_int = sum(K[t] * gaps[t] for t in range(len(gaps)))
    return dict(path=path, turns=len(main), side=side, K=K, o=o, n=n, gaps=gaps, D=D,
                kv_int=kv_int)


def q(xs, p):
    xs = sorted(xs)
    if not xs:
        return float('nan')
    i = min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))
    return xs[i]


def cv2(xs):
    m = st.fmean(xs)
    return st.pvariance(xs) / (m * m) if m > 0 else float('nan')


def work(n, K, Kc):
    """P(n,K) in units of a: n + n (K + n/2) / Kc.  Kc = inf → linear only."""
    return n + (0.0 if math.isinf(Kc) else n * (K + n / 2) / Kc)


def mixture_cv2(sessions, Kc, p):
    """CV² of prefill work when each turn (t ≥ 2) hits w.p. p, plus the
    decomposition: variance from the mixture vs from (n, K) spread."""
    hits, misses = [], []
    for s in sessions:
        for t in range(1, s['turns']):
            hits.append(work(s['n'][t], s['K'][t] - s['n'][t], Kc))
            misses.append(work(s['K'][t], 0, Kc))
    mh, mm = st.fmean(hits), st.fmean(misses)
    vh, vm = st.pvariance(hits), st.pvariance(misses)
    mean = p * mh + (1 - p) * mm
    within = p * vh + (1 - p) * vm           # spread of (n, K) inside each branch
    between = p * (1 - p) * (mm - mh) ** 2   # the hit/miss mixture
    var = within + between
    return dict(cv2=var / mean ** 2, share_mixture=between / var if var > 0 else float('nan'),
                cv2_all_hit=vh / mh ** 2, miss_over_hit=mm / mh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('jobdirs', nargs='+')
    ap.add_argument('--tex', help='write LaTeX tables into this directory')
    ap.add_argument('--label', default='traces')
    a = ap.parse_args()
    sessions = []
    for jd in a.jobdirs:
        for f in sorted(glob.glob(os.path.join(jd, '*', 'agent', 'trajectory.json'))):
            s = load_session(f)
            if s:
                sessions.append(s)
    S = sessions
    print(f'{len(S)} sessions from {a.jobdirs}')
    if not S:
        raise SystemExit('no agent/trajectory.json with ≥ 2 main-agent LLM calls found')
    turns = [s['turns'] for s in S]
    print(f"turns/session: mean {st.fmean(turns):.1f} median {q(turns, .5)} p90 {q(turns, .9)} max {max(turns)}; CV² {cv2(turns):.2f}")
    print(f"sub-agent LLM calls/session: mean {st.fmean([s['side'] for s in S]):.1f}; sessions with sub-agents {sum(s['side'] > 0 for s in S)}")
    allK = [k for s in S for k in s['K'][1:]]
    alln = [x for s in S for x in s['n'][1:]]
    allo = [x for s in S for x in s['o']]
    gaps = [g for s in S for g in s['gaps']]
    finalK = [s['K'][-1] for s in S]
    print(f"context K (turn ≥ 2): median {q(allK, .5):,.0f} p90 {q(allK, .9):,.0f} max {max(allK):,}; final K median {q(finalK, .5):,.0f}")
    print(f"new tokens n (turn ≥ 2): median {q(alln, .5):,.0f} mean {st.fmean(alln):,.0f} p90 {q(alln, .9):,.0f}; CV² {cv2(alln):.2f}")
    print(f"output tokens o: median {q(allo, .5):,.0f} mean {st.fmean(allo):,.0f} p90 {q(allo, .9):,.0f}; CV² {cv2(allo):.2f}")
    print(f"reuse share of prefix tokens under perfect caching: {1 - sum(alln) / sum(allK):.3f}")
    print(f"inter-call gap (s): median {q(gaps, .5):.1f} mean {st.fmean(gaps):.1f} p90 {q(gaps, .9):.1f} p99 {q(gaps, .99):.1f}; CV² {cv2(gaps):.2f}")
    D = [s['D'] for s in S]
    meanK_sess = [st.fmean(s['K']) for s in S]
    naive = st.fmean(D) * st.fmean(allK)
    exact = st.fmean([s['kv_int'] for s in S])
    print(f"session length D (s): median {q(D, .5):.0f} mean {st.fmean(D):.0f}")
    print(f"resident KV: E[∫K dt] = {exact:,.0f} token·s vs naive E[D]E[K] = {naive:,.0f} (ratio {exact / naive:.2f}); corr(D, mean K) = {corr(D, meanK_sess):.2f}")
    rows = []
    print('\nprefill-work CV² of the hit/miss mixture (turns ≥ 2):')
    print(f"{'K_c':>8} {'miss/hit':>9} {'CV² all-hit':>12} " + ' '.join(f'p={p:.2f}: CV² (mix share)' for p in (0.90, 0.96, 0.99)))
    for Kc in (float('inf'), 100_000, 30_000, 10_000):
        r = [mixture_cv2(S, Kc, p) for p in (0.90, 0.96, 0.99)]
        kc = '∞' if math.isinf(Kc) else f'{Kc:,}'
        print(f"{kc:>8} {r[0]['miss_over_hit']:9.1f} {r[0]['cv2_all_hit']:12.2f} " + ' '.join(f"{x['cv2']:8.2f} ({x['share_mixture']:.2f})       " for x in r))
        rows.append((kc, r))
    if a.tex:
        os.makedirs(a.tex, exist_ok=True)
        with open(os.path.join(a.tex, f'tab-{a.label}-cv2.tex'), 'w') as f:
            f.write('% generated by scripts/trace_stats_harbor.py; do not edit\n')
            f.write('\\begin{tabular}{@{}rrrrrr@{}}\n\\toprule\n')
            f.write('$K_c$ & miss/hit & $\\mathrm{CV}^2$, all hit & $h=0.90$ & $h=0.96$ & $h=0.99$ \\\\\n\\midrule\n')
            for kc, r in rows:
                kcs = '$\\infty$' if kc == '∞' else kc.replace(',', '\\,')
                f.write(f"{kcs} & {r[0]['miss_over_hit']:.0f} & {r[0]['cv2_all_hit']:.2f} & " +
                        ' & '.join(f"{x['cv2']:.1f} ({100 * x['share_mixture']:.0f}\\,\\%)" for x in r) + ' \\\\\n')
            f.write('\\bottomrule\n\\end{tabular}\n')
        with open(os.path.join(a.tex, f'tab-{a.label}-workload.tex'), 'w') as f:
            f.write('% generated by scripts/trace_stats_harbor.py; do not edit\n')
            f.write('\\begin{tabular}{@{}lrrrr@{}}\n\\toprule\n & median & mean & p90 & $\\mathrm{CV}^2$ \\\\\n\\midrule\n')
            for name, xs, fmt in (('turns per session', turns, '{:.0f}'), ('context $K$ (tokens)', allK, '{:,.0f}'),
                                  ('new tokens $n$', alln, '{:,.0f}'), ('output tokens $o$', allo, '{:,.0f}'),
                                  ('inter-call gap (s)', gaps, '{:.1f}')):
                f.write(f"{name} & {fmt.format(q(xs, .5))} & {fmt.format(st.fmean(xs))} & {fmt.format(q(xs, .9))} & {cv2(xs):.2f} \\\\\n".replace(',', '\\,'))
            f.write('\\bottomrule\n\\end{tabular}\n')
        with open(os.path.join(a.tex, f'macros-{a.label}.tex'), 'w') as f:
            f.write('% generated by scripts/trace_stats_harbor.py; do not edit\n')
            f.write(f"\\newcommand{{\\trSessions}}{{{len(S)}}}\n")
            f.write(f"\\newcommand{{\\trReuse}}{{{100 * (1 - sum(alln) / sum(allK)):.1f}}}\n")
            f.write(f"\\newcommand{{\\trKvRatio}}{{{exact / naive:.2f}}}\n")
            f.write(f"\\newcommand{{\\trCorrDK}}{{{corr(D, meanK_sess):.2f}}}\n")
            f.write(f"\\newcommand{{\\trCvN}}{{{rows[0][1][0]['cv2_all_hit']:.1f}}}\n")  # append-only CV² (linear model)
        print('wrote tables to', a.tex)


def corr(x, y):
    mx, my = st.fmean(x), st.fmean(y)
    sx, sy = st.pstdev(x), st.pstdev(y)
    if sx == 0 or sy == 0:
        return float('nan')
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) * sx * sy)


if __name__ == '__main__':
    main()
