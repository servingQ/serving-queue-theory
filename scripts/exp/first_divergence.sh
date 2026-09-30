#!/usr/bin/env bash
# First scheduler step at which serQ and the real vLLM scheduler differ
# (schedule or block accounting), with the steps around it.
#   bash scripts/exp/first_divergence.sh N BLOCKS SPACING DIR
set -euo pipefail
cd "$(dirname "$0")/../.."
N=$1; B=$2; SP=$3; D=$4
export HF_HOME=/mnt/shared_data/users/jinhwan.suk/.cache/huggingface VLLM_PLUGINS=
mkdir -p "$D"
ORACLE_TRACE_ITER=1 ORACLE_TRACE_EVICT=1 ~/vllm-rbln-dynkv/.venv/bin/python .serq/src/tools/vllm_replay_oracle.py --trace data/exp/traces/short_base.jsonl --spacing "$SP" --max-sessions "$N" --blocks "$B" --cost sum --c-step 0.03 --d 0 --beta 0 --a 0 --b 0 --c0 0 --out "$D/oracle.csv" 2>&1 | grep -E "^(ITER|EVICT)" > "$D/oracle.log"
SERQ_TRACE_ITER=1 SERQ_TRACE_EVICT=1 .serq/bin/serq run .serq/src/examples/replay/vllm_replay.sq --trace .serq/src/examples/replay/data/short_base.csv --set N="$N" --set blocks="$B" --set c_it=0.03 --set d=0 --set e=0 --set a=0 --set b=0 --set c0=0 --set spacing="$SP" 2>"$D/seq.log" >/dev/null
python3 - "$D" <<'PY'
import sys
D = sys.argv[1]
o = [l.rstrip() for l in open(D + '/oracle.log') if l.startswith('ITER')]
r = [l.rstrip() for l in open(D + '/seq.log') if l.startswith('ITER')]
for i, (a, b) in enumerate(zip(o, r)):
    if a != b:
        print(f'first differing step #{i}')
        for j in range(max(0, i - 3), min(len(o), i + 3)):
            print('  vllm ', o[j]); print('  seq  ', r[j])
        break
else:
    print('no differing step', len(o), len(r))
PY
