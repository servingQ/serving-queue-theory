#!/usr/bin/env python3
"""Check the unified course against the pinned serQ release; emit reproducible evidence.

--serq must name that release's binary. --baseline and --baseline-source are
optional: compare with the repository's previous release without requiring
that its numerical results stay identical. No serving measurements are made.
"""
import argparse
import re
import json
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ROOT / 'lectures/queueing-serving/programs'


def run(binary, path, seed, settings=()):
    cmd = [str(binary), 'run', str(path), '--seed', str(seed), '--json']
    for setting in settings:
        cmd += ['--set', setting]
    return json.loads(subprocess.check_output(cmd, text=True))


def close(value, expected, tolerance, label):
    assert abs(value - expected) <= tolerance * max(abs(expected), 1e-6), (
        f'{label}: {value} versus {expected} (relative tolerance {tolerance})')



def release_identity(binary, pinned=True):
    """The release a serq binary was built from, verified where possible.

    fetch_serq.sh writes the checked-out ref to <root>/tag next to <root>/bin/serq;
    it must equal the pin in validation/pyproject.toml. The commit is recorded
    only when the source checkout is a git repository.
    """
    pin = re.search(r'^\[tool\.serq\][^\[]*?^(?:tag|rev) = "([^"]+)"',
                    (ROOT / 'validation/pyproject.toml').read_text(), re.M | re.S)
    root = Path(binary).resolve().parent.parent
    tag_file = root / 'tag'
    ref = tag_file.read_text().strip() if tag_file.exists() else None
    commit = None
    if (root / 'src/.git').exists():
        commit = subprocess.check_output(['git', '-C', str(root / 'src'), 'rev-parse', 'HEAD'],
                                         text=True).strip()
    path = Path(binary).resolve()
    shown = str(path.relative_to(ROOT.resolve())) if path.is_relative_to(ROOT.resolve()) else path.name
    if not pinned:
        return dict(binary=shown, release=ref, commit=commit)
    return dict(binary=shown, release=ref, pinned=pin.group(1) if pin else None,
                release_verified=ref is not None and pin is not None and ref == pin.group(1),
                commit=commit)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serq', required=True, type=Path)
    ap.add_argument('--tex', type=Path, help='optional generated comparison table')
    ap.add_argument('--baseline', type=Path)
    ap.add_argument('--baseline-source', type=Path)
    ap.add_argument('--out', type=Path, default=ROOT / 'research/lecture-results.json')
    args = ap.parse_args()
    assert bool(args.baseline) == bool(args.baseline_source)
    ir = json.loads(subprocess.check_output([str(args.serq), 'ir', str(PROGRAMS / 'mg1.sq')], text=True))
    assert ir['version'] == 10, f"expected IR v10, got {ir['version']}"
    checks, comparisons = [], []
    for path in PROGRAMS.glob('*.sq'):
        if path.name.endswith('library.sq'):
            continue
        subprocess.run([str(args.serq), 'check', str(path)], check=True, capture_output=True)
    # PK: deterministic, exponential, Erlang-4, H2 at common mean 1.
    for law, m2 in [(0, 1), (1, 2), (2, 1.25), (3, 5)]:
        r = run(args.serq, PROGRAMS / 'mg1.sq', 3, [f'law={law}', 'cv2=4'])
        observed = r['observes']['wait']['mean']
        expected = .8 * m2 / (2 * (1 - .8))
        close(observed, expected, .08, f'PK law {law}')
        checks.append(dict(check=f'PK law {law}', observed=observed, expected=expected))
    # PS: three laws, same load, time-average number.
    for law in [0, 1, 3]:
        r = run(args.serq, PROGRAMS / 'ps.sq', 5, [f'law={law}'])
        observed = r['stages'][0]['mean_number']; expected = .7 / .3
        close(observed, expected, .06, f'PS law {law}')
        checks.append(dict(check=f'PS law {law}', observed=observed, expected=expected))
    for n in [2, 8, 32]:
        q = 0
        for k in range(1, n + 1):
            response = 1 + q
            throughput = k / (4 + response)
            q = throughput * response
        r = run(args.serq, PROGRAMS / 'closed.sq', 7, [f'N={n}'])
        observed = r['stages'][0]['mean_number']
        close(observed, q, .06, f'MVA N={n}')
        checks.append(dict(check=f'MVA N={n}', observed=observed, expected=q))
    # Saturated PD bottleneck including a link-limited configuration.
    for np, bw in [(10, 1000), (11, 1000), (12, 1000), (11, 10)]:
        r = run(args.serq, PROGRAMS / 'pd_tandem.sq', 3,
                ['mode=1', f'NP={np}', f'bnet={bw}'])
        observed = next(s for s in r['stages'] if s['name'] == 'decode')['throughput']
        expected = min(np * 2, 32 - np, bw)
        close(observed, expected, .03, f'PD split {np} link {bw}')
        checks.append(dict(check=f'PD split {np} link {bw}', observed=observed, expected=expected))
    for seed in [1, 2, 3]:
        r = run(args.serq, PROGRAMS / 'lecture_pd.sq', seed)
        stages = {s['name']: s for s in r['stages']}
        assert r['turns'] > 500 and stages['prefill']['utilization'] < .95
        # Work o*w with E[o]=200, w=.0002; PS min(present,16)
        # gives each job at most unit rate. This catches a capacity variable
        # accidentally resolving to a workload attribute.
        service = stages['decode']['mean_service']
        close(service, .04, .1, f'PD decode work seed {seed}')
        ttft = r['observes']['ttft']['mean']
        # TTFT starts before `hold memP`, so it includes the pool's admission wait.
        pool_wait = next(p for p in r['pools'] if p['name'] == 'memP')['mean_wait']
        expected = pool_wait + stages['prefill']['mean_wait'] + stages['prefill']['mean_service']
        close(ttft, expected, .01, f'PD TTFT seed {seed}')
        # The client's first token comes after the transfer and the decode
        # pool's admission: ttft_client = ttft + transfer + wait for memD.
        client = r['observes']['ttft_client']['mean']
        transfer = r['observes']['transfer']['mean']
        wait_d = next(p for p in r['pools'] if p['name'] == 'memD')['mean_wait']
        close(client, ttft + transfer + wait_d, .01, f'PD client TTFT seed {seed}')
        checks.append(dict(check=f'PD decode service seed {seed}', observed=service, expected=.04))
        checks.append(dict(check=f'PD TTFT seed {seed}', observed=ttft, expected=expected))
        checks.append(dict(check=f'PD client TTFT seed {seed}', observed=client,
                           expected=ttft + transfer + wait_d))
        if args.baseline:
            old = run(args.baseline, args.baseline_source / 'lecture_pd.seq', seed)
            comparisons.append(dict(seed=seed,
                baseline={k: old['observes'][k]['mean'] for k in ['ttft', 'response', 'miss']},
                current={k: r['observes'][k]['mean'] for k in ['ttft', 'response', 'miss']},
                baseline_decode=next(s for s in old['stages'] if s['name']=='decode')['mean_service'],
                current_decode=service))
    # Step-engine price: effective FIFO approximation, not an exact theorem
    # about the engine. Full-prompt admission gate and unlimited KV are held
    # fixed to isolate the change of runtime.
    a, b, omega = 1.94e-4, 6.51e-9, .057
    work = lambda n: a*n+b*n*n/2
    lam = .6 / (.8*work(512)+.2*work(5120))
    base = run(args.serq, PROGRAMS / 'price.sq', 1, [f'Lambda={lam}'])
    changed = run(args.serq, PROGRAMS / 'price.sq', 1, [f'Lambda={lam}', 'delta=.01'])
    obs = lambda r,k: r['observes'][k]['mean']
    ld = lam*(obs(base,'response')-obs(base,'ttft'))
    avail = 1-ld/math.floor(omega/a)
    sh, sm = work(512)/avail, work(5120)/avail
    mean, m2 = .8*sh+.2*sm, .8*sh*sh+.2*sm*sm
    rho=lam*mean; w=lam*m2/(2*(1-rho))
    phi=sm-sh+lam*(sm*sm-sh*sh)/(2*(1-rho))+lam*w*(sm-sh)/(1-rho)
    lo=lam*.01*phi; hi=lo*(1-rho)/(1-rho-lam*.01*(sm-sh))
    rise=lam*(obs(changed,'ttft')-obs(base,'ttft'))
    # Finite-run differences need a margin; the record exposes both ends.
    assert lo*.9 <= rise <= hi*1.1, f'step price {rise}, bracket [{lo}, {hi}]'
    new_ld=lam*(obs(changed,'response')-obs(changed,'ttft'))
    assert abs(new_ld-ld)/ld < .01, f'decode changed {ld} -> {new_ld}'
    checks.append(dict(check='step-engine miss-price approximation', observed=rise,
                       lower=lo, upper=hi, decode_relative_change=(new_ld-ld)/ld))
    # Recompute the course's nonlinear feedback example, independent of
    # interpreter ordering or random streams; bisection resolves all roots.
    def feedback(h, lam):
        mean = 5 - 4.5*h
        if lam*mean >= 1:
            return 0
        wait = lam*(25 - 24.75*h)/(2*(1-lam*mean))
        return math.exp(-(7+wait)/60)
    roots = {}
    for lam in [.25, .18]:
        found = [0.] if feedback(0, lam)==0 else []
        for i in range(10000):
            lo, hi = i/10000, (i+1)/10000
            if (feedback(lo,lam)-lo)*(feedback(hi,lam)-hi)<0:
                for _ in range(50):
                    mid=(lo+hi)/2
                    if (feedback(lo,lam)-lo)*(feedback(mid,lam)-mid)<=0: hi=mid
                    else: lo=mid
                found.append((lo+hi)/2)
        roots[str(lam)]=found
    assert len(roots['0.25'])==3 and len(roots['0.18'])==1
    for value, expected in zip(roots['0.25'], [0, .250, .882]):
        close(value, expected, .01, 'feedback roots .25')
    close(roots['0.18'][0], .885, .01, 'feedback roots .18')
    current = release_identity(args.serq)
    assert current['release_verified'], (
        f"serq at {args.serq} is {current['release']!r}, pinned {current['pinned']!r}; "
        "build it with scripts/fetch_serq.sh, which records the release in .serq/tag")
    result = dict(**current, ir_version=ir['version'], checks=checks,
                  baseline=release_identity(args.baseline, pinned=False) if args.baseline else None,
                  baseline_comparison=comparisons, feedback_roots=roots)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    if args.tex:
        rows = [r'\begin{center}\small', r'\begin{tabular}{@{}lrr@{}}',
                r'\toprule', rf'Metric (seconds) & Previous runtime & serQ {current["release"]} \\', r'\midrule']
        if comparisons:
            for key, label in [('ttft','TTFT'), ('response','Turn response')]:
                before = sum(c['baseline'][key] for c in comparisons)/len(comparisons)
                after = sum(c['current'][key] for c in comparisons)/len(comparisons)
                rows.append(f'{label} & {before:.5f} & {after:.5f} '+r'\\')
            before = sum(c['baseline_decode'] for c in comparisons)/len(comparisons)
            after = sum(c['current_decode'] for c in comparisons)/len(comparisons)
            rows.append(f'Decode service & {before:.5f} & {after:.5f} '+r'\\')
        rows += [r'\bottomrule', r'\end{tabular}', r'\end{center}']
        args.tex.write_text('\n'.join(rows)+'\n')
    print(f'OK: {len(checks)} lecture checks; feedback roots verified; {len(comparisons)} baseline comparisons')


if __name__ == '__main__':
    main()
