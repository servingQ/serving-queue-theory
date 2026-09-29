#!/usr/bin/env python3
"""Workload and TTFT statistics from a WekaTrace corpus of Claude Code
proxy traces (HF dataset `semianalysisai/cc-traces-weka-061326`).

Each row is one session: `requests` in time order; main-agent requests
(type `s`) carry `t` (s), `in` (prompt tokens, 64-token blocks), `out`,
`hash_ids` (prefix-block hashes, session-local), `api_time`, `ttft`
(measured at the proxy) and `think_time` (gap since the previous request
ended: tool execution plus client time).  Sub-agent groups (type
`subagent`) nest their inner requests (type `n`).

Reported, for the paper's formulation (§2) and E2 (§4.2):

* turns per session, sub-agent fan-out;
* observed prefix reuse: for request t, the hit is the longest prefix of
  `hash_ids` whose blocks an earlier request of the session already held
  (a perfect, never-evicting cache); n_t = in_t - 64·hit_t is the append;
* think time (τ_i proxy), output tokens, decode time and TPOT;
* measured TTFT by new-token bin, and the share of log-TTFT variance the
  new-token count explains (the serving stack behind the proxy is unknown,
  so TTFT here is an observation, not a controlled measurement);
* the resident-KV integral ∫K(t)dt vs the naive E[D]E[K] (§2.1);
* prefill-work CV² under P(n,K) = a n + b n (K + n/2) for a sweep of the
  crossover context K_c = a/b, with the observed reuse ("all hit") and
  with forced misses at hit rates p (Eq. cv2), split into the share from
  the mixture vs from the spread of the appends.

Usage: scripts/trace_stats_weka.py traces.jsonl [--tex OUTDIR] [--label weka]
"""
import argparse
import collections
import json
import math
import os
import statistics as st


def q(xs, p):
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))
    return xs[i]


def cv2(xs):
    m = st.fmean(xs)
    return st.pvariance(xs) / (m * m)


def work(n, K, Kc):
    return n + (0.0 if math.isinf(Kc) else n * (K + n / 2) / Kc)


def load(path):
    sessions = []
    for line in open(path):
        r = json.loads(line)
        bs = r.get('block_size', 64)
        seen = set()
        turns = []
        groups = 0
        inner = 0
        for req in r['requests']:
            if req.get('type') == 'subagent':
                groups += 1
                inner += len(req.get('requests', []))
                continue
            if req.get('type') != 's':
                continue
            ids = req['hash_ids']
            hit = 0
            for h in ids:
                if h in seen:
                    hit += 1
                else:
                    break
            seen.update(ids)
            K = req['in']
            n = max(K - bs * hit, 0)
            turns.append(dict(t=req['t'], K=K, n=n, o=req['out'], api=req['api_time'],
                              ttft=req.get('ttft'), think=req.get('think_time'), hitfrac=(bs * hit) / K if K else 0.0))
        if len(turns) >= 2:
            sessions.append(dict(id=r['id'], turns=turns, groups=groups, inner=inner))
    return sessions


def mixture(S, Kc, p):
    hits, misses = [], []
    for s in S:
        for u in s['turns'][1:]:
            hits.append(work(u['n'], u['K'] - u['n'], Kc))
            misses.append(work(u['K'], 0, Kc))
    mh, mm = st.fmean(hits), st.fmean(misses)
    vh, vm = st.pvariance(hits), st.pvariance(misses)
    mean = p * mh + (1 - p) * mm
    within = p * vh + (1 - p) * vm
    between = p * (1 - p) * (mm - mh) ** 2
    var = within + between
    return dict(cv2=var / mean ** 2, share=between / var, cv2_hit=vh / mh ** 2, ratio=mm / mh)


