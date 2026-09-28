# Trace analysis: what real agent traces say about the formulation

Status 2026-09-23. Two trace sets, two scripts, one generated directory
(`paper/traces/`, `\input` by the paper; never typed by hand).

| Corpus | Source | Sessions | Requests | What it has | Script |
|---|---|---|---|---|---|
| cc-traces-weka | HF `semianalysisai/cc-traces-weka-061326` (SemiAnalysis Claude Code proxy, v7, Jun 2026); production, interactive, Claude models | 183 | 26,439 main-agent (+652 sub-agent groups) | per request: `t`, `in` (64-token blocks), `out`, prefix-block `hash_ids`, `api_time`, measured `ttft`, `think_time` | `scripts/trace_stats_weka.py` |
| harbor SWE-bench Pro | `/mnt/shared_data/groups/fsw_serv/harbor-trajectory/swebenchpro__claude-code` (our runs: Claude Code 2.1.220 → MiniMax-M2.5 via gateway) | 99 | ~1,600 main-agent LLM calls | per step: timestamp, prompt/completion tokens (cache fields are zero: the gateway does not report them) | `scripts/trace_stats_harbor.py` |

Regenerate with `make traces` (set `WEKA=` to the downloaded `traces.jsonl`;
the file is 805 MB and is not in the repo).

## Definitions

- **Hit / append.** Weka: for request `t`, hit blocks = longest prefix of
  `hash_ids` already held by an earlier request of the same session (a
  perfect, never-evicting cache); `n_t = in_t − 64·hit_t`. Harbor: no
  hashes, so `n_t = K_t − K_{t−1} − o_{t−1}` (assumes the whole previous
  prompt plus completion is reused).
- **Prefill work.** `P(n,K) = a n + b n (K + n/2)` in units of `a`, with the
  crossover context `K_c = a/b` (context at which attention work equals
  dense work) swept over ∞ (linear only), 100K, 30K, 10K.
- **Mixture CV².** For turns ≥ 2, hit work `P(n, K−n)`, miss work `P(K, 0)`;
  at hit rate `p` the variance splits by the law of total variance into
  *within* (`p·Var[hit] + (1−p)·Var[miss]`, the spread of appends and
  contexts) and *between* (`p(1−p)(E[miss]−E[hit])²`, the hit/miss
  mixture). "Observed reuse" / "all hit" = `p = 1`.

## Results (2026-09-23)

### Workload (Weka, turns ≥ 2)

| | median | mean | p90 | CV² |
|---|---|---|---|---|
| turns per session | 58 | 144 | 289 | 4.5 |
| context K (tokens) | 207K | 275K | 601K | 0.60 |
| appended tokens n | 1,344 | 3,413 | 5,056 (p99 37.8K) | 32.0 |
| output tokens o | 501 | 1,132 | 2,795 | 2.8 |
| think time (tool + user, s) | 3.8 | 214 | 88 (p99 1,989) | 304 |
| TTFT at the proxy (s) | 3.54 | 4.64 | 8.24 (p99 24.6) | 0.95 |

