#!/usr/bin/env bash
# Runs ON the Lambda instance: served replays with the step tracer
# (steptrace/sitecustomize.py) and, for hypothesis H-pin, with a waiting
# request's cached prefix pinned (steptrace/pinpatch.py).
#   tag spacing pin(0/1)
set -u
cd "$(dirname "$0")/../../.."
PORT=8020; BASE=http://127.0.0.1:$PORT; MODEL=Qwen/Qwen3-8B
export BASE MODEL DP_SIZE=0 REPLAYER=replayer/replay_text_trace.py
T=data/exp/traces; S=data/exp/gpu/seq_trace; mkdir -p $S
log() { echo "[steptrace] $(date '+%F %T') $*"; }
# Start after other testbed replays have drained; do not overlap runs.
for r in "s30_base 3.0 0" "s30_pin 3.0 1" "s25_pin 2.5 1"; do
  set -- $r
  pkill -f "[v]llm.entrypoints"; while nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -q .; do sleep 5; done
  PIN=""; [ "$3" = 1 ] && PIN=1
  PIN_WAITING=$PIN STEPTRACE=$PWD/$S/$1.steps PYTHONPATH=$PWD/scripts/exp/lambda/steptrace MAX_LEN=40960 MODEL=$MODEL PORT=$PORT \
    nohup bash scripts/exp/serve_gpu.sh > $S/serve_$1.out 2>&1 < /dev/null &
  for _ in $(seq 1 180); do curl -sf "$BASE/health" >/dev/null && break; sleep 5; done
  log "server up for $1 (pin=$3)"
  TRACES=$T/short_base.qwen.jsonl OUTBASE=$S bash scripts/exp/run_e2.sh "$1" "$2" 96 > "$S/$1.launch.log" 2>&1 &
  RP=$!
  while kill -0 $RP 2>/dev/null; do
    sleep 30
    n=$(wc -l < $S/$1/rounds.jsonl 2>/dev/null || echo 0)
    busy=$(curl -s -m 5 "$BASE/metrics" | grep -E "^vllm:num_requests_(running|waiting)\{" | awk '{s+=$2} END {print s+0}')
    if [ "$n" -ge 3300 ] && [ "$busy" = 0 ]; then sleep 60; pkill -f "[r]eplay_text_trace.py"; fi
  done
  log "done $1 ($(wc -l < $S/$1/rounds.jsonl) rounds; pin: $(grep -c 'pin: ' $S/serve_$1.out) messages)"
done
pkill -f "[v]llm.entrypoints"
log "all done"
