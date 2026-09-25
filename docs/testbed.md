# NPU testbed for E1/E2 (MiniMax-M2.7, DP4 + EP)

Status as of 2026-09-24. This file records how the measurement server is
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
| `scripts/exp/analyze_e2.py --fit fit.json runs...` | per run: λ, N̄, Z, E[S], CV², ρ, TTFT, observed wait vs open PK and finite-source predictions, variance split |

The replayer is `~/icp-serving-workload-analysis/replayer/replay_text_trace.py`
(open-loop `--arrival-spacing-s`, `--session-admission-cap`). Both scripts
were validated end to end against the tiny model on one NPU (port 8020).

Results go into the paper only through generated tables (never typed by
hand); see `docs/research-plan.md` §4.2a for the table layouts.

## Runs so far (2026-09-24/26)

| Run | What | Result |
|-----|------|--------|
| E1 `data/exp/e1/probes.jsonl` | 18 cold + 27 pinned append probes | `fit.json`: a = 0.194 ms/token, b = 6.51 ns/token², c0 = 44 ms, K_c ≈ 30k, MAPE 3.4 % |
| E2 `s20c0`, `s20c16`, `s20c8`, `s10c8` | 37 sessions × 10 turns, pinned, caps ∞/16/8/8 | `paper/exp/tab-e2.tex`; summary in `docs/research-plan.md` §0 |
| `data/exp/e2_partial/s20c16_diskfull_partial` | first cap-16 attempt | killed by ENOSPC at 279/369; not used |
| `data/exp/e1/probes_unpinned.jsonl` | first append sweep without DP pinning | 2 of 27 hits; not used |

Runs are single-seed. Two replays must never run at once on the server.

