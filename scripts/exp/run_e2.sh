#!/usr/bin/env bash
# E2 on one replica group: replay the coding-agent trace against the server
# started by serve_m27.sh, open-loop (one session every SPACING seconds),
# with a cap on live sessions, and record per-request TTFT, cached tokens and
# the server's /metrics every second.
#
#   bash scripts/exp/run_e2.sh <tag> <spacing_s> <cap>      # e.g. run_e2.sh s20c8 20 8
#
# Output: data/exp/e2/<tag>/{rounds.jsonl,meta.json,metrics.jsonl}
set -euo pipefail
TAG=$1; SPACING=$2; CAP=$3
BASE=${BASE:-http://127.0.0.1:8010}
MODEL=${MODEL:-MiniMaxAI/MiniMax-M2.7}
TRACES=${TRACES:-/mnt/shared_data/groups/fsw_serv/fsw-415/cc_traj_50k_think30s.jsonl}
REPLAYER=${REPLAYER:-/home/jinhwan.suk/icp-serving-workload-analysis/replayer/replay_text_trace.py}
# Session affinity: pin each session to one DP rank (X-data-parallel-rank), so
# KV reuse within a session is possible; DP_SIZE=0 lets vLLM balance per request.
DP_SIZE=${DP_SIZE:-4}
OUT=data/exp/e2/$TAG
mkdir -p "$OUT"
curl -sf "$BASE/health" >/dev/null || { echo "server not ready at $BASE"; exit 1; }
NSESS=$(wc -l < "$TRACES")
echo "[e2] $(date '+%F %T') tag=$TAG spacing=${SPACING}s cap=$CAP dp_size=$DP_SIZE sessions=$NSESS"
printf '{"tag":"%s","spacing_s":%s,"cap":%s,"dp_size":%s,"sessions":%s,"model":"%s","started":"%s"}\n' "$TAG" "$SPACING" "$CAP" "$DP_SIZE" "$NSESS" "$MODEL" "$(date -Is)" > "$OUT/params.json"
python3 "$REPLAYER" \
  --traces "$TRACES" \
  --base-url "$BASE/v1" \
  --model "$MODEL" \
  --concurrency "$NSESS" \
  --arrival-spacing-s "$SPACING" \
  --session-admission-cap "$CAP" \
  --dp-size "$DP_SIZE" \
  --metrics-url "$BASE/metrics" --metrics-interval 1.0 \
  --no-output-text \
  --out "$OUT/rounds.jsonl" 2>&1 | tee "$OUT/replay.log"
echo "[e2] $(date '+%F %T') done -> $OUT"
