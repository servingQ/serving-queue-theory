#!/usr/bin/env bash
# GPU (A100) counterpart of serve_m27.sh: one vLLM replica with prefix caching,
# chunked prefill and /metrics, for the cost fit and the replays on GPU.
#
#   MODEL=... GPUS=0 PORT=8020 bash scripts/exp/serve_gpu.sh
#
# Env: MODEL (HF id; MiniMax-M2.7 needs 8 A100-80GB in bf16, A100 has no fp8;
#      a 30B-class dense model fits one A100 and is enough for the mechanism),
#      GPUS (CUDA_VISIBLE_DEVICES), TP (tensor parallel, default = number of
#      GPUs), PORT, MAX_LEN, BLOCK (16 on GPU), MAX_SEQS, BUDGET (chunked-prefill
#      token budget per step), VENV (a venv with vllm installed).
# Draft written 2026-09-26 before any GPU run; adjust flags to the vLLM version
# on the box. Caches stay under /mnt/shared_data (HF_HOME, VLLM_CACHE_ROOT).
set -euo pipefail
MODEL=${MODEL:?set MODEL}
GPUS=${GPUS:-0}
NGPU=$(echo "$GPUS" | tr ',' '\n' | wc -l)
TP=${TP:-$NGPU}
PORT=${PORT:-8020}
MAX_LEN=${MAX_LEN:-131072}
BLOCK=${BLOCK:-16}
MAX_SEQS=${MAX_SEQS:-64}
BUDGET=${BUDGET:-512}
VENV=${VENV:-$HOME/vllm-gpu/.venv}
export HF_HOME=${HF_HOME:-/mnt/shared_data/users/jinhwan.suk/.cache/huggingface}
export VLLM_CACHE_ROOT=${VLLM_CACHE_ROOT:-/mnt/shared_data/users/jinhwan.suk/.cache/vllm}
export CUDA_VISIBLE_DEVICES=$GPUS
LOG=data/exp/serve_gpu_$(date +%Y%m%d_%H%M%S).log
mkdir -p data/exp
echo "[serve_gpu] model=$MODEL gpus=$GPUS tp=$TP port=$PORT block=$BLOCK max_seqs=$MAX_SEQS budget=$BUDGET log=$LOG"
exec "$VENV/bin/python" -m vllm.entrypoints.cli.main serve "$MODEL" \
  --port "$PORT" \
  --tensor-parallel-size "$TP" \
  --max-model-len "$MAX_LEN" \
  --block-size "$BLOCK" \
  --enable-chunked-prefill --max-num-batched-tokens "$BUDGET" \
  --max-num-seqs "$MAX_SEQS" \
  --gpu-memory-utilization 0.9 \
  --enable-prefix-caching --enable-prompt-tokens-details \
  --trust-remote-code \
  2>&1 | tee "$LOG"
