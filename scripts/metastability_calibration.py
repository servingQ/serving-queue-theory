#!/usr/bin/env python3
"""Lecture 7's counterpart of the calibration experiment of Alvaro et al.
(§6.1): fit a queue-and-cache chain to serQ's load sweep on vLLM's rules
(research/metastability-serq.json), then predict serQ's held-out burst
recoveries.

Two chains (scripts/metastability_ctmc.py): the processor-sharing chain of
Definition 7.10, with vLLM's memory accounting (an admitted miss holds the
prefix it recomputes, at most 16 admitted), and the FIFO-victim chain
`build3_fifo` (one turn served at a time; the LRU victim is the next waiting
turn in line with weight beta). Models and simulation, not measurements.
Writes research/metastability-calibration.json, lectures/queueing-serving/
fig-meta-calibration.pdf and metastability-exp.tex (generated; do not edit).
  uv run --with numpy --with scipy --with matplotlib python scripts/metastability_calibration.py
"""
import json
import time
from pathlib import Path

import matplotlib
matplotlib.use('pdf')
import matplotlib.pyplot as plt
import numpy as np
import scipy.sparse.linalg as spl

import metastability_ctmc as mc
from metastability_figs import BLUE, ORANGE, AQUA, INK, INK2, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'lectures/queueing-serving'

# serQ's replica (programs/metastable.sq) in the chain's units. Engine seconds
# per turn from the serQ report: utilisation / turn rate at Z = 4 s (hit 0.80)
# and at Z = 1.5 s (hit 0.01, engine saturated) give S_hit and S_miss. Memory
# in prefixes of K0 + n + o = 16 700 tokens: the pool is 34 000 x 16 tokens,
# an admitted turn adds n + o = 700, and at most max_seqs = 16 are admitted.
SQ = dict(N=40, sh=0.037, sm=0.336, C=34000 * 16 / 16700, a=700 / 16700, qcap=16)


def ps_chain(Z, C):
    return mc.build3(SQ['N'], Z, C, SQ['a'], sh=SQ['sh'], sm=SQ['sm'], qcap=SQ['qcap'], miss_mem=True)


def fifo_chain(Z, C, beta):
    return mc.build3_fifo(SQ['N'], Z, C, SQ['a'], sh=SQ['sh'], sm=SQ['sm'], qcap=SQ['qcap'], beta=beta)


def ps_rates(st):
    h, m = st[:, 0], st[:, 1]
    q = np.maximum(h + m, 1)
    return h / (q * SQ['sh']), m / (q * SQ['sm'])


def fifo_rates(st):
    k = st[:, 3]
    return (k == 1) / SQ['sh'], (k == 2) / SQ['sm']


def share(x, rh, rm):
    return float((x @ rh) / (x @ rh + x @ rm))


def sweep(build, rates, Zs, **kw):
    out = []
    for Z in Zs:
        st, idx, Q = build(Z, **kw)
        out.append(share(mc.stationary(Q), *rates(st)))
    return np.array(out)


def fit(build, rates, Zs, target, grid):
    rows = []
    for kw in grid:
        pred = sweep(build, rates, Zs, **kw)
        rows.append(kw | dict(rmse=float(np.sqrt(((pred - target) ** 2).mean())), pred=pred.tolist()))
        print(build.__name__, kw, round(rows[-1]['rmse'], 3), flush=True)
    return min(rows, key=lambda r: r['rmse']), rows


def burst_curve(build, rates, B_s, kw, Z=4.0, Zb=1.5, t1=1000.0, horizon=1600.0, dt=5.0):
    """Expected hit share of completions for normal -> burst -> normal from the
    stationary law at Z: the chain's version of serQ's burst runs."""
    st, idx, Q = build(Z, **kw)
    _, _, Qb = build(Zb, **kw)
    rh, rm = rates(st)
    x = mc.stationary(Q)
    base = share(x, rh, rm)
    ts, ys = [t1], [base]
    seg = spl.expm_multiply(Qb.T, x, start=0, stop=B_s, num=int(B_s / dt) + 1, endpoint=True)
    ts += list(t1 + np.linspace(0, B_s, len(seg)))[1:]; ys += [share(v, rh, rm) for v in seg][1:]
    rest = horizon - t1 - B_s
    seg = spl.expm_multiply(Q.T, seg[-1], start=0, stop=rest, num=int(rest / dt) + 1, endpoint=True)
    ts += list(t1 + B_s + np.linspace(0, rest, len(seg)))[1:]; ys += [share(v, rh, rm) for v in seg][1:]
    end = t1 + B_s
    rec = next((t - end for t, y in zip(ts, ys) if t > end and abs(y - base) <= 0.05), None)
    return dict(t=[float(t) for t in ts], hit=ys, base=base, recovery_s=rec)