def r2_log(x, y):
    lx = [math.log(a) for a in x]
    ly = [math.log(b) for b in y]
    mx, my = st.fmean(lx), st.fmean(ly)
    sxy = sum((a - mx) * (b - my) for a, b in zip(lx, ly))
    sxx = sum((a - mx) ** 2 for a in lx)
    syy = sum((b - my) ** 2 for b in ly)
    return sxy * sxy / (sxx * syy), sxy / sxx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('traces')
    ap.add_argument('--tex')
    ap.add_argument('--label', default='weka')
    ap.add_argument('--export-csv', help='write per-turn sessions (session,turn,new,out,think) for validation replay')
    ap.add_argument('--split-gap', type=float, default=600.0,
                    help='export only: start a new session after a gap longer than this many seconds (user walked away)')
    a = ap.parse_args()
    S = load(a.traces)
    if a.export_csv:
        export_csv(S, a.export_csv, a.split_gap)
    T = [u for s in S for u in s['turns']]
    T2 = [u for s in S for u in s['turns'][1:]]
    print(f'{len(S)} sessions, {len(T)} main-agent requests')
    turns = [len(s['turns']) for s in S]
    print(f"turns/session: median {q(turns, .5)} mean {st.fmean(turns):.0f} p90 {q(turns, .9)} max {max(turns)}; CV² {cv2(turns):.2f}")
    print(f"sub-agent groups/session: mean {st.fmean([s['groups'] for s in S]):.1f}; inner requests/group: {sum(s['inner'] for s in S) / max(1, sum(s['groups'] for s in S)):.1f}")
    K = [u['K'] for u in T2]
    n = [u['n'] for u in T2]
    o = [u['o'] for u in T]
    think = [u['think'] for u in T2 if u['think'] is not None]
    ttft = [u['ttft'] for u in T2 if u['ttft'] is not None and u['ttft'] > 0]
    hitfrac = [u['hitfrac'] for u in T2]
    print(f"context K (turn ≥ 2): median {q(K, .5):,} p90 {q(K, .9):,} max {max(K):,}")
    print(f"observed reuse: token-weighted prefix hit {1 - sum(n) / sum(K):.3f}; requests with hit ≥ 90% of prompt: {st.fmean(h >= .9 for h in hitfrac):.3f}; with hit < 50%: {st.fmean(h < .5 for h in hitfrac):.3f}")
    print(f"new tokens n (turn ≥ 2): median {q(n, .5):,} mean {st.fmean(n):,.0f} p90 {q(n, .9):,} p99 {q(n, .99):,}; CV² {cv2(n):.2f}")
    print(f"output tokens o: median {q(o, .5)} mean {st.fmean(o):.0f} p90 {q(o, .9)}; CV² {cv2(o):.2f}")
    print(f"think time (s): median {q(think, .5):.1f} mean {st.fmean(think):.1f} p90 {q(think, .9):.1f} p99 {q(think, .99):.1f}; CV² {cv2(think):.2f}; share > 60 s: {st.fmean(x > 60 for x in think):.3f}")
    dec = [(u['api'] - u['ttft']) / u['o'] for u in T if u['ttft'] and u['o'] > 0 and u['api'] > u['ttft']]
    print(f"TPOT proxy (s/token): median {q(dec, .5):.3f} p90 {q(dec, .9):.3f}")
    print(f"TTFT (s): median {q(ttft, .5):.2f} mean {st.fmean(ttft):.2f} p90 {q(ttft, .9):.2f} p99 {q(ttft, .99):.2f}; CV² {cv2(ttft):.2f}")
    bins = [(0, 1024), (1024, 4096), (4096, 16384), (16384, 65536), (65536, 10 ** 9)]
    print('TTFT by new tokens n (turn ≥ 2):')
    brows = []
    for lo, hi in bins:
        xs = [u['ttft'] for u in T2 if lo <= u['n'] < hi and u['ttft'] and u['ttft'] > 0]
        if xs:
            row = (lo, hi, len(xs), q(xs, .5), q(xs, .9), st.fmean([u['K'] for u in T2 if lo <= u['n'] < hi]))
            brows.append(row)
            print(f"  n in [{lo:>6,}, {hi if hi < 10**9 else 'inf':>7}): {len(xs):6d} req  median {q(xs, .5):5.2f}  p90 {q(xs, .9):5.2f}  (mean K {row[5]:,.0f})")
    pairs = [(u['n'], u['ttft']) for u in T2 if u['n'] > 0 and u['ttft'] and u['ttft'] > 0]
    r2n, slope_n = r2_log(*zip(*pairs))
    pairsK = [(u['K'], u['ttft']) for u in T2 if u['ttft'] and u['ttft'] > 0]
    r2K, _ = r2_log(*zip(*pairsK))
    print(f"log-log R²: TTFT vs n = {r2n:.2f} (slope {slope_n:.2f}); TTFT vs K = {r2K:.2f}")
    # resident KV integral
    kv_int, D, meanK = [], [], []
    for s in S:
        ts = s['turns']
        integ = sum(ts[i]['K'] * (ts[i + 1]['t'] - ts[i]['t']) for i in range(len(ts) - 1))
        kv_int.append(integ)
        D.append(ts[-1]['t'] + ts[-1]['api'] - ts[0]['t'])
        meanK.append(st.fmean(u['K'] for u in ts))
    naive = st.fmean(D) * st.fmean([u['K'] for u in T])
    exact = st.fmean(kv_int)
    print(f"session length D (s): median {q(D, .5):.0f} mean {st.fmean(D):.0f}")
    print(f"resident KV: E[∫K dt] = {exact:,.0f} token·s vs naive E[D]E[K] = {naive:,.0f} (ratio {exact / naive:.2f}); corr(D, mean K) = {corr(D, meanK):.2f}")
    print('\nprefill-work CV² (turns ≥ 2): observed reuse ("all hit") and with forced misses at hit rate p')
    rows = []
    for Kc in (float('inf'), 100_000, 30_000, 10_000):
        r = [mixture(S, Kc, p) for p in (0.90, 0.96, 0.99)]
        kc = '∞' if math.isinf(Kc) else f'{Kc:,}'
        print(f"  K_c={kc:>8} miss/hit {r[0]['ratio']:5.1f}  CV² all-hit {r[0]['cv2_hit']:6.2f}  " + '  '.join(f"p={p:.2f}: {x['cv2']:6.2f} (mix {x['share']:.2f})" for p, x in zip((0.90, 0.96, 0.99), r)))
        rows.append((kc, r))
    if a.tex:
        os.makedirs(a.tex, exist_ok=True)
        L = a.label
        hdr = f'% generated by scripts/trace_stats_weka.py from {os.path.basename(a.traces)}; do not edit\n'
        with open(os.path.join(a.tex, f'tab-{L}-workload.tex'), 'w') as f:
            f.write(hdr + '\\begin{tabular}{@{}lrrrr@{}}\n\\toprule\n & median & mean & p90 & $\\mathrm{CV}^2$ \\\\\n\\midrule\n')
            for name, xs, fmt in (('turns per session', turns, '{:.0f}'), ('context $K$ (tokens)', K, '{:,.0f}'),
                                  ('appended tokens $n$', n, '{:,.0f}'), ('output tokens $o$', o, '{:,.0f}'),
                                  ('think time (s)', think, '{:.1f}'), ('TTFT (s)', ttft, '{:.2f}')):
                f.write(f"{name} & {fmt.format(q(xs, .5))} & {fmt.format(st.fmean(xs))} & {fmt.format(q(xs, .9))} & {cv2(xs):.2f} \\\\\n".replace(',', '\\,'))
            f.write('\\bottomrule\n\\end{tabular}\n')
        with open(os.path.join(a.tex, f'tab-{L}-ttft.tex'), 'w') as f:
            f.write(hdr + '\\begin{tabular}{@{}lrrr@{}}\n\\toprule\nappended tokens $n$ & requests & TTFT median (s) & p90 (s) \\\\\n\\midrule\n')
            for lo, hi, cnt, med, p90, _ in brows:
                rng = f'$<{hi // 1024}$K' if lo == 0 else (f'$\\ge{lo // 1024}$K' if hi >= 10 ** 9 else f'{lo // 1024}--{hi // 1024}K')
                f.write(f"{rng} & {cnt:,} & {med:.2f} & {p90:.2f} \\\\\n".replace(',', '\\,'))
            f.write('\\bottomrule\n\\end{tabular}\n')
        with open(os.path.join(a.tex, f'tab-{L}-cv2.tex'), 'w') as f:
            f.write(hdr + '\\begin{tabular}{@{}rrrrrr@{}}\n\\toprule\n$K_c$ & miss/hit & all hit & $h{=}0.90$ & $h{=}0.96$ & $h{=}0.99$ \\\\\n\\midrule\n')
            for kc, r in rows:
                kcs = '$\\infty$' if kc == '∞' else (kc.replace(',000', 'k'))
                f.write(f"{kcs} & {r[0]['ratio']:.0f} & {r[0]['cv2_hit']:.0f} & " + ' & '.join(f"{x['cv2']:.0f} ({100 * x['share']:.0f})" for x in r) + ' \\\\\n')
            f.write('\\bottomrule\n\\end{tabular}\n')
        with open(os.path.join(a.tex, f'macros-{L}.tex'), 'w') as f:
            f.write(hdr)
            f.write(f"\\newcommand{{\\wkSessions}}{{{len(S)}}}\n\\newcommand{{\\wkRequests}}{{{len(T):,}}}\n".replace(',', '\\,'))
            f.write(f"\\newcommand{{\\wkReuse}}{{{100 * (1 - sum(n) / sum(K)):.1f}}}\n")
            f.write(f"\\newcommand{{\\wkHitNinety}}{{{100 * st.fmean(h >= .9 for h in hitfrac):.0f}}}\n")
            f.write(f"\\newcommand{{\\wkResetShare}}{{{100 * st.fmean(h < .5 for h in hitfrac):.1f}}}\n")
            f.write(f"\\newcommand{{\\wkCvN}}{{{cv2(n):.1f}}}\n\\newcommand{{\\wkCvTtft}}{{{cv2(ttft):.1f}}}\n")
            f.write(f"\\newcommand{{\\wkRtwoN}}{{{r2n:.2f}}}\n\\newcommand{{\\wkRtwoK}}{{{r2K:.2f}}}\n")
            f.write(f"\\newcommand{{\\wkKvRatio}}{{{exact / naive:.2f}}}\n\\newcommand{{\\wkCorrDK}}{{{corr(D, meanK):.2f}}}\n")
            f.write(f"\\newcommand{{\\wkThinkLong}}{{{100 * st.fmean(x > 60 for x in think):.0f}}}\n")
            f.write(f"\\newcommand{{\\wkCvHitLin}}{{{rows[0][1][0]['cv2_hit']:.1f}}}\n")
            f.write(f"\\newcommand{{\\wkMixShareLin}}{{{100 * rows[0][1][1]['share']:.0f}}}\n")
            f.write(f"\\newcommand{{\\wkCvMixLin}}{{{rows[0][1][1]['cv2']:.1f}}}\n")
            lin = [100 * x['share'] for x in rows[0][1]]
            att = [100 * x['share'] for kc, r in rows[1:] for x in r]
            f.write(f"\\newcommand{{\\wkMixLinMin}}{{{min(lin):.0f}}}\n\\newcommand{{\\wkMixLinMax}}{{{max(lin):.0f}}}\n")
            f.write(f"\\newcommand{{\\wkMixAttMin}}{{{min(att):.0f}}}\n\\newcommand{{\\wkMixAttMax}}{{{max(att):.0f}}}\n")
            f.write(f"\\newcommand{{\\wkAppendShareMin}}{{{100 - max(lin + att):.0f}}}\n")
            f.write(f"\\newcommand{{\\wkTurnsMedian}}{{{q(turns, .5)}}}\n")
            f.write(f"\\newcommand{{\\wkContextMedian}}{{{q(K, .5) / 1000:.0f}}}\n")
            f.write(f"\\newcommand{{\\wkThinkMedian}}{{{q(think, .5):.1f}}}\n\\newcommand{{\\wkThinkPninety}}{{{q(think, .9):.0f}}}\n")
        print('wrote tables to', a.tex)
    resume_stats(S, a.split_gap, a.tex, a.label)


