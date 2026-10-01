#!/usr/bin/env python3
"""Lecture 7's picture of a metastable failure, after the trajectories of
Alvaro et al.: normal load, a 60 s burst, normal load again, for a replica
whose waiting turns hold memory and for one that takes memory at admission.

Sample paths of the queue-and-cache chain (scripts/metastability_ctmc.py,
`build3`), drawn by the Gillespie algorithm from its generator, for the picture;
the probabilities quoted in the lecture are exact transient laws
(`expm_multiply`), with a no-burst control and the stationary value. Model
output, not measurements. Writes lectures/queueing-serving/fig-meta-failure.pdf,
research/metastability-failure.json and metastability-failure.tex (macros).
  uv run --with numpy --with scipy --with matplotlib python scripts/metastability_failure.py
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use('pdf')
import matplotlib.pyplot as plt
import numpy as np
import scipy.sparse.linalg as spl

import metastability_ctmc as mc
from metastability_figs import BLUE, ORANGE, INK, INK2, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'lectures/queueing-serving'
N, C, A, Z, ZB = 40, 48, 1.2, 42.5, 12.0     # memory 1.2 contexts per waiting turn
T_BURST, B, HORIZON, WIN, PATHS = 500.0, 60.0, 3000.0, 50.0, 40
ARMS = [('held while waiting', None, ORANGE), ('taken at admission, $B=16$', 16, BLUE)]


def gillespie(phases, x0, rng):
    """Exact sample path through a list of (generator in CSR, duration)."""
    t, i = 0.0, x0
    T, S = [0.0], [x0]
    for Q, dur in phases:
        end = t + dur
        while True:
            lo, hi = Q.indptr[i], Q.indptr[i + 1]
            js, rs = Q.indices[lo:hi], Q.data[lo:hi]
            off = js != i
            js, rs = js[off], rs[off]
            tot = rs.sum()
            dt = rng.exponential(1 / tot)
            if t + dt > end:
                t = end
                break
            t += dt
            i = rng.choice(js, p=rs / tot)
            T.append(t); S.append(i)
    return np.array(T), np.array(S)


def arm(qcap, seed):
    st, idx, Q = mc.build3(N, Z, C, A, qcap=qcap)
    _, _, Qb = mc.build3(N, ZB, C, A, qcap=qcap)
    Q, Qb = Q.tocsr(), Qb.tocsr()
    rng = np.random.default_rng(seed)
    grid = np.arange(0, HORIZON + 1, 10.0)
    wins = np.arange(0, HORIZON + WIN, WIN)
    qs, hits, done = [], [], []
    for _ in range(PATHS):
        T, S = gillespie([(Q, T_BURST), (Qb, B), (Q, HORIZON - T_BURST - B)], idx[(0, 0, 0)], rng)
        h, m = st[S, 0], st[S, 1]
        qs.append((h + m)[np.searchsorted(T, grid, side='right') - 1])
        # a completion lowers h + m by one; it was a hit if h fell
        dq = np.diff(h + m)
        t_c = T[1:][dq == -1]
        is_hit = (np.diff(h) == -1)[dq == -1]
        k = np.digitize(t_c, wins) - 1
        n_all = np.bincount(k, minlength=len(wins) - 1)[:len(wins) - 1]
        n_hit = np.bincount(k, weights=is_hit, minlength=len(wins) - 1)[:len(wins) - 1]
        hits.append(n_hit); done.append(n_all)
    qs = np.array(qs)
    H, D = np.array(hits).sum(0), np.array(done).sum(0)
    return dict(grid=grid.tolist(), q_mean=qs.mean(0).tolist(), q_paths=qs[:3].tolist(),
                p_congested=(qs >= 16).mean(0).tolist(),
                win=(wins[:-1] + WIN / 2).tolist(), hit_share=(H / np.maximum(D, 1)).tolist(),
                goodput=(D / (PATHS * WIN)).tolist())


def exact(qcap):
    """P(q >= 16) at 1000 s and at the horizon, after the burst and without it,
    from the warm empty queue; and the stationary value."""
    st, idx, Q = mc.build3(N, Z, C, A, qcap=qcap)
    _, _, Qb = mc.build3(N, ZB, C, A, qcap=qcap)
    bad = (st[:, 0] + st[:, 1]) >= 16
    x0 = np.zeros(len(st)); x0[idx[(0, 0, 0)]] = 1
    pre = spl.expm_multiply(Q.T * T_BURST, x0)
    after = spl.expm_multiply(Qb.T * B, pre)
    out = {}
    for name, y0, t0 in [('burst', after, T_BURST + B), ('no_burst', x0, 0.0)]:
        out[name] = {str(t): float(spl.expm_multiply(Q.T * (t - t0), y0)[bad].sum()) for t in (1000, 3000)}
    out['stationary'] = float(mc.stationary(Q)[bad].sum())
    return out


def main():
    res = {name: arm(qcap, seed=7) for name, qcap, _ in ARMS}
    ex = {name: exact(qcap) for name, qcap, _ in ARMS}
    fig, (a0, a1, a2) = plt.subplots(3, 1, figsize=(6.4, 4.6), sharex=True,
                                     gridspec_kw=dict(height_ratios=[1, 2, 1.6]))
    t = np.array([0, T_BURST, T_BURST, T_BURST + B, T_BURST + B, HORIZON])
    a0.plot(t, [N / Z, N / Z, N / ZB, N / ZB, N / Z, N / Z], color=INK2)
    a0.set_ylabel('offered\nturns/s'); a0.set_ylim(0, N / ZB * 1.15)
    for ax in (a0, a1, a2):
        ax.axvspan(T_BURST, T_BURST + B, color='#e4e3df', zorder=0)
    for name, _, col in ARMS:
        r = res[name]
        for p in r['q_paths']:
            a1.plot(r['grid'], p, color=col, lw=0.6, alpha=0.35)
        a1.plot(r['grid'], r['q_mean'], color=col, lw=1.8, label=name)
        a2.plot(r['win'], r['hit_share'], color=col, lw=1.6, label=name)
    a1.set_ylabel('waiting turns $q$'); a1.legend(loc='upper right', fontsize=7)
    a2.set_ylabel('hit share of\ncompleted turns'); a2.set_xlabel('time (s)'); a2.set_ylim(0, 1.02)
    a1.annotate('burst', xy=(T_BURST + B / 2, 38), ha='center', fontsize=7, color=INK2)
    save(fig, 'failure')
    held, adm = ex[ARMS[0][0]], ex[ARMS[1][0]]
    m = ['% Generated by scripts/metastability_failure.py; do not edit.',
         f"\\newcommand{{\\metaFailZ}}{{{Z:g}}}", f"\\newcommand{{\\metaFailZb}}{{{ZB:g}}}",
         f"\\newcommand{{\\metaFailA}}{{{A:g}}}", f"\\newcommand{{\\metaFailPaths}}{{{PATHS}}}",
         f"\\newcommand{{\\metaFailHeldThousand}}{{{held['burst']['1000']:.2f}}}",
         f"\\newcommand{{\\metaFailHeldEnd}}{{{held['burst']['3000']:.2f}}}",
         f"\\newcommand{{\\metaFailHeldCtlEnd}}{{{held['no_burst']['3000']:.2f}}}",
         f"\\newcommand{{\\metaFailHeldStat}}{{{held['stationary']:.2f}}}",
         f"\\newcommand{{\\metaFailAdmThousand}}{{{adm['burst']['1000']:.2f}}}",
         f"\\newcommand{{\\metaFailAdmEnd}}{{{adm['burst']['3000']:.2f}}}",
         f"\\newcommand{{\\metaFailAdmStat}}{{{adm['stationary']:.2f}}}"]
    (OUT / 'metastability-failure.tex').write_text('\n'.join(m) + '\n')
    (ROOT / 'research/metastability-failure.json').write_text(json.dumps(dict(exact=ex, paths=res), indent=1) + '\n')
    print('\n'.join(m))


if __name__ == '__main__':
    main()