def figure(Zs, target, ps_best, fifo_best, burst, serq):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.6, 2.4))
    a1.plot(Zs, target, color=INK2, marker='o', ms=3, label='serQ (vLLM rules)')
    a1.plot(Zs, ps_best['pred'], color=AQUA, ls='--', label='PS chain, best fit')
    a1.plot(Zs, fifo_best['pred'], color=BLUE, label='FIFO-victim chain, best fit')
    a1.set_xlabel('think time $Z$ (s)'); a1.set_ylabel('hit rate'); a1.legend(loc='lower right', fontsize=6)
    a1.set_title('(a) fitted on the load sweep', fontsize=8, color=INK, loc='left')
    for (Bs, cur), col in zip(burst.items(), [BLUE, ORANGE]):
        a2.plot(cur['t'], cur['hit'], color=col, label=f'chain, burst {Bs} s')
    for row, col in zip([r for r in serq['burst'] if r['B']], [BLUE, ORANGE]):
        w = row['window_s']; h = row['hit']
        a2.plot(np.arange(len(h)) * w + w / 2, h, color=col, ls=':', label=f"serQ, burst {row['B']} s")
    a2.set_xlim(950, 1500); a2.set_xlabel('time (s)'); a2.set_ylabel('hit rate')
    a2.set_title('(b) held-out bursts', fontsize=8, color=INK, loc='left'); a2.legend(loc='lower right', fontsize=6)
    save(fig, 'calibration')


def main():
    serq = json.loads((ROOT / 'research/metastability-serq.json').read_text())
    Zs = [r['Z'] for r in serq['sweep']]
    target = np.array([(r['cold']['hit'] + r['warm']['hit']) / 2 for r in serq['sweep']])
    t0 = time.perf_counter()
    ps_ab = sweep(ps_chain, ps_rates, Zs, C=SQ['C'])
    ps_best, ps_rows = fit(ps_chain, ps_rates, Zs, target, [dict(C=C) for C in [30, 32.6, 35, 38, 41]])
    fifo_best, fifo_rows = fit(fifo_chain, fifo_rates, Zs, target,
                               [dict(C=C, beta=b) for C in [35, 36, 37, 38] for b in [3.0, 4.0, 6.0]])
    kw = {k: fifo_best[k] for k in ['C', 'beta']}
    burst = {Bs: burst_curve(fifo_chain, fifo_rates, Bs, kw) for Bs in [60, 300]}
    seconds = time.perf_counter() - t0
    figure(Zs, target, ps_best, fifo_best, burst, serq)
    res = dict(note='CTMC and serQ, not measurements', serq_mapping=SQ, Z=Zs, serq=target.tolist(),
               ps=dict(ab_initio=ps_ab.tolist(), best=ps_best, grid=ps_rows),
               fifo=dict(best=fifo_best, grid=fifo_rows), burst_prediction={str(k): v for k, v in burst.items()},
               seconds=seconds)
    (ROOT / 'research/metastability-calibration.json').write_text(json.dumps(res, indent=1) + '\n')
    sqb = {r['B']: r for r in serq['burst']}
    slope = lambda p: 'rises' if p[0] > p[-1] else 'falls'
    m = ['% Generated by scripts/metastability_calibration.py; do not edit.',
         f"\\newcommand{{\\metaPsRmse}}{{{ps_best['rmse']:.2f}}}",
         f"\\newcommand{{\\metaPsLowZ}}{{{ps_best['pred'][0]:.2f}}}",
         f"\\newcommand{{\\metaFifoC}}{{{fifo_best['C']:g}}}",
         f"\\newcommand{{\\metaFifoBeta}}{{{fifo_best['beta']:g}}}",
         f"\\newcommand{{\\metaFifoRmse}}{{{fifo_best['rmse']:.2f}}}",
         f"\\newcommand{{\\metaFifoLowZ}}{{{fifo_best['pred'][0]:.2f}}}",
         f"\\newcommand{{\\metaSqLowZ}}{{{target[0]:.2f}}}",
         f"\\newcommand{{\\metaAbC}}{{{SQ['C']:.1f}}}",
         f"\\newcommand{{\\metaPredRecSixty}}{{{burst[60]['recovery_s']:.0f}}}",
         f"\\newcommand{{\\metaPredRecThreeHundred}}{{{burst[300]['recovery_s']:.0f}}}",
         f"\\newcommand{{\\metaSqRecSixtyB}}{{{sqb[60]['recovery_s']:.0f}}}",
         f"\\newcommand{{\\metaSqRecThreeHundredB}}{{{sqb[300]['recovery_s']:.0f}}}",
         f"\\newcommand{{\\metaCalMinutes}}{{{seconds / 60:.0f}}}"]
    (OUT / 'metastability-exp.tex').write_text('\n'.join(m) + '\n')
    print(json.dumps(dict(ps=ps_best['rmse'], fifo={k: fifo_best[k] for k in ['C', 'beta', 'rmse']},
                          pred={k: v['recovery_s'] for k, v in burst.items()},
                          serq={k: sqb[k]['recovery_s'] for k in [60, 300]}, minutes=seconds / 60), indent=1))


if __name__ == '__main__':
    main()