def export_csv(S, path, split_gap):
    """Per-turn replay file. `new` is the append (turn 1: the whole prompt),
    `out` the output tokens, `think` the gap *after* the turn before the
    next one (0 on a session's last turn). A gap above `split_gap` ends the
    session: the user walked away, and the next request starts a new
    session whose first turn prefills its whole prompt."""
    rows = []
    sid = 0
    for s in S:
        turns = s['turns']
        cur = []
        def flush():
            nonlocal sid
            if len(cur) >= 2:
                for i, (new, out, think) in enumerate(cur):
                    rows.append(f'{sid},{i + 1},{new},{out},{think:.3f}')
                sid += 1
        for i, u in enumerate(turns):
            gap = (turns[i + 1]['think'] or 0.0) if i + 1 < len(turns) else 0.0
            new = u['K'] if not cur else u['n']
            if gap > split_gap or i + 1 == len(turns):
                cur.append((new, u['o'], 0.0))
                flush()
                cur = []
            else:
                cur.append((new, u['o'], gap))
        if cur:
            flush()
    with open(path, 'w') as f:
        f.write('# generated by scripts/trace_stats_weka.py --export-csv from semianalysisai/cc-traces-weka-061326;\n')
        f.write(f'# main-agent requests only; sessions split at gaps > {split_gap:.0f} s; think = gap after the turn (s)\n')
        f.write('session,turn,new,out,think\n')
        f.write('\n'.join(rows) + '\n')
    print(f'exported {sid} sessions, {len(rows)} turns to {path}')


