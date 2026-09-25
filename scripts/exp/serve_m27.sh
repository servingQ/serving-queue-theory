#!/usr/bin/env bash
# E1/E2 testbed server: MiniMax-M2.7 (fp8 weights, W8A16 on RBLN), DP4 + EP on
# four RBLN-CR13 NPUs, 4096-token KV blocks, vLLM prefix caching with the
# RBLN sub-block prefix cache on, chunked prefill. No LMCache connector: the
# experiment measures the prefill queue of one replica group under KV reuse.
#
#   bash scripts/exp/serve_m27.sh > data/exp/serve_m27.log 2>&1 &
#   curl -sf http://127.0.0.1:${PORT:-8010}/health
#
# Environment follows lmcache-rbln/tests/e2e/serve_env.rc (MoE/EP runtime
# flags) with the sub-block cache ON and the compile cache used.
set -uo pipefail
VENV=${VENV:-/home/jinhwan.suk/lmcache-rbln/.venv}
source "$VENV/bin/activate"
unset PYTHONPATH
source /home/jinhwan.suk/lmcache-rbln/tests/e2e/serve_env.rc
export VLLM_RBLN_SUB_BLOCK_CACHE=${SUB_BLOCK:-1}   # the sub-block prefix cache under test
# Decode batch buckets: compile only batch sizes 1, 4 and 8 (max-num-seqs 8).
export VLLM_RBLN_DECODE_BATCH_BUCKET_STRATEGY=manual
export VLLM_RBLN_DECODE_BATCH_BUCKET_MANUAL_BUCKETS=${BUCKETS:-1,4,8}
export VLLM_DISABLE_COMPILE_CACHE=0         # reuse ~/.cache/vllm/rbln across runs
export HF_HOME=${HF_HOME:-/mnt/shared_data/.cache/huggingface}
# torch_rbln file offloading (host-tensor mode, RBLN_WEIGHT_FREE) writes per-process
# temp tensors under RBLN_OFFLOAD_DIR (default ~/.cache/rbln_cache/offload); with
# 200 GB of weights that fills the home disk. Keep it on the shared store.
export RBLN_OFFLOAD_DIR=${RBLN_OFFLOAD_DIR:-/mnt/shared_data/users/jinhwan.suk/.cache/rbln_cache/offload}
mkdir -p "$RBLN_OFFLOAD_DIR"
export RBLN_DEVICES=${RBLN_DEVICES:-0,1,2,3}
# vllm-rbln >= 0.11.3a20 drops RBLN_DEVICES (an inherited empty RBLN_VISIBLE_DEVICES
# put every DP rank on the same NPU -> rbln_memcpy_h2v failures). Set the new name.
export RBLN_VISIBLE_DEVICES="$RBLN_DEVICES"
unset RBLN_DEVICES
export VLLM_RBLN_USE_DEVICE_TENSOR=${DEVICE_TENSOR:-1}
export PORT=${PORT:-8010}
export MODEL=${MODEL:-MiniMaxAI/MiniMax-M2.7}
export MAX_MODEL_LEN=${MAX_MODEL_LEN:-102400}
export BLOCK_SIZE=${BLOCK_SIZE:-4096}
export KV_DTYPE=${KV_DTYPE:-auto}
echo "[serve] $(date '+%F %T') model=$MODEL port=$PORT devices=$RBLN_VISIBLE_DEVICES block=$BLOCK_SIZE kv=$KV_DTYPE max_model_len=$MAX_MODEL_LEN sub_block=$VLLM_RBLN_SUB_BLOCK_CACHE buckets=$VLLM_RBLN_DECODE_BATCH_BUCKET_MANUAL_BUCKETS max_num_seqs=8"
exec "$VENV/bin/python" -m vllm.entrypoints.cli.main serve "$MODEL" --port "$PORT" \
  --data-parallel-size 4 --enable-expert-parallel \
  --max-model-len "$MAX_MODEL_LEN" --block-size "$BLOCK_SIZE" --kv-cache-dtype "$KV_DTYPE" \
  --enable-chunked-prefill --max-num-batched-tokens 512 --max-num-seqs 8 \
  --gpu-memory-utilization 0.8 --trust-remote-code \
  --enable-prefix-caching --enable-prompt-tokens-details
