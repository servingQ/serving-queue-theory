#!/usr/bin/env python3
"""Convert a replay trace (`data/exp/traces/*.jsonl`, one session per line
with `requests: [{in, out, think_time, forced_miss}, ...]`) into the seQ
trace CSV `session,turn,new,out,think,forced`, where `new` is the absolute
prompt length of the turn (the vLLM replay program uses it as the prompt),
`out` the completion length, `think` the gap before the next turn and
`forced` 1 for a turn that carries a nonce (reuses no prefix).

    python3 scripts/exp/seq_trace.py data/exp/traces/short_base.jsonl .seq/src/examples/replay/data/short_base.csv
"""
import json
import sys


def main():
    src, dst = sys.argv[1], sys.argv[2]
    n_sessions = 0
    with open(dst, "w") as out:
        out.write("session,turn,new,out,think,forced\n")
        for i, line in enumerate(open(src)):
            line = line.strip()
            if not line:
                continue
            s = json.loads(line)
            reqs = s["requests"]
            for k, q in enumerate(reqs):
                # the trace's think_time is the gap before this request;
                # seQ's `think` is the gap after a turn
                think = reqs[k + 1].get("think_time", 0.0) if k + 1 < len(reqs) else 0.0
                out.write(
                    f"{i},{k + 1},{q['in']},{q['out']},{think},{1 if q.get('forced_miss') else 0}\n"
                )
            n_sessions += 1
    print(f"{dst}: {n_sessions} sessions", file=sys.stderr)


if __name__ == "__main__":
    main()