def resume_stats(S, split_gap, tex, label):
    """p_i and tau_i as a scheduler could estimate them: the probability that a
    turn is followed by another one (within `split_gap`) and the mean gap
    before that next turn, by turn index and by the length of the gap that
    preceded the turn. Also the first-turn context of the replayed sessions
    (whole prompt of a genuinely new session, or of a split continuation)."""
    by_turn = collections.defaultdict(lambda: [0, 0, []])
    by_gap = collections.defaultdict(lambda: [0, 0, []])
    turn_bins = [(1, 1), (2, 5), (6, 20), (21, 50), (51, 10 ** 9)]
    gap_bins = [(0, 2), (2, 10), (10, 60), (60, split_gap)]
    first_ctx_new, first_ctx_split = [], []
    for s in S:
        ts = s['turns']
        first_ctx_new.append(ts[0]['K'])
        for i, u in enumerate(ts):
            nxt = ts[i + 1]['think'] if i + 1 < len(ts) else None
            cont = nxt is not None and nxt <= split_gap
            if nxt is not None and nxt > split_gap:
                first_ctx_split.append(ts[i + 1]['K'])
            tb = next(b for b in turn_bins if b[0] <= i + 1 <= b[1])
            rec = by_turn[tb]
            rec[0] += 1
            rec[1] += cont
            if cont:
                rec[2].append(nxt)
            prev = u['think'] if i > 0 else None
            if prev is not None and prev <= split_gap:
                gb = next(b for b in gap_bins if b[0] <= prev < b[1])
                rec = by_gap[gb]
                rec[0] += 1
                rec[1] += cont
                if cont:
                    rec[2].append(nxt)
    print(f'\nresume probability p (another turn within {split_gap:.0f} s) and mean next gap tau (s):')
    rows_t, rows_g = [], []
    for b in turn_bins:
        n, k, g = by_turn[b]
        if n:
            lbl = f'turn {b[0]}' if b[0] == b[1] else (f'turn $\\ge$ {b[0]}' if b[1] >= 10 ** 9 else f'turns {b[0]}--{b[1]}')
            rows_t.append((lbl, n, k / n, st.fmean(g) if g else float('nan'), q(g, .5) if g else float('nan')))
            print(f'  {lbl:>16}: n {n:6d}  p {k / n:.3f}  tau mean {rows_t[-1][3]:.1f} median {rows_t[-1][4]:.1f}')
    for b in gap_bins:
        n, k, g = by_gap[b]
        if n:
            lbl = f'gap {b[0]:.0f}--{b[1]:.0f}\\,s'
            rows_g.append((lbl, n, k / n, st.fmean(g) if g else float('nan'), q(g, .5) if g else float('nan')))
            print(f'  {lbl:>16}: n {n:6d}  p {k / n:.3f}  tau mean {rows_g[-1][3]:.1f} median {rows_g[-1][4]:.1f}')
    print(f'first-turn context: new sessions median {q(first_ctx_new, .5):,} ; split continuations median {q(first_ctx_split, .5):,} (n={len(first_ctx_split)})')
    if tex:
        with open(os.path.join(tex, f'tab-{label}-resume.tex'), 'w') as f:
            f.write('% generated by scripts/trace_stats_weka.py; do not edit\n')
            f.write('\\begin{tabular}{@{}lrrrr@{}}\n\\toprule\n & turns & $p$ & $\\tau$ mean (s) & $\\tau$ median (s) \\\\\n\\midrule\n')
            for lbl, n, pp, tm, tmed in rows_t + rows_g:
                line = f"{lbl} & {n:,} & {pp:.2f} & {tm:.0f} & {tmed:.1f} \\\\\n".replace(f"{n:,}", f"{n:,}".replace(',', '\\,'))
                f.write(line.replace('\\\\,s', '\\,s'))  # the label's thin space, not a double backslash
            f.write('\\bottomrule\n\\end{tabular}\n')
        ps = [r[2] for r in rows_t + rows_g]
        taus = [r[3] for r in rows_t + rows_g]
        with open(os.path.join(tex, f'macros-{label}.tex'), 'a') as f:
            f.write(f"\\newcommand{{\\wkPmin}}{{{min(ps):.2f}}}\n\\newcommand{{\\wkPmax}}{{{max(ps):.2f}}}\n")
            f.write(f"\\newcommand{{\\wkTauMin}}{{{min(taus):.0f}}}\n\\newcommand{{\\wkTauMax}}{{{max(taus):.0f}}}\n")
            f.write(f"\\newcommand{{\\wkFirstCtxNew}}{{{q(first_ctx_new, .5) / 1000:.0f}}}\n")
            f.write(f"\\newcommand{{\\wkFirstCtxSplit}}{{{q(first_ctx_split, .5) / 1000:.0f}}}\n")
            f.write(f"\\newcommand{{\\wkSplitShare}}{{{100 * len(first_ctx_split) / (len(first_ctx_split) + len(first_ctx_new)):.0f}}}\n")


def corr(x, y):
    mx, my = st.fmean(x), st.fmean(y)
    sx, sy = st.pstdev(x), st.pstdev(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) * sx * sy)


if __name__ == '__main__':
    main()
