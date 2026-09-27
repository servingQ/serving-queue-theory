#!/usr/bin/env python3
"""Decode-stretch probe on an idle server (pre-registered in docs/memory-model.md).

Each experiment launches a set of streaming requests, each pinned to a DP rank
(X-data-parallel-rank), with random unique prompts (no prefix hits) and
ignore_eos, and records the arrival time of every streamed chunk. One JSON line
per request goes to --out:
  {exp, cfg, rank, K, out, t_send, t_first, t_done, times: [...], usage}
with times relative to the experiment start (perf_counter).

Experiments (--only to run a subset):
  A  decode on rank 0 with b concurrent requests of context K (others idle)
  B  rank 0: 4 x 16k decoding; rank 1: b in {0, 4, 8} x 2k decoding at once
  C  rank 0: 1 x 16k decoding; rank 1: a cold prefill of n in {8k, 32k}
     started 12 s later (rank 0 is decoding by then)
  D  rank 0: 1 x 16k decoding; rank 0: a cold prefill of 16k 12 s later
  E  rank 0: a cold prefill of 16k alone, and while rank 1 prefills 32k
  F  (added after v1 failed, to identify the cross-rank context term) all four
     ranks decoding b requests of context K at once
  G  (added after v2 failed on s15) prefill stretch with k = 1..4 ranks
     prefilling at once: rank 0 prefills n0 while k-1 peers prefill n1

  python3 scripts/exp/probe_decode.py --base-url http://127.0.0.1:8010/v1 \\
      --model MiniMaxAI/MiniMax-M2.7 --out data/exp/decode/probes.jsonl
"""
import argparse
import json
import random
import threading
import time
import urllib.request

VOCAB = (1000, 150000)


def rand_prompt(n, rng):
    return [rng.randint(*VOCAB) for _ in range(n)]


def stream(base, model, rank, prompt, max_tokens, t0, rec):
    body = json.dumps({"model": model, "prompt": prompt, "max_tokens": max_tokens, "stream": True,
                       "ignore_eos": True, "temperature": 0.0,
                       "stream_options": {"include_usage": True}}).encode()
    req = urllib.request.Request(base + "/completions", data=body,
                                 headers={"Content-Type": "application/json", "X-data-parallel-rank": str(rank)})
    rec["t_send"] = time.perf_counter() - t0
    times = []
    try:
        with urllib.request.urlopen(req, timeout=3600) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                obj = json.loads(payload)
                if obj.get("choices"):
                    times.append(time.perf_counter() - t0)
                if obj.get("usage"):
                    rec["usage"] = obj["usage"]
    except Exception as e:  # recorded, not raised: the experiment continues
        rec["error"] = repr(e)
    rec["times"] = times
    rec["t_first"] = times[0] if times else None
    rec["t_done"] = time.perf_counter() - t0


def launch(args, specs, rng):
    """specs: list of dict(rank, K, out, delay): each request starts `delay`
    seconds after the previous one was started."""
    t0 = time.perf_counter()
    recs = [dict(rank=s["rank"], K=s["K"], out=s["out"]) for s in specs]
    prompts = [rand_prompt(s["K"], rng) for s in specs]
    threads = []
    for i, s in enumerate(specs):
        time.sleep(s.get("delay", 0.0))
        th = threading.Thread(target=stream, args=(args.base_url, args.model, s["rank"], prompts[i], s["out"], t0, recs[i]))
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8010/v1")
    ap.add_argument("--model", default="MiniMaxAI/MiniMax-M2.7")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="ABCDE")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    out = open(args.out, "a")

    def run(exp, cfg, specs):
        recs = launch(args, specs, rng)
        for r in recs:
            r.update(exp=exp, cfg=cfg)
            out.write(json.dumps(r) + "\n")
        out.flush()
        firsts = [r["t_first"] for r in recs if r.get("t_first")]
        print(f"{exp} {cfg}: {len(recs)} requests, first tokens {min(firsts) if firsts else None} .. "
              f"{max(firsts) if firsts else None}, errors {sum(1 for r in recs if r.get('error'))}", flush=True)
        time.sleep(3)

    for rep in range(args.reps):
        if "A" in args.only:
            for K in (2048, 16384, 50000):
                for b in (1, 2, 3, 4, 5, 8):
                    if K == 50000 and b > 3:
                        continue
                    out_tokens = 256 + 40 * b if K <= 16384 else 400
                    run("A", dict(K=K, b=b, rep=rep), [dict(rank=0, K=K, out=out_tokens) for _ in range(b)])
        if "B" in args.only:
            for b1 in (0, 4, 8):
                specs = [dict(rank=0, K=16384, out=600) for _ in range(4)]
                specs += [dict(rank=1, K=2048, out=800) for _ in range(b1)]
                run("B", dict(b1=b1, rep=rep), specs)
        if "C" in args.only:
            for n in (8192, 32768):
                run("C", dict(n=n, rep=rep), [dict(rank=0, K=16384, out=1500), dict(rank=1, K=n, out=1, delay=12.0)])
        if "D" in args.only:
            run("D", dict(n=16384, rep=rep), [dict(rank=0, K=16384, out=1500), dict(rank=0, K=16384, out=1, delay=12.0)])
        if "E" in args.only:
            run("E", dict(peer=0, rep=rep), [dict(rank=0, K=16384, out=1)])
            run("E", dict(peer=1, rep=rep), [dict(rank=1, K=32768, out=1), dict(rank=0, K=16384, out=1, delay=0.3)])
        if "F" in args.only:
            for K, b, nr in ((16384, 1, 4), (16384, 2, 4), (16384, 4, 4), (50000, 1, 4), (50000, 2, 4),
                             (50000, 3, 4), (50000, 3, 2), (50000, 2, 2)):
                run("F", dict(K=K, b=b, ranks=nr, rep=rep),
                    [dict(rank=r, K=K, out=500) for r in range(nr) for _ in range(b)])
        if "G" in args.only:
            for n0, n1 in ((16384, 32768), (2048, 4096), (4096, 4096)):
                for k in (1, 2, 3, 4):
                    specs = [dict(rank=r, K=n1, out=1) for r in range(1, k)]
                    specs.append(dict(rank=0, K=n0, out=1, delay=0.2 if k > 1 else 0.0))
                    run("G", dict(n0=n0, n1=n1, k=k, rep=rep), specs)


if __name__ == "__main__":
    main()
