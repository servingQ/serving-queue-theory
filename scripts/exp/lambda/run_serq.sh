#!/usr/bin/env bash
# Runs ON the Lambda instance: served replays with per-iteration logging, the
# end-to-end test cases of serQ (serQ `docs/language.md` §8).
set -u
cd "$(dirname "$0")/../../.."
PORT=8020; BASE=http://127.0.0.1:$PORT; MODEL=Qwen/Qwen3-8B
export BASE MODEL DP_SIZE=0 REPLAYER=replayer/replay_text_trace.py
T=data/exp/traces
log() { echo "[run_serq] $(date '+%F %T') $*"; }
drain() {
  while pgrep -f "replay_text_trac[e].py" >/dev/null; do sleep 5; done
  while curl -s -m 5 "$BASE/metrics" | grep -E "^vllm:num_requests_(running|waiting)\{" | awk '{s+=$2} END {exit !(s>0)}'; do sleep 5; done
  sleep 20
}
S=data/exp/gpu/seq; mkdir -p $S
pkill -f "[v]llm.entrypoints"; while nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -q .; do sleep 5; done
MAX_LEN=40960 MODEL=$MODEL PORT=$PORT EXTRA_ARGS="--enable-logging-iteration-details" nohup bash scripts/exp/serve_gpu.sh > $S/serve.out 2>&1 < /dev/null &
for _ in $(seq 1 180); do curl -sf "$BASE/health" >/dev/null && break; sleep 5; done
log "server up"
for r in "s35_base 3.5 short_base" "s30_base 3.0 short_base" "s35_m10 3.5 short_m10"; do
  set -- $r
  drain
  log "start $1"
  TRACES=$T/$3.qwen.jsonl OUTBASE=$S bash scripts/exp/run_e2.sh "$1" "$2" 96 > "$S/$1.launch.log" 2>&1
  grep -a "Iteration(" $S/serve.out > $S/$1.iterations.log; : > /dev/null
  log "done $1"
done
log "all done"