- Token-weighted prefix hit under a perfect cache: **98.8 %**; 95 % of
  requests reuse ≥ 90 % of their prompt; **2.1 % reuse < 50 %** (context
  compactions: the workload's own misses).
- Sub-agents: 3.6 groups per session, 28 inner requests per group.
- Resident KV: `E[∫K dt] / (E[D]·E[K]) = 1.15`, `corr(D, mean K) = 0.57`.
  The naive M/G/∞ estimate is 15 % low, as §2.1 predicts when long
  sessions carry long contexts.
- TPOT proxy `(api_time − ttft)/out`: median 10 ms, p90 16 ms.

### Workload (harbor SWE-bench Pro, Claude Code → MiniMax-M2.5)

turns/session median 16 (max 37); context median 30K (max 91K); append
median 259, mean 1,111, CV² 6.8; output median 97; inter-call gap median
83 s, CV² 0.66 (no human in the loop); reuse under perfect caching 96.6 %;
`E[∫K dt]/(E[D]E[K]) = 0.98`, `corr = 0.23` (fixed-length benchmark tasks:
no lifetime–size correlation). Other harbor sets (swebench-verified,
terminal-bench-2 with Claude Code) give append CV² 4.0 and 13.1, reuse
98.5 % and 98.3 %.

### Prefill-work CV² and the mixture's share

Weka, turns ≥ 2, `p` = hit rate, share = between-variance / total:

| K_c | miss/hit | CV² observed reuse | p = 0.90 | p = 0.96 | p = 0.99 |
|---|---|---|---|---|---|
| ∞ | 81 | 32.0 | 12.3 (58 %) | 24.5 (57 %) | 41.3 (47 %) |
| 100K | 78 | 55.3 | 20.1 (35 %) | 39.3 (35 %) | 66.1 (28 %) |
| 30K | 78 | 64.4 | 23.0 (31 %) | 45.0 (30 %) | 75.6 (25 %) |
| 10K | 77 | 68.3 | 24.3 (29 %) | 47.5 (29 %) | 79.7 (23 %) |

Harbor SWE-bench Pro: observed-reuse CV² 6.8 (linear), miss/hit 29; at
p = 0.96 CV² 9.2 with mixture share 73 % (linear) / 67 % (K_c = 100K).

Reading: CV² is not monotone in `p` because forcing misses raises the mean
faster than the variance; what the PK wait needs is `E[S²]` and `ρ`, both
of which rise with misses. The point for the paper is the *split*: even at
a 96 % hit rate the mixture is only about half of `Var[S]` in production
traces (and less under an attention-heavy cost model), because the append
itself has CV² 32. The §2.3 claim "if every turn hit, E[S²] ≈ E[S]²" was
false for these workloads and has been rewritten: variance has two
sources, the append (not controllable) and the mixture (the policy's
lever).

### TTFT at the proxy vs the append

| appended tokens n | requests | TTFT median (s) | TTFT p90 (s) |
|---|---|---|---|
| < 1K | 11,100 | 4.06 | 8.76 |
| 1–4K | 11,857 | 3.02 | 7.44 |
| 4–16K | 2,676 | 3.70 | 8.59 |
| 16–64K | 497 | 3.82 | 9.28 |
| ≥ 64K | 126 | 5.26 | 15.86 |

log–log R² of TTFT on n: 0.01 (slope −0.04); on K: 0.06. On this
production stack, at a hit rate near one, TTFT is **not** explained by the
append or the context; only appends above 64K tokens lift the tail. A
median TTFT of 3.5 s for a 1K append onto a 250K cached prefix is far
above any prefill time, so the proxy's TTFT is dominated by things the
trace does not record (queueing, cache-tier loads, routing, proxy
overhead). This neither confirms nor refutes `prop:price`: the load and
the queue are unobserved. It does say that E2 must control the load and
observe the queue directly, and that in the all-hit regime the append is
not what moves TTFT.

## What went into the paper

- §2.1: the resident-KV ratio 1.15 and corr 0.57 (`\wkKvRatio`, `\wkCorrDK`).
- §2.3: rewritten "where the variance comes from" (two sources; `\wkCvN`,
  `\wkMixShareLin`).
- §4.2 "What the traces say" + Table `tab:traces` (workload + TTFT by
  append); E2 hypothesis now about the mixture's *share* growing under
  eviction; Limitations paragraph.
- Bib: `cc-traces-weka` (verified against the dataset README and file).

## Caveats

- Both corpora are Claude Code. Other harnesses (OpenHands, terminus,
  mini-swe-agent are in the harbor directory but use different log
  layouts) are not analysed yet.
- Weka think time includes the human; harbor gaps include decode and
  client time (no server-side timestamps).
- Harbor cache fields are zero, so its hit/miss is assumed, not observed.
- The cost-model sweep replaces calibration (E1); the linear column is the
  most favourable to the mixture.
- The Weka `in` field is a block count (multiple of 64) and can overcount
  in the heavy cache-write tail (dataset README); requests above 990,016
  tokens were removed by the dataset authors.

## Harness comparison (2026-09-24)

`scripts/trace_stats_harbor.py` on the other SWE-bench Pro harnesses
(openhands-sdk has no ATIF trajectory.json for most trials and is skipped):

| Harness (SWE-bench Pro, MiniMax-M2.5) | sessions | turns median | context median | append median / CV² | reuse | gap median / CV² |
|---|---|---|---|---|---|---|
| claude-code | 99 | 16 | 30K | 259 / 6.8 | 96.6 % | 83 s / 0.66 |
| terminus-2 | 100 | 65 | 27K | 146 / 2.3 | 98.9 % | 14 s / 4.7 |
| mini-swe-agent | 83 | 40 | 21K | 280 / 1.9 | 97.2 % | 18 s / 2.7 |

Append variance is a harness property (Claude Code's tool outputs and
sub-agent results are the largest); reuse is not (97–99 % everywhere).
Resume probability in the production corpus: 0.85–0.99 by turn index or
preceding gap; expected next gap 4–65 s (table `tab-weka-resume.tex`).

## Replay in the simulator (2026-09-24)

`scripts/trace_stats_weka.py --export-csv` writes `libqueuingsim/data/weka-sessions.csv`
(main-agent requests, sessions split at gaps > 600 s: 761 sessions, 26,395
turns, mean 34.7 turns, mean think 22.7 s, mean final context 391k).
`libqueuingsim::workload::TraceCorpus` loads it and `BatchConfig::trace`
replays one real session per Poisson arrival. Results in paper §4.1
(`tab:sim-trace`, generated): appends alone give CV² 35–43; a tight
admission cap keeps hits ≥ 0.80 with the mixture at 38–75 % of Var[S]; a
loose cap thrashes; PK from measured moments overstates the observed
prefill wait 4–20× because 2–24 live sessions are a finite population.
Block eviction changed nothing beyond seed noise. Cost model: `a = 2e-5`,
`b = 4e-10` (`K_c = 50k`, dense-70B order), `β = 2e-9`, `ω = 2e-4`.

## Next

- Add the other harbor harnesses (parse their own formats) to see whether
  append CV² and reuse are harness properties.
- Forced-miss injection on the replayed workload (the `prop:price` bracket
  with real appends) and a finite-population correction of PK.
- E1 calibration turns the `K_c` sweep into one column.
