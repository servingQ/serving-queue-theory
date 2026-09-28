# NPU testbed (MiniMax-M2.7, DP4 + EP): cost fit, long- and short-context replays

Status as of 2026-09-26. Experiment names: cost fit (was E1), long-context
replay (E2), short-context replay and price test (E2b); the codes survive
in directory and macro names only. A GPU (A100) testbed is next; see
`research/research-plan.md` §0 and `scripts/exp/serve_gpu.sh`. This file records how the measurement server is
launched and every configuration that did not work, so nobody re-runs the
bisection.

## Target configuration (user request)

| Item | Value |
|------|-------|
| Model | `MiniMaxAI/MiniMax-M2.7` (fp8 checkpoint, W8A16 on RBLN) |
| Parallelism | `--data-parallel-size 4 --enable-expert-parallel`, one RBLN-CR13 per rank |
| KV block | `--block-size 4096`, `VLLM_RBLN_SUB_BLOCK_CACHE=1` (sub-block prefix cache on) |
| Batching | `--max-num-seqs 8`, decode buckets `1,4,8` (`VLLM_RBLN_DECODE_BATCH_BUCKET_STRATEGY=manual`) |
| Prefill | chunked, `--max-num-batched-tokens 512` |
| Prefix cache | vLLM `--enable-prefix-caching`, `--enable-prompt-tokens-details` (usage.cached_tokens) |
| Connector | none (no LMCache); one replica group |

