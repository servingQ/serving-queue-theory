#!/usr/bin/env bash
# Stop my own experiment servers (vllm serve, engine cores, workers, DP
# coordinators) and nothing else. Usage: stop_exp.sh [pattern]
# The pattern defaults to every vllm process of this user.
pat=${1:-"vllm serve|EngineCore|Worker_DP|VLLM::DPCoordinator|VllmWorker"}
me=$(id -u)
for p in $(pgrep -u "$me" -f "$pat"); do
  { [ "$p" = "$$" ] || [ "$p" = "$PPID" ]; } && continue
  kill "$p" 2>/dev/null
done
sleep 3
for p in $(pgrep -u "$me" -f "$pat"); do
  { [ "$p" = "$$" ] || [ "$p" = "$PPID" ]; } && continue
  kill -9 "$p" 2>/dev/null
done
echo "[stop] $(date '+%F %T') remaining: $(pgrep -u "$me" -f "$pat" | grep -v "^$$\$" | wc -l)"
