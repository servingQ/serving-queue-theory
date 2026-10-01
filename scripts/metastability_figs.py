#!/usr/bin/env python3
"""Figures for lecture 7 (serQ #120), in the style of Alvaro et al.'s
experiments: drift field, recovery time by initial state, the metastable
region, burst response, and the serQ load sweep.

CTMC panels are exact computations from scripts/metastability_ctmc.py; serQ
panels read research/metastability-serq.json (scripts/metastability_serq.py).
Writes lectures/queueing-serving/fig-meta-*.pdf, research/metastability-figs.json
and lectures/queueing-serving/metastability-figs.tex (macros; generated).
  uv run --with numpy --with scipy --with matplotlib python scripts/metastability_figs.py
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use('pdf')
import matplotlib.pyplot as plt
import numpy as np
import scipy.sparse.linalg as spl

import metastability_ctmc as mc

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'lectures/queueing-serving'
BLUE, ORANGE, AQUA, YELLOW = '#2a78d6', '#eb6834', '#1baf7a', '#eda100'
INK, INK2, GRID = '#0b0b0b', '#52514e', '#e4e3df'
plt.rcParams.update({'font.size': 8, 'axes.edgecolor': INK2, 'axes.labelcolor': INK,
                     'xtick.color': INK2, 'ytick.color': INK2, 'axes.spines.top': False,
                     'axes.spines.right': False, 'axes.grid': True, 'grid.color': GRID,
                     'grid.linewidth': 0.5, 'lines.linewidth': 1.6, 'legend.frameon': False,
                     'pdf.fonttype': 42})
B = mc.BASE
N = B['N']


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / f'fig-meta-{name}.pdf')
    plt.close(fig)


def drift_field():
    """Mean drift of (h, m), queued hits and queued misses (the queue and the
    orbit of Alvaro et al.), averaged over the stationary law of the cold
    thinkers c within each cell, and the stationary mass of each cell."""
    st, idx, Q = mc.build3(N, B['Z'], B['C'], B['a'])
    pi = mc.stationary(Q)
    q = st[:, 0]
    lost = st[:, 1]
    Qc = Q.tocsr()
    dq = np.zeros(len(st)); dl = np.zeros(len(st))
    for i in range(len(st)):
        row = Qc.getrow(i)
        for j, r in zip(row.indices, row.data):
            if j != i:
                dq[i] += r * (q[j] - q[i]); dl[i] += r * (lost[j] - lost[i])
    mass = np.zeros((N + 1, N + 1)); U = np.zeros_like(mass); V = np.zeros_like(mass)
    np.add.at(mass, (lost, q), pi)
    np.add.at(U, (lost, q), pi * dq); np.add.at(V, (lost, q), pi * dl)
    ok = mass > 1e-12
    U[ok] /= mass[ok]; V[ok] /= mass[ok]
    fig, ax = plt.subplots(figsize=(3.0, 2.8))
    lm = np.where(mass > 1e-12, np.log10(np.maximum(mass, 1e-12)), np.nan)
    im = ax.imshow(lm, origin='lower', cmap='Blues', vmin=-8, vmax=-1, aspect='auto',
                   extent=(-0.5, N + 0.5, -0.5, N + 0.5))
    gq, gl = np.meshgrid(np.arange(N + 1), np.arange(N + 1))
    sel = ok & (gl % 2 == 0) & (mass > 1e-8)
    mag = np.hypot(U, V)
    ax.quiver(gq[sel], gl[sel], (U / np.maximum(mag, 1e-9))[sel], (V / np.maximum(mag, 1e-9))[sel],
              color=ORANGE, scale=28, width=0.005, headwidth=3.5)
    ax.set_xlabel('queued hits $h$'); ax.set_ylabel('queued misses $m$')
    hmax = int(gq[mass > 1e-12].max())
    ax.set_xlim(-0.5, hmax + 0.5); ax.set_ylim(-0.5, N + 0.5); ax.grid(False)
    cb = fig.colorbar(im, ax=ax, shrink=0.85); cb.set_label(r'$\log_{10}$ stationary mass', color=INK)
    save(fig, 'drift')


def recovery_by_start():
    st, idx, Q = mc.build3(N, B['Z'], B['C'], B['a'])
    pi = mc.stationary(Q)
    q = st[:, 0] + st[:, 1]
    t = mc.hitting_time(Q, q <= 1)
    up, dn = mc.lumped(N, B['Z'], st, pi, mc.SH, mc.SM)
    piL, _ = mc.bd(up, dn)
    q0 = np.arange(2, N + 1)
    hmax = B['C'] - N                                    # the most waiting hits the cache holds
    warm = [t[idx[(min(k, hmax), k - min(k, hmax), 0)]] for k in q0]   # as many waiting hits as fit
    cold = [t[idx[(0, k, N - k)]] for k in q0]           # queued misses, cold thinkers
    one = [mc.bd_recovery(piL, dn, k, 1) for k in q0]
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    ax.plot(q0, cold, color=ORANGE, label='3D, cold cache')
    ax.plot(q0, warm, color=BLUE, label='3D, warm cache')
    ax.plot(q0, one, color=AQUA, ls='--', label='queue length only')
    ax.set_yscale('log'); ax.set_xlabel('initial queued turns'); ax.set_ylabel('mean time to $q\\leq1$ (s)')
    ax.legend(loc='lower right')
    save(fig, 'recovery')
    return dict(q0=q0.tolist(), warm=[float(x) for x in warm], cold=[float(x) for x in cold],
                lumped=[float(x) for x in one])


def region():
    """Slowest relaxation time 1/lambda_2 over (a, Z); circles mark a bimodal
    queue-length law."""
    A = [0.2, 0.4, 0.6, 0.8, 0.9, 1.0, 1.1, 1.2]
    Zs = np.arange(15, 47.5, 2.5)
    T = np.zeros((len(A), len(Zs))); bim = np.zeros_like(T, dtype=bool)
    for i, a in enumerate(A):
        for j, Z in enumerate(Zs):
            st, idx, Q = mc.build3(N, Z, B['C'], a)
            pi = mc.stationary(Q)
            q = st[:, 0] + st[:, 1]
            pq = np.bincount(q, weights=pi, minlength=N + 1)
            T[i, j] = 1 / mc.slow_rates(Q, k=1)[0]
            bim[i, j] = bimodal(pq)
        print('region a', a, flush=True)
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    im = ax.imshow(np.log10(T), origin='lower', aspect='auto', cmap='Blues',
                   extent=(Zs[0] - 1.25, Zs[-1] + 1.25, -0.5, len(A) - 0.5))
    ii, jj = np.nonzero(bim)
    ax.scatter(Zs[jj], ii, s=14, facecolors='none', edgecolors=ORANGE, linewidths=1.2,
               label='bimodal')
    ax.set_yticks(range(len(A))); ax.set_yticklabels([f'{a:g}' for a in A])
    ax.set_xlabel('think time $Z$ (s)'); ax.set_ylabel('memory per queued turn $a$')
    ax.grid(False)
    ax.legend(loc='lower left', bbox_to_anchor=(0, 1.0), fontsize=7, handletextpad=0.2)
    cb = fig.colorbar(im, ax=ax, shrink=0.85); cb.set_label(r'$\log_{10}(1/\lambda_2)$ (s)', color=INK)
    save(fig, 'region')
    return dict(a=A, Z=Zs.tolist(), relax_s=T.tolist(), bimodal=bim.tolist())


def bimodal(pq, depth=0.5):
    pk = [n for n in range(N + 1) if (n == 0 or pq[n] >= pq[n - 1])
          and (n == N or pq[n] >= pq[n + 1]) and pq[n] > 1e-4]
    return any(pq[pk[i]:pk[j] + 1].min() < depth * min(pq[pk[i]], pq[pk[j]])
               for i in range(len(pk)) for j in range(i + 1, len(pk)))


def burst_ctmc():
    st, idx, Q = mc.build3(N, B['Z'], B['C'], B['a'])
    _, _, Qb = mc.build3(N, 12.0, B['C'], B['a'])
    q = st[:, 0] + st[:, 1]
    x0 = np.zeros(len(st)); x0[idx[(0, 0, 0)]] = 1
    t_pre = 200.0
    x = spl.expm_multiply(Q.T * t_pre, x0)
    curves = {}
    for Bl in [0, 30, 60]:
        ts, ys = [0.0], [float(x0 @ q)]
        pre = spl.expm_multiply(Q.T, x0, start=0, stop=t_pre, num=21, endpoint=True)
        ts = list(np.linspace(0, t_pre, 21)); ys = [float(v @ q) for v in pre]
        y = x
        if Bl:
            seg = spl.expm_multiply(Qb.T, x, start=0, stop=Bl, num=7, endpoint=True)
            ts += list(t_pre + np.linspace(0, Bl, 7))[1:]; ys += [float(v @ q) for v in seg][1:]
            y = seg[-1]
        seg = spl.expm_multiply(Q.T, y, start=0, stop=2000, num=81, endpoint=True)
        ts += list(t_pre + Bl + np.linspace(0, 2000, 81))[1:]; ys += [float(v @ q) for v in seg][1:]
        curves[Bl] = (ts, ys)
    return curves


def burst_figure(serq):
    curves = burst_ctmc()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.6, 2.3))
    for Bl, col in zip([0, 30, 60], [INK2, BLUE, ORANGE]):
        ts, ys = curves[Bl]
        a1.plot(ts, ys, color=col, label=f'burst {Bl} s' if Bl else 'no burst (from warm, empty)')
    a1.set_xlabel('time (s)'); a1.set_ylabel(r'$\mathbb{E}\,q(t)$')
    a1.set_title('(a) queue-and-cache chain, $a=1$', fontsize=8, color=INK, loc='left')
    a1.legend(loc='lower right')
    for row, col in zip(serq['burst'], [INK2, BLUE, ORANGE]):
        w = row['window_s']; h = row['hit']
        a2.plot(np.arange(len(h)) * w + w / 2, h, color=col,
                label=f"burst {row['B']} s" if row['B'] else 'no burst')
    a2.set_xlabel('time (s)'); a2.set_ylabel('hit rate (25 s windows)')
    a2.set_title('(b) vLLM rules in serQ, mean of 5 seeds', fontsize=8, color=INK, loc='left')
    a2.set_xlim(500, 2000); a2.legend(loc='lower right')
    save(fig, 'burst')
    return {str(k): dict(t=[float(x) for x in v[0]], q=v[1]) for k, v in curves.items()}


def sweep_figure(serq):
    Z = [r['Z'] for r in serq['sweep']]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.6, 2.2))
    for start, col, mk, ls, mfc in [('cold', ORANGE, 'o', '-', ORANGE), ('warm', BLUE, 's', '--', 'none')]:
        for ax, key in [(a1, 'hit'), (a2, 'ttft')]:
            ax.errorbar(Z, [r[start][key] for r in serq['sweep']], [r[start][key + '_sd'] for r in serq['sweep']],
                        color=col, marker=mk, ms=5 if start == 'warm' else 3, mfc=mfc, ls=ls,
                        capsize=2, label=f'{start} start')
    a1.set_xlabel('think time $Z$ (s)'); a1.set_ylabel('hit rate')
    a2.set_xlabel('think time $Z$ (s)'); a2.set_ylabel('mean TTFT (s)')
    a1.legend(loc='lower right')
    save(fig, 'sweep')


def macros(serq, rec, reg):
    sw = {r['Z']: r for r in serq['sweep']}
    gap = max(abs(r['cold']['hit'] - r['warm']['hit']) for r in serq['sweep'])
    bu = {r['B']: r for r in serq['burst']}
    bim_a = sorted({reg['a'][i] for i, row in enumerate(reg['bimodal']) if any(row)})
    m = ['% Generated by scripts/metastability_figs.py; do not edit.',
         f"\\newcommand{{\\metaSqHitHigh}}{{{sw[4]['cold']['hit']:.2f}}}",
         # the admission rule's cliff: N = C + Z / S_miss at Z* = (N - C) S_miss, C the pool in contexts
         f"\\newcommand{{\\metaZstar}}{{{(40 - 34000 * 16 / 16700) * serq['engine_seconds']['S_miss']:.1f}}}",
         f"\\newcommand{{\\metaSqHitAtTwoHalf}}{{{sw[2.5]['cold']['hit']:.2f}}}",
         f"\\newcommand{{\\metaSqHitAtThree}}{{{sw[3]['cold']['hit']:.2f}}}",
         f"\\newcommand{{\\metaSqHitAtTwo}}{{{sw[2]['cold']['hit']:.2f}}}",
         f"\\newcommand{{\\metaSqHitLow}}{{{sw[1.5]['cold']['hit']:.2f}}}",
         f"\\newcommand{{\\metaSqTtftHigh}}{{{sw[4]['cold']['ttft']:.2f}}}",
         f"\\newcommand{{\\metaSqTtftLow}}{{{sw[1.5]['cold']['ttft']:.1f}}}",
         f"\\newcommand{{\\metaSqColdWarmGap}}{{{gap:.3f}}}",
         f"\\newcommand{{\\metaSqRecSixty}}{{{bu[60]['recovery_s']:.0f}}}",
         f"\\newcommand{{\\metaSqRecThreeHundred}}{{{bu[300]['recovery_s']:.0f}}}",
         f"\\newcommand{{\\metaSqMinHit}}{{{bu[300]['min_hit']:.2f}}}",
         f"\\newcommand{{\\metaRecColdTen}}{{{rec['cold'][rec['q0'].index(10)]:.0f}}}",
         f"\\newcommand{{\\metaRecWarmTen}}{{{rec['warm'][rec['q0'].index(10)]:.0f}}}",
         f"\\newcommand{{\\metaRecLumpTen}}{{{rec['lumped'][rec['q0'].index(10)]:.0f}}}",
         f"\\newcommand{{\\metaBimodalAmin}}{{{min(bim_a):g}}}" if bim_a else '\\newcommand{\\metaBimodalAmin}{--}']
    (OUT / 'metastability-figs.tex').write_text('\n'.join(m) + '\n')


def main():
    serq = json.loads((ROOT / 'research/metastability-serq.json').read_text())
    drift_field()
    rec = recovery_by_start()
    burst = burst_figure(serq)
    sweep_figure(serq)
    reg = region()
    macros(serq, rec, reg)
    (ROOT / 'research/metastability-figs.json').write_text(
        json.dumps(dict(recovery=rec, region=reg, burst_ctmc=burst), indent=1) + '\n')
    print('wrote fig-meta-*.pdf, metastability-figs.tex, research/metastability-figs.json')


if __name__ == '__main__':
    main()
