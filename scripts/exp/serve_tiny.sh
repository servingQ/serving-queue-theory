#!/usr/bin/env bash
# Fast repro of the compile error with rbln/minimax-m2.7-tiny on one NPU.
#   RBLN_DEVICES=0 PORT=8020 EXTRA="--disable-hybrid-kv-cache-manager" bash scripts/exp/serve_tiny.sh
set -uo pipefail
VENV=${VENV:-/home/jinhwan.suk/lmcache-rbln/.venv}
source "$VENV/bin/activate"
unset PYTHONPATH
source /home/jinhwan.suk/lmcache-rbln/tests/e2e/serve_env.rc
export VLLM_RBLN_SUB_BLOCK_CACHE=${SUB_BLOCK:-1}
export VLLM_RBLN_DECODE_BATCH_BUCKET_STRATEGY=manual
export VLLM_RBLN_DECODE_BATCH_BUCKET_MANUAL_BUCKETS=${BUCKETS:-1,4,8}
export VLLM_DISABLE_COMPILE_CACHE=1
export HF_HUB_OFFLINE=1
export HF_HOME=${HF_HOME:-/mnt/shared_data/.cache/huggingface}
# torch_rbln file offloading (host-tensor mode, RBLN_WEIGHT_FREE) writes per-process
# temp tensors under RBLN_OFFLOAD_DIR (default ~/.cache/rbln_cache/offload); with
# 200 GB of weights that fills the home disk. Keep it on the shared store.
export RBLN_OFFLOAD_DIR=${RBLN_OFFLOAD_DIR:-/mnt/shared_data/users/jinhwan.suk/.cache/rbln_cache/offload}
mkdir -p "$RBLN_OFFLOAD_DIR"
export RBLN_DEVICES=${RBLN_DEVICES:-0}
# vllm-rbln >= 0.11.3a20 drops RBLN_DEVICES (an inherited empty RBLN_VISIBLE_DEVICES
# put every DP rank on the same NPU -> rbln_memcpy_h2v failures). Set the new name.
export RBLN_VISIBLE_DEVICES="$RBLN_DEVICES"
unset RBLN_DEVICES
export VLLM_RBLN_USE_DEVICE_TENSOR=${DEVICE_TENSOR:-1}
export PORT=${PORT:-8020}
export BLOCK_SIZE=${BLOCK_SIZE:-1024}
echo "[tiny] $(date '+%F %T') port=$PORT dev=$RBLN_VISIBLE_DEVICES block=$BLOCK_SIZE sub_block=$VLLM_RBLN_SUB_BLOCK_CACHE device_tensor=$VLLM_RBLN_USE_DEVICE_TENSOR extra='${EXTRA:-}'"
exec "$VENV/bin/python" -m vllm.entrypoints.cli.main serve "${MODEL:-/mnt/shared_data/.cache/huggingface/hub/models--rbln--minimax-m2.7-tiny/snapshots/91571a3fe734cee2107b69f5d50043f8f56676f0}" --served-model-name tiny --port "$PORT" \
  --max-model-len 16384 --block-size "$BLOCK_SIZE" \
  --enable-chunked-prefill --max-num-batched-tokens 512 --max-num-seqs 8 \
  --gpu-memory-utilization 0.5 --trust-remote-code ${EXTRA:-}
