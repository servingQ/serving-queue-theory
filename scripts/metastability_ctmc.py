#!/usr/bin/env python3
"""Metastability of a replica that loses prefixes while congested (serQ #120).

Exact numerics on two CTMCs, no simulation and no measurement (rule 7):
* the birth-death chain on the queue length (lecture 7, `Metastability.lean`):
  open and closed, product-form law, passage times, spectral gap;
* a three-dimensional closed chain (queued hits h, queued misses m, cold
  thinking sessions c) in which a prefix is lost when the idle-prefix cache
  C - a q overflows, to test whether the queue length is enough.

Writes research/metastability-results.json and the lecture tables
lectures/queueing-serving/metastability-tables.tex (generated; do not edit). Run:
  uv run --with numpy --with scipy python scripts/metastability_ctmc.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl
from scipy.sparse.csgraph import connected_components
from scipy.linalg import eigh_tridiagonal

ROOT = Path(__file__).resolve().parents[1]
SH, SM = 0.5, 5.0  # hit and miss work (s), the ratio of lecture 6's example


# ---------------------------------------------------------------- birth-death
def bd(up, dn):
    """Stationary law, log-weights of a finite birth-death chain."""
    M = len(up) - 1
    lw = np.zeros(M + 1)
    for n in range(M):
        lw[n + 1] = lw[n] + np.log(up[n] / dn[n + 1])
    pi = np.exp(lw - lw.max())
    return pi / pi.sum(), lw


def bd_pass(pi, dn, k):
    """Mean time from k to k-1 (passTime in Metastability.lean)."""
    return pi[k:].sum() / (pi[k] * dn[k])


def bd_recovery(pi, dn, m, n):
    return sum(bd_pass(pi, dn, k) for k in range(n + 1, m + 1))


def bd_gap(up, dn):
    """Spectral gap via the symmetrised (reversible) generator."""
    d = -(up + dn)
    d[0] = -up[0]
    d[-1] = -dn[-1]
    off = -np.sqrt(up[:-1] * dn[1:])
    ev = np.sort(-eigh_tridiagonal(d, off, eigvals_only=True))
    return float(ev[1])


def modes(pi):
    M = len(pi) - 1
    return [n for n in range(M + 1)
            if (n == 0 or pi[n] >= pi[n - 1]) and (n == M or pi[n] > pi[n + 1])]


def logistic_s(n, n0, width, sh=SH, sm=SM):
    return sh + (sm - sh) / (1 + np.exp(-(n - n0) / width))


def closed_bd(N, Z, s):
    up = np.array([(N - n) / Z for n in range(N + 1)], float)
    dn = np.array([0.0] + [1 / s(n) for n in range(1, N + 1)])
    return up, dn


def exp_closed_scaling():
    """Arrhenius: recovery time and 1/gap grow exponentially in N at fixed
    per-session parameters (Z, n0, width scale with N)."""
    rows = []
    for N in [20, 40, 60, 80, 120, 160]:
        Z, n0, w = 1.5 * N, 0.25 * N, 0.05 * N
        up, dn = closed_bd(N, Z, lambda n: logistic_s(n, n0, w))
        pi, lw = bd(up, dn)
        md = modes(pi)
        good, bad = md[0], md[-1]
        sad = good + int(np.argmin(lw[good:bad + 1]))
        rows.append(dict(N=N, Z=Z, modes=md, saddle=sad,
                         mass_bad=float(pi[sad:].sum()),
                         barrier_bad_to_good=float(lw[bad] - lw[sad]),
                         barrier_good_to_bad=float(lw[good] - lw[sad]),
                         recovery_bad_to_good_s=float(bd_recovery(pi, dn, bad, good)),
                         inv_gap_s=1 / bd_gap(up, dn)))
    return rows


def exp_closed_hysteresis(N=40):
    """Fluid crossings (N-n) s(n+1) = Z as Z varies: the load at which the good
    mode disappears differs from the load at which the bad one does. A 5 s
    grid for the record and a 0.05 s grid for the two thresholds."""
    s = lambda n: logistic_s(n, 0.25 * N, 0.05 * N)
    rows = []
    for Z in np.arange(10, 141, 5):
        up, dn = closed_bd(N, Z, s)
        pi, lw = bd(up, dn)
        rows.append(dict(Z=float(Z), modes=modes(pi), gap=bd_gap(up, dn),
                         mean_q=float(np.arange(N + 1) @ pi)))
    two = [float(Z) for Z in np.arange(10, 140, 0.05)
           if len(modes(bd(*closed_bd(N, Z, s))[0])) >= 2]
    return dict(grid=rows, two_modes_Z_min=min(two), two_modes_Z_max=max(two),
                ratio=max(two) / min(two))


def exp_open(M=400):
    """Open queue truncated at M: stability limit 1/S_miss (ratio test) and,
    inside the band 1/S_miss < lam < 1/s(0), the mean time to collapse from
    empty (to the far side of the fluid saddle)."""
    n0, w = 20.0, 4.0
    s = lambda n: logistic_s(n, n0, w)
    rows = []
    for lam in [0.15, 0.19, 0.21, 0.25, 0.5, 1.0, 1.5]:
        up = np.full(M + 1, lam)
        dn = np.array([0.0] + [1 / s(n) for n in range(1, M + 1)])
        pi, lw = bd(up, dn)
        drift = [lam * s(n + 1) - 1 for n in range(M)]
        sad = next((n for n in range(M) if drift[n] > 0), None)
        # mean time to climb from 0 past the saddle (to sad + 10): the sum of
        # upward passages k -> k+1, sum_{j<=k} pi_j / (pi_k lam), in log space
        log10_T = None
        if sad is not None and sad + 10 < M:
            cum = np.logaddexp.accumulate(lw)
            terms = cum[:sad + 10] - lw[:sad + 10] - np.log(lam)
            log10_T = float(np.logaddexp.reduce(terms) / np.log(10))
        rows.append(dict(lam=lam, lam_S_miss=lam * SM, lam_S_hit=lam * SH,
                         fluid_saddle=sad, truncated_mass_top_half=float(pi[M // 2:].sum()),
                         log10_time_to_collapse_from_empty_s=log10_T))
    return rows


# ------------------------------------------------------- three-dimensional chain
def build3(N, Z, C, a, sh=SH, sm=SM, phi=0.0, qcap=None, miss_mem=False):
    """States (h, m, c); w = N - h - m - c warm thinkers, q = h + m queued.
    Warm returns are hits, cold returns misses; processor sharing over the
    queue; a completion leaves a warm thinker. After every transition, while
    the idle prefixes w + h exceed C - a q, one is evicted: a queued hit with
    probability 1 - phi (LRU: its last use is oldest), else a warm thinker
    (phi = 1 protects waiting prefixes). With `qcap`, only the first `qcap`
    queued turns take memory (an engine that allocates at admission, with a
    batch cap). With `miss_mem`, an admitted miss also holds one prefix of
    memory, the blocks it is recomputing, as in vLLM."""
    idx, states = {}, []
    for h in range(N + 1):
        for m in range(N + 1 - h):
            for c in range(N + 1 - h - m):
                idx[(h, m, c)] = len(states)
                states.append((h, m, c))

    def evict(st):
        out, done = [(1.0, st)], []
        while out:
            p, (h, m, c) = out.pop()
            w, q = N - h - m - c, h + m
            adm = q if qcap is None else min(q, qcap)
            used = w + h + (min(m, adm) if miss_mem else 0)
            if used <= C - a * adm or w + h == 0:
                done.append((p, (h, m, c)))
            elif h > 0 and w > 0:
                out += [x for x in [(p * (1 - phi), (h - 1, m + 1, c)),
                                    (p * phi, (h, m, c + 1))] if x[0] > 0]
            elif h > 0:
                out.append((p, (h - 1, m + 1, c)))
            else:
                out.append((p, (h, m, c + 1)))
        return done

    rows, cols, vals = [], [], []

    def add(i, rate, targ):
        for p, t in evict(targ):
            j = idx[t]
            if j != i:
                rows.append(i); cols.append(j); vals.append(rate * p)

    for i, (h, m, c) in enumerate(states):
        w, q = N - h - m - c, h + m
        if w > 0: add(i, w / Z, (h + 1, m, c))
        if c > 0: add(i, c / Z, (h, m + 1, c - 1))
        if h > 0: add(i, h / (q * sh), (h - 1, m, c))
        if m > 0: add(i, m / (q * sm), (h, m - 1, c))
    n = len(states)
    Q = sp.csr_matrix((vals, (rows, cols)), shape=(n, n))
    Q = (Q - sp.diags(np.asarray(Q.sum(1)).ravel())).tocsc()
    return np.array(states), idx, Q


def recurrent_class(Q):
    """The closed communicating class (the support of the stationary law):
    the strongly connected component with no transition leaving it."""
    n, lab = connected_components(Q, directed=True, connection='strong')
    A = Q.tocoo()
    leaves = np.zeros(n, bool)
    off = A.row != A.col
    leaves[lab[A.row[off]][lab[A.row[off]] != lab[A.col[off]]]] = True
    closed = [k for k in range(n) if not leaves[k]]
    assert len(closed) == 1
    return lab == closed[0]


def build3_ordered(N, Z, C, a, sh=SH, sm=SM, phi=0.0, qcap=16):
    """The queue-and-cache chain with one turn in service at a time, picked
    uniformly from the queue when the server frees (a stand-in for FIFO that
    does not let short hits overtake), instead of processor sharing. States
    (h, m, c, k): k = 0 idle, 1 serving a hit, 2 serving a miss (counted in h
    or m). The turn in service holds its prefix and cannot be evicted; the
    idle prefixes w + h plus a served miss's recomputed prefix must fit in
    C - a min(q, qcap)."""
    idx, states = {}, []
    for h in range(N + 1):
        for m in range(N + 1 - h):
            for c in range(N + 1 - h - m):
                for k in ([0] if h + m == 0 else [k for k in (1, 2) if (k == 1 and h) or (k == 2 and m)]):
                    idx[(h, m, c, k)] = len(states)
                    states.append((h, m, c, k))

    def evict(st):
        out, done = [(1.0, st)], []
        while out:
            p, (h, m, c, k) = out.pop()
            w, q = N - h - m - c, h + m
            used = w + h + (k == 2)
            hw = h - (k == 1)                      # waiting hits, evictable
            if used <= C - a * min(q, qcap) or w + hw == 0:
                done.append((p, (h, m, c, k)))
            elif hw > 0 and w > 0:
                out += [x for x in [(p * (1 - phi), (h - 1, m + 1, c, k)),
                                    (p * phi, (h, m, c + 1, k))] if x[0] > 0]
            elif hw > 0:
                out.append((p, (h - 1, m + 1, c, k)))
            else:
                out.append((p, (h, m, c + 1, k)))
        return done

    def start(h, m, c):
        q = h + m
        if q == 0:
            return [(1.0, (0, 0, c, 0))]
        return [x for x in [(h / q, (h, m, c, 1)), (m / q, (h, m, c, 2))] if x[0] > 0]

    rows, cols, vals = [], [], []

    def add(i, rate, targets):
        for p0, t0 in targets:
            for p, t in evict(t0):
                j = idx[t]
                if j != i:
                    rows.append(i); cols.append(j); vals.append(rate * p0 * p)

    for i, (h, m, c, k) in enumerate(states):
        w = N - h - m - c
        if w > 0: add(i, w / Z, [(1.0, (h + 1, m, c, k if k else 1))])
        if c > 0: add(i, c / Z, [(1.0, (h, m + 1, c - 1, k if k else 2))])
        if k == 1: add(i, 1 / sh, start(h - 1, m, c))
        if k == 2: add(i, 1 / sm, start(h, m - 1, c))
    n = len(states)
    Q = sp.csr_matrix((vals, (rows, cols)), shape=(n, n))
    Q = (Q - sp.diags(np.asarray(Q.sum(1)).ravel())).tocsc()
    return np.array(states), idx, Q


def build3_fifo(N, Z, C, a, sh=SH, sm=SM, qcap=16, beta=1.0):
    """Like `build3_ordered`, but LRU picks its victim where FIFO serves next:
    the waiting hit evicted is the oldest one, and it is served before the
    other waiting turns. The victim is a waiting hit with probability
    beta hw / (beta hw + w) (hw waiting hits, w warm thinkers): beta > 1 says a
    waiting prefix is stochastically older than a thinking one, not always.
    States (h, m, c, k, e): e of the m misses are evicted turns at the head
    of the line. Service starts with a head miss if e > 0,
    else with a waiting turn picked uniformly. This is what makes LRU under
    FIFO the cyclic worst case at saturation."""
    idx, states = {}, []
    for h in range(N + 1):
        for m in range(N + 1 - h):
            for c in range(N + 1 - h - m):
                ks = [0] if h + m == 0 else [k for k in (1, 2) if (k == 1 and h) or (k == 2 and m)]
                for k in ks:
                    for e in range(m - (k == 2) + 1):
                        idx[(h, m, c, k, e)] = len(states)
                        states.append((h, m, c, k, e))

    def evict(st):
        out, done = [(1.0, st)], []
        while out:
            p, (h, m, c, k, e) = out.pop()
            w, q = N - h - m - c, h + m
            used = w + h + (k == 2)
            hw = h - (k == 1)
            if used <= C - a * min(q, qcap) or w + hw == 0:
                done.append((p, (h, m, c, k, e)))
            else:
                ph = beta * hw / (beta * hw + w)
                out += [x for x in [(p * ph, (h - 1, m + 1, c, k, e + 1)),
                                    (p * (1 - ph), (h, m, c + 1, k, e))] if x[0] > 0]
        return done

    def start(h, m, c, e):
        q = h + m
        if q == 0:
            return [(1.0, (0, 0, c, 0, 0))]
        if e > 0:
            return [(1.0, (h, m, c, 2, e - 1))]
        return [x for x in [(h / q, (h, m, c, 1, 0)), (m / q, (h, m, c, 2, 0))] if x[0] > 0]

    rows, cols, vals = [], [], []

    def add(i, rate, targets):
        for p0, t0 in targets:
            for p, t in evict(t0):
                j = idx[t]
                if j != i:
                    rows.append(i); cols.append(j); vals.append(rate * p0 * p)

    for i, (h, m, c, k, e) in enumerate(states):
        w = N - h - m - c
        if w > 0: add(i, w / Z, [(1.0, (h + 1, m, c, k if k else 1, e))])
        if c > 0: add(i, c / Z, [(1.0, (h, m + 1, c - 1, k if k else 2, e))])
        if k == 1: add(i, 1 / sh, start(h - 1, m, c, e))
        if k == 2: add(i, 1 / sm, start(h, m - 1, c, e))
    n = len(states)
    Q = sp.csr_matrix((vals, (rows, cols)), shape=(n, n))
    Q = (Q - sp.diags(np.asarray(Q.sum(1)).ravel())).tocsc()
    return np.array(states), idx, Q


def stationary(Q):
    QT = Q.T.tocsc()
    x = spl.spsolve(QT[1:, 1:], -QT[1:, 0].toarray().ravel())
    pi = np.concatenate([[1.0], x])
    return pi / pi.sum()


def hitting_time(Q, target):
    """Mean hitting time of the boolean set `target` from every state."""
    keep = np.where(~target)[0]
    A = -Q[keep][:, keep]
    t = np.zeros(Q.shape[0])
    t[keep] = spl.spsolve(A.tocsc(), np.ones(len(keep)))
    return t


def slow_rates(Q, k=3):
    """Smallest nonzero decay rates of the generator (shift-invert)."""
    vals = spl.eigs(Q.T, k=k + 1, sigma=-1e-9, return_eigenvectors=False)
    vals = np.sort(np.abs(np.real(vals)))
    return [float(v) for v in vals[1:k + 1]]


def summarise3(N, states, pi, Q, sh, sm, good_q=1, bad_lo=16):
    q = states[:, 0] + states[:, 1]
    pq = np.bincount(q, weights=pi, minlength=N + 1)
    thr = (pi * np.where(states[:, 0] > 0, states[:, 0] / np.maximum(q, 1) / sh, 0)
           + pi * np.where(states[:, 1] > 0, states[:, 1] / np.maximum(q, 1) / sm, 0)).sum()
    t = hitting_time(Q, q <= good_q)
    bad = q >= bad_lo
    rec = float((pi[bad] * t[bad]).sum() / pi[bad].sum()) if pi[bad].sum() > 0 else None
    return pq, dict(mean_q=float(np.arange(N + 1) @ pq), p_good=float(pq[:4].sum()),
                    p_bad=float(pq[bad_lo:].sum()), throughput=float(thr),
                    mean_response_s=float((np.arange(N + 1) @ pq) / thr),
                    recovery_from_bad_s=rec)


def lumped(N, Z, states, pi, sh, sm):
    """Queue length alone: birth (N-q)/Z, death the stationary conditional
    mean service rate at q (preserves the stationary marginal exactly)."""
    q = states[:, 0] + states[:, 1]
    rate = np.where(q > 0, (states[:, 0] / sh + states[:, 1] / sm) / np.maximum(q, 1), 0)
    pq = np.bincount(q, weights=pi, minlength=N + 1)
    dn = np.bincount(q, weights=pi * rate, minlength=N + 1) / np.maximum(pq, 1e-300)
    up = np.array([(N - k) / Z for k in range(N + 1)], float)
    return up, dn


BASE = dict(N=40, Z=27.0, C=48, a=1.0)


def exp_queue_enough():
    N, Z, C, a = BASE['N'], BASE['Z'], BASE['C'], BASE['a']
    states, idx, Q = build3(N, Z, C, a)
    pi = stationary(Q)
    pq, summ = summarise3(N, states, pi, Q, SH, SM)
    up, dn = lumped(N, Z, states, pi, SH, SM)
    piL, _ = bd(up, dn)
    q = states[:, 0] + states[:, 1]
    bad = q >= 16
    t3 = hitting_time(Q, q <= 1)
    # 1D recovery from each bad level, weighted like the 3D one
    recL = sum(pq[k] * bd_recovery(piL, dn, k, 1) for k in range(16, N + 1)) / pq[16:].sum()
    # warm vs cold start at q = 0: probability of the bad region after T
    warm = np.zeros(len(states)); warm[idx[(0, 0, 0)]] = 1
    cold = np.zeros(len(states)); cold[idx[(0, 0, N)]] = 1
    horizon = {}
    for T in [30, 100, 300, 1000]:
        pw = spl.expm_multiply(Q.T * T, warm)
        pc = spl.expm_multiply(Q.T * T, cold)
        horizon[T] = dict(p_bad_warm=float(pw[bad].sum()), p_bad_cold=float(pc[bad].sum()),
                          mean_q_warm=float(pw @ q), mean_q_cold=float(pc @ q))
    rec = recurrent_class(Q)
    return dict(params=BASE | dict(sh=SH, sm=SM), states=len(states), summary=summ,
                recurrent_states=int(rec.sum()), recurrent_max_h=int(states[rec, 0].max()),
                recurrent_max_c=int(states[rec, 2].max()),
                marginal_max_abs_diff=float(np.abs(piL - pq).max()),
                slow_rates_3d=slow_rates(Q), gap_1d=bd_gap(up, dn),
                recovery_bad_to_q1_3d_s=float((pi[bad] * t3[bad]).sum() / pi[bad].sum()),
                recovery_bad_to_q1_1d_s=float(recL),
                warm_vs_cold=horizon, pq=[float(x) for x in pq])


def exp_burst():
    """Normal load -> burst (think time Z_b) for B seconds -> normal load, from
    the warm empty state. Probability of the bad region 600 s after the burst
    ends, and the mean time from there to an empty-ish queue."""
    N, Z, C, a = BASE['N'], BASE['Z'], BASE['C'], BASE['a']
    states, idx, Q = build3(N, Z, C, a)
    _, _, Qb = build3(N, 12.0, C, a)
    q = states[:, 0] + states[:, 1]
    t_rec = hitting_time(Q, q <= 1)
    x0 = np.zeros(len(states)); x0[idx[(0, 0, 0)]] = 1
    rows = []
    for B in [0, 10, 30, 60, 120]:
        x = spl.expm_multiply(Qb.T * B, x0) if B else x0
        at_end = dict(mean_q=float(x @ q), mean_cold=float(x @ states[:, 2]))
        y = spl.expm_multiply(Q.T * 600, x)
        rows.append(dict(burst_s=B, at_burst_end=at_end,
                         p_bad_600s_after=float(y[q >= 16].sum()),
                         mean_time_to_q1_after_burst_s=float(x @ t_rec)))
    return dict(burst_Z=12.0, rows=rows)


def exp_interventions():
    N, Z, C, a = BASE['N'], BASE['Z'], BASE['C'], BASE['a']
    arms = {
        'base': dict(),
        r'prefill $\times1.25$ (hit and miss)': dict(sh=SH / 1.25, sm=SM / 1.25),
        r'hit path $\times1.25$': dict(sh=SH / 1.25),
        r'miss path $\times1.25$ (recompute or reload)': dict(sm=SM / 1.25),
        r'KV capacity $C+4$': dict(C=C + 4),
        r'protect waiting, $\phi=1$': dict(phi=1.0),
        r'protect waiting, $\phi=0.5$': dict(phi=0.5),
    }
    out = {}
    for name, kw in arms.items():
        args = dict(N=N, Z=Z, C=C, a=a, sh=SH, sm=SM, phi=0.0) | kw
        states, idx, Q = build3(**args)
        pi = stationary(Q)
        _, summ = summarise3(N, states, pi, Q, args['sh'], args['sm'])
        out[name] = summ
    return out


def fmt(x, d=2):
    return f'{x:.{d}f}'


def sci(x):
    e = int(np.floor(np.log10(x)))
    return f'{x / 10 ** e:.1f}\\times10^{{{e}}}' if e >= 4 else f'{x:.0f}'


def tex_tables(res):
    """LaTeX fragments for lecture 7, one macro per table."""
    out = ['% Generated by scripts/metastability_ctmc.py; do not edit.']
    rows = [f"{r['lam']:.2f} & {fmt(r['lam_S_miss'])} & "
            f"{r['fluid_saddle'] if r['fluid_saddle'] is not None else '--'} & "
            + (f"$10^{{{r['log10_time_to_collapse_from_empty_s']:.1f}}}$"
               if r['log10_time_to_collapse_from_empty_s'] is not None else '--') + r' \\'
            for r in res['open']]
    out.append('\\newcommand{\\metaOpenTable}{\\begin{tabular}{rrrr}\\toprule\n'
               '$\\lambda$ (1/s) & $\\lambda S^{\\mathrm{miss}}$ & fluid saddle & '
               'mean time to collapse (s)\\\\\\midrule\n' + '\n'.join(rows)
               + '\n\\bottomrule\\end{tabular}}')
    rows = [f"{r['N']} & {r['saddle']} & {r['modes'][-1]} & {fmt(r['barrier_bad_to_good'], 1)} & "
            f"${sci(r['recovery_bad_to_good_s'])}$ & ${sci(r['inv_gap_s'])}$ \\\\"
            for r in res['closed_scaling']]
    out.append('\\newcommand{\\metaScalingTable}{\\begin{tabular}{rrrrrr}\\toprule\n'
               '$N$ & saddle & bad mode & barrier $\\Delta V$ & recovery (s) & $1/\\text{gap}$ (s)'
               '\\\\\\midrule\n' + '\n'.join(rows) + '\n\\bottomrule\\end{tabular}}')
    q = res['queue_enough']
    rows = [f"{T} & {fmt(v['p_bad_warm'], 3)} & {fmt(v['p_bad_cold'], 3)} & "
            f"{fmt(v['mean_q_warm'], 1)} & {fmt(v['mean_q_cold'], 1)} \\\\"
            for T, v in q['warm_vs_cold'].items()]
    out.append('\\newcommand{\\metaWarmColdTable}{\\begin{tabular}{rrrrr}\\toprule\n'
               '$t$ (s) & $\\Prob(q_t\\ge16)$ warm & cold & $\\E q_t$ warm & cold'
               '\\\\\\midrule\n' + '\n'.join(rows) + '\n\\bottomrule\\end{tabular}}')
    hy = res['closed_hysteresis']
    out.append(f"\\newcommand{{\\metaHysZlo}}{{{hy['two_modes_Z_min']:.1f}}}")
    out.append(f"\\newcommand{{\\metaHysZhi}}{{{hy['two_modes_Z_max']:.1f}}}")
    out.append(f"\\newcommand{{\\metaHysRatio}}{{{hy['ratio']:.1f}}}")
    out.append(f"\\newcommand{{\\metaStates}}{{{q['states']}}}")
    out.append(f"\\newcommand{{\\metaRecurrent}}{{{q['recurrent_states']}}}")
    out.append(f"\\newcommand{{\\metaRecurrentH}}{{{q['recurrent_max_h']}}}")
    out.append(f"\\newcommand{{\\metaMarginalDiff}}{{{q['marginal_max_abs_diff']:.0e}}}")
    out.append(f"\\newcommand{{\\metaSlowThree}}{{{q['slow_rates_3d'][0]:.5f}}}")
    out.append(f"\\newcommand{{\\metaGapOne}}{{{q['gap_1d']:.5f}}}")
    out.append(f"\\newcommand{{\\metaRecThree}}{{{q['recovery_bad_to_q1_3d_s']:.0f}}}")
    out.append(f"\\newcommand{{\\metaRecOne}}{{{q['recovery_bad_to_q1_1d_s']:.0f}}}")
    out.append(f"\\newcommand{{\\metaPBad}}{{{q['summary']['p_bad']:.2f}}}")
    rows = [f"{r['burst_s']} & {fmt(r['at_burst_end']['mean_q'], 1)} & "
            f"{fmt(r['p_bad_600s_after'], 2)} & {r['mean_time_to_q1_after_burst_s']:.0f} \\\\"
            for r in res['burst']['rows']]
    out.append('\\newcommand{\\metaBurstTable}{\\begin{tabular}{rrrr}\\toprule\n'
               'burst (s) & $\\E q$ at its end & $\\Prob(q\\ge16)$ 600\\,s later & '
               'mean time to $q\\le1$ (s)\\\\\\midrule\n' + '\n'.join(rows)
               + '\n\\bottomrule\\end{tabular}}')
    iv = res['interventions']
    by_resp = sorted(iv, key=lambda k: iv[k]['mean_response_s'])
    by_rec = sorted(iv, key=lambda k: iv[k]['recovery_from_bad_s'])
    rows = [f"{k} & {fmt(v['mean_response_s'])} & {by_resp.index(k) + 1} & "
            f"{fmt(v['p_bad'], 3)} & {v['recovery_from_bad_s']:.0f} & {by_rec.index(k) + 1} \\\\"
            for k, v in iv.items()]
    out.append('\\newcommand{\\metaInterventionTable}{\\begin{tabular}{lrrrrr}\\toprule\n'
               'arm & response (s) & rank & $\\Prob(q\\ge16)$ & recovery (s) & rank'
               '\\\\\\midrule\n' + '\n'.join(rows) + '\n\\bottomrule\\end{tabular}}')
    wc = q['warm_vs_cold']['30']
    out.append(f"\\newcommand{{\\metaWarmThirty}}{{{wc['p_bad_warm']:.3f}}}")
    out.append(f"\\newcommand{{\\metaColdThirty}}{{{wc['p_bad_cold']:.2f}}}")
    br = {r['burst_s']: r for r in res['burst']['rows']}
    out.append(f"\\newcommand{{\\metaBurstNone}}{{{br[0]['p_bad_600s_after']:.2f}}}")
    out.append(f"\\newcommand{{\\metaBurstThirty}}{{{br[30]['p_bad_600s_after']:.2f}}}")
    recs = [r['mean_time_to_q1_after_burst_s'] for b, r in br.items() if b >= 30]
    out.append(f"\\newcommand{{\\metaBurstRecLo}}{{{min(recs):.0f}}}")
    out.append(f"\\newcommand{{\\metaBurstRecHi}}{{{max(recs):.0f}}}")
    sc = res['closed_scaling']
    slope = np.polyfit([r['N'] for r in sc], [r['barrier_bad_to_good'] for r in sc], 1)[0]
    out.append(f"\\newcommand{{\\metaScalingSlope}}{{{slope:.2f}}}")
    band = [r for r in res['open'] if r['log10_time_to_collapse_from_empty_s'] is not None]
    out.append(f"\\newcommand{{\\metaOpenFirstLog}}{{{band[0]['log10_time_to_collapse_from_empty_s']:.0f}}}")
    out.append(f"\\newcommand{{\\metaOpenLastRatio}}{{{band[-1]['lam_S_miss']:g}}}")
    out.append(f"\\newcommand{{\\metaOpenLastSec}}{{{10 ** band[-1]['log10_time_to_collapse_from_empty_s']:.0f}}}")
    return '\n'.join(out) + '\n'


def main():
    if '--tex-only' in sys.argv:          # regenerate the lecture tables from the stored results
        write_tex(json.loads((ROOT / 'research/metastability-results.json').read_text()))
        return
    res = dict(
        note='CTMC numerics for lecture 7 (serQ #120); models, not measurements',
        closed_scaling=exp_closed_scaling(),
        closed_hysteresis=exp_closed_hysteresis(),
        open=exp_open(),
        queue_enough=exp_queue_enough(),
        burst=exp_burst(),
        interventions=exp_interventions(),
    )
    path = ROOT / 'research/metastability-results.json'
    path.write_text(json.dumps(res, indent=1) + '\n')
    write_tex(res)


def write_tex(res):
    (ROOT / 'lectures/queueing-serving/metastability-tables.tex').write_text(tex_tables(res))
    print('wrote lectures/queueing-serving/metastability-tables.tex')


if __name__ == '__main__':
    main()
