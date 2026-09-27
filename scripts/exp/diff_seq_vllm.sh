#!/usr/bin/env bash
# Step-exact differential run of seQ (.seq/src/programs/vllm_replay.seq) and
# the real vLLM scheduler (.seq/src/tools/vllm_replay_oracle.py) on the first
# N sessions of a trace, with a constant step cost so that both timelines
# are identical if and only if the scheduling and caching decisions are.
#
#   bash scripts/exp/diff_seq_vllm.sh N BLOCKS SPACING [OUTDIR] [EXTRA seQ --set ...]
set -euo pipefail
cd "$(dirname "$0")/../.."
N=$1; BLOCKS=$2; SP=$3; D=${4:-data/exp/seq/diff}; shift 4 || shift $#
# COST=real uses the calibrated cost model of the program (both sides); the
# default is a constant 30 ms step, which makes the timelines comparable
# step by step.
if [ "${COST:-const}" = real ]; then
  # the A100 step fit (data/exp/gpu_seq/fit.json), as in vllm_replay.seq
  OARGS="--cost sum --c-step 0.013939 --d 4.1053e-5 --beta 1.3786e-7 --a 5.1527e-5 --b 4.0196e-9 --c0 0.02524"; RARGS=()
else
  OARGS="--cost sum --c-step 0.03 --d 0 --beta 0 --a 0 --b 0 --c0 0"
  RARGS=(--set c_it=0.03 --set d=0 --set e=0 --set a=0 --set b=0 --set c0=0)
fi
TRACE=${TRACE:-short_base}; FORCED=${FORCED:-}
export HF_HOME=/mnt/shared_data/users/jinhwan.suk/.cache/huggingface VLLM_CACHE_ROOT=/mnt/shared_data/users/jinhwan.suk/.cache/vllm VLLM_PLUGINS=
mkdir -p "$D"
timeout 1200 ~/vllm-rbln-dynkv/.venv/bin/python .seq/src/tools/vllm_replay_oracle.py \
  --trace data/exp/traces/$TRACE.jsonl $FORCED --spacing "$SP" --max-sessions "$N" --blocks "$BLOCKS" \
  $OARGS --out "$D/oracle.csv" 2>&1 | grep -v "^INFO\|WARNING\|Triton\|Model Runner\|SSM" | tail -2
P=(.seq/src/programs/vllm_replay.seq --set N="$N" --set blocks="$BLOCKS" "${RARGS[@]}"
   --set spacing="$SP" "$@" --trace .seq/src/programs/data/$TRACE.csv)
.seq/bin/seq-lang ir "${P[@]}" > "$D/program.ir.json"      # what ran, as IR
.seq/bin/seq-lang run "${P[@]}" --dump "$D/seq" > "$D/seq.txt"
python3 - "$D" <<'EOF'
import sys
D = sys.argv[1]
o = {}
for l in open(D + '/oracle.csv').read().splitlines()[1:]:
    s, k, sent, first, done, prompt, cached, out = l.split(',')
    if first == 'None':
        continue
    o[(int(s), int(k))] = (float(sent), float(first), int(cached), int(prompt))
def rd(n):
    d = {}
    for l in open(f'{D}/seq/{n}.csv').read().splitlines()[1:]:
        t, s, k, v = l.split(',')
        d[(int(s), int(k))] = float(v)
    return d
sent, tt, ca = rd('sent'), rd('ttft'), rd('cached_tokens')
keys = sorted(o, key=lambda k: o[k][0])
nd = 0
for k in keys:
    if k not in sent:
        print('missing in seq', k)
        nd += 1
        continue
    a = o[k]
    b = (sent[k], sent[k] + tt[k], int(ca[k]))
    if abs(a[0] - b[0]) > 1e-6 or abs(a[1] - b[1]) > 1e-6 or a[2] != b[2]:
        nd += 1
        if nd <= 6:
            print('DIFF', k, 'vllm: sent %.3f first %.3f cached %d prompt %d' % a, '| seq: sent %.3f first %.3f cached %d' % b)
print(f'{len(keys)} requests, {nd} differ')
EOF