Launcher: `scripts/exp/serve_m27.sh` (env: `VENV`, `RBLN_DEVICES`, `PORT`,
`SUB_BLOCK`, `BLOCK_SIZE`, `DEVICE_TENSOR`). Stop with
`scripts/exp/stop_exp.sh` (kills only this user's vllm processes).

## Software stack that loads the model

`~/vllm-rbln-dynkv/.venv`: vllm 0.26.0+cpu, vllm-rbln 0.11.3a20.dev1,
torch-rbln 0.5.0rc1, rebel-compiler 0.11.3.dev499, KMD 3.5.0~rc5.

Two settings are required with this stack and are now in the launcher:

1. **`RBLN_VISIBLE_DEVICES`, not `RBLN_DEVICES`.** vllm-rbln ≥ 0.11.3a20
   pops `RBLN_DEVICES`; with the new variable unset every DP rank selected
   the same NPU and weight upload failed with `rbln_memcpy_h2v failed ...
   device may be busy or faulted`. The launcher exports both names.
2. **`VLLM_RBLN_USE_DEVICE_TENSOR=0` (host-tensor weights).** With device
   tensors on, the fp8 M2.7 load fails on every rank at the first large
   tensor (`embed_tokens`, 1.23 GB) with the same `memcpy_h2v` error even
   when each rank has its own NPU. Isolated copies of the same tensor
   (mmap'd from the NFS checkpoint, cloned, or pinned) succeed on NPU 0
   and NPU 4, and `rbln/minimax-m2.7-tiny` loads in DP4+EP with device
   tensors, so the failure needs the concurrent full-size load; it is a
   vllm-rbln/torch-rbln issue, not a device fault. Host-tensor mode loads
   the weights (the compiler bakes them into the programs); measurements
   of TTFT and cached tokens are unaffected by where the weights sat
   before compile.

3. **`RBLN_OFFLOAD_DIR` on the shared store.** In host-tensor mode torch_rbln
   offloads tensors to per-process temp files under `RBLN_OFFLOAD_DIR`
   (default `~/.cache/rbln_cache/offload`); with M2.7 this filled the 1.7 TB
   home disk on 2026-09-24 and killed a replay mid-run (`ENOSPC`). The
   launcher now points it at
   `/mnt/shared_data/users/jinhwan.suk/.cache/rbln_cache/offload`. The user's
   shell already sets `HF_HOME` and `VLLM_CACHE_ROOT` under
   `/mnt/shared_data/users/jinhwan.suk/.cache`, which the launcher inherits.

## Stacks that do not work (do not retry)

| Stack | Failure |
|-------|---------|
| `~/lmcache-rbln/.venv` (vllm 0.24, vllm-rbln 0.11.3a4, rebel-compiler dev505) | compile error `rtosa.reshape` on the KV tensor (N blocks → 2) for M2.7 and for the tiny model; the vllm-rbln build predates the 2026-09-22 compiler upgrade |
| `data/exp/venv-sqt` (copy of the above with vllm-rbln 0.11.3a20) | `ValueError: not enough values to unpack (expected 3, got 2)`: a20 needs vllm 0.26 |
| Any launch right after killing a DP4 server on the same NPUs | `memcpy_h2v ... busy or faulted`; wait until `rbln-stat` shows no contexts |

## Measurement scripts

| Script | Purpose |
|--------|---------|
| `scripts/exp/probe_prefill.py` | E1: cold and append probes on an idle server; fits `P(n,K) = c0 + a n + b n (K + n/2)`; writes `data/exp/e1/probes.jsonl` and the fit |
| `scripts/exp/run_e2.sh <tag> <spacing_s> <cap>` | E2: open-loop replay of the coding-agent trace (37 sessions) with a live-session cap; writes `data/exp/e2/<tag>/rounds.jsonl` and `/metrics` samples |
| `scripts/exp/analyze_e2.py --fit fit.json [--warmup 90] runs...` | per run: λ, N̄, Z, E[S], CV², ρ, interarrival CV², TTFT, observed wait vs open PK and finite-source predictions, variance split; `--warmup` restricts the window to [first arrival + 90 s, last arrival] (E2b) |
| `scripts/exp/make_short_trace.py` | E2b: derives the short-context trace from the 50k one (2k first prompt, appends scaled to mean ~1k, out ≤ 4 tokens, per-session nonce, `--miss-share` forced misses by a nonce at the head of the prompt, ids salted for round-robin rank pinning) |
| `scripts/exp/analyze_price.py` | E2b: the forced-miss arm against its baseline, per rank: ΔL_P observed vs the bracket of `prop:price` and the finite-source price |
| `scripts/exp/paper_e2b_tables.py`, `plot_exp.py` | `paper/exp/tab-e2b*.tex`, `macros-e2b.tex`, `fig-e2b.pdf` |

The replayer is `~/icp-serving-workload-analysis/replayer/replay_text_trace.py`
(open-loop `--arrival-spacing-s`, `--session-admission-cap`). Both scripts
were validated end to end against the tiny model on one NPU (port 8020).

Results go into the paper only through generated tables (never typed by
hand); see `research/research-plan.md` §4.2a for the table layouts.

## Runs so far (2026-09-24/26)

| Run | What | Result |
|-----|------|--------|
| E1 `data/exp/e1/probes.jsonl` | 18 cold + 27 pinned append probes | `fit.json`: a = 0.194 ms/token, b = 6.51 ns/token², c0 = 44 ms, K_c ≈ 30k, MAPE 3.4 % |
| E2 `s20c0`, `s20c16`, `s20c8`, `s10c8` | 37 sessions × 10 turns, pinned, caps ∞/16/8/8 | `paper/exp/tab-e2.tex`; summary in `research/research-plan.md` §0 |
| `data/exp/e2_partial/s20c16_diskfull_partial` | first cap-16 attempt | killed by ENOSPC at 279/369; not used |
| `data/exp/e1/probes_unpinned.jsonl` | first append sweep without DP pinning | 2 of 27 hits; not used |

Runs are single-seed. Two replays must never run at once on the server.

## E2b: the PK regime on a short-context trace (2026-09-26)

Why: at 50k contexts a rank holds two to four contexts, so E2 never leaves
the memory-bound regime and never tests the PK wait or the price bracket.
E2b replays a derived trace (`scripts/exp/make_short_trace.py`, files
under `data/exp/traces/`, not committed, deterministic from the source):
9 copies of the 37 sessions, first prompt 2k tokens, appends = the source
appends × 0.44 (mean ~940, max 4000), contexts 2k → 8.6k (median),
`out ≤ 4` so decode is negligible, the source think times (mean 5–6 s,
capped at 30 s in the source), a 4-token nonce per session (no shared
prefixes), ids salted so crc32 pinning is round-robin (84/83/83/83).
Forced-miss arm: 10 % of follow-up turns get a 2-token nonce at the head
of that and every later prompt of the session (one full recompute, hits
again afterwards); the request carries `forced_miss: true`.
Runs: `TRACES=... OUTBASE=data/exp/e2b MAXSESS=... bash scripts/exp/run_e2.sh <tag> <spacing> 96`
(drivers `data/exp/e2b/batch2.sh`).

What did not work:
- `out ≤ 32` at 1.4 s spacing (`data/exp/e2b_v1_out32_overload/`): the
  decode batch cap (8 per rank) bound on every rank, waiting "by
  capacity" 5–17, ITL 0.25–0.32 s. Killed.
- `out ≤ 4` at 1.5 s spacing (`s15_base`, ρ_E1 ≈ 0.5): saturates and
  thrashes. Two mechanisms, both outside the E1 model: (i) the
  scheduler that ran, vllm-rbln's `RBLNScheduler`
  (`vllm_rbln/v1/core/rbln_scheduler.py`, logged on every engine in
  `data/exp/serve_m27_v7_hosttensor.log`; the `optimum_scheduler.py`
  cited here before did not run), never mixes a prefill with decodes:
  guards (A)–(D), l. 198–205, make a step either all decodes or a lone
  prefill, and an admitted prefill evicts the decode batch for that step,
  so prefill is exclusive and has priority over decode; and the
  DP+EP ranks step in lockstep (`v1/worker/dp_utils.py`), so ITL goes
  from 0.017 s idle to 0.10 s when a *peer* rank prefills, 0.17–0.25 s
  when the own rank has prefills pending, and 1.5 s at saturation (read
  off the replays, not probed on an idle server; the decode probe planned
  in `research/memory-model.md` must reproduce them independently); the
  4-token decodes then hold the 8 running slots for seconds; (ii) the pool is 52 blocks of 4096 tokens
  per rank (51 allocatable: one is vLLM's null block), so a 5k-token session holds 2 blocks and ~20 live sessions
  per rank fill it; LRU then evicts the prefixes with the longest gap
  (49 % of the misses followed a gap of 29 s or more and 91 % arrived to
  a queue on their rank; `scripts/exp/memory_model.py`, see
  `research/memory-model.md`), the misses re-prefill 4–6k tokens,
  and TTFT rises over the run (0.6 s → 3.6 s). `kv_cache_usage_perc`
  counts only running requests' blocks (20–35 %), not cached ones.
- Sub-block granularity is 512 tokens: `cached_tokens` is rounded down
  to a multiple of 512, so `analyze_e2.py` counts a hit as cached ≥
  min(0.9·prefix, prefix − 512).

Second batch (`batch2.sh`): 2.5 s (333 sessions), 3.5 s and 5 s (222
sessions), baseline and forced-miss arms. Results (window 90 s after
the first arrival to the last arrival; `make exp` regenerates them):

| run | ρ/rank (E1) | hit % | CV²_arr | W_srv (s) | PK (s) | finite (s) | price test (4 ranks summed) |
|-----|-------------|-------|---------|-----------|--------|------------|-----------------------------|
| `s15_base` (saturated) | 0.67–0.74 | 75 | 1.3 | 5.8 | 1.7 | 2.4 | – |
| `s25_base` / `s25_m10` | 0.35–0.36 | 98 | 1.0 | 0.11 | 0.16 | 0.13 | ΔL_P 2.05 vs [1.80, 2.27] (243 forced + 52 unforced misses; forced only [1.56, 1.88]), fin 0.82 |
| `s35_base` / `s35_m10` | 0.24–0.25 | 99 | 1.3 | 0.05 | 0.09 | 0.08 | ΔL_P 0.75 vs [0.74, 0.83] (163 forced, no unforced), fin 0.39 |
| `s25_base_s1` / `s25_m10_s1` (seed 1) | 0.35–0.36 | 98 | – | 0.11 | 0.16 | 0.13 | ΔL_P 2.15 vs [1.89, 2.44] (forced + 55 unforced), fin 0.86 |
| `s50_base` | 0.17 | 99 | 1.5 | 0.04 | 0.05 | 0.05 | – |

Reading: in the light arms the prefill queue is the only wait, the
arrivals are Poisson-like and the PK wait is 1.3–1.6× the server's
queueing time; the forced-miss rise sits inside the bracket
of `prop:price` at 3.5 s and 9 % above its upper end at 2.5 s (the
server's prefill time under concurrency is 1.09–1.29× the E1 model in
these runs (`pf_over_es` of `analyze_e2.py`; 1.07–1.10× in the long-context runs),
which the bracket does not include); the Markovian finite-source
price understates the rise 2–3×.

