#!/usr/bin/env python
"""GPU test cases for serQ (runs ON the Lambda instance, in ~/vllm-gpu/.venv).

The vLLM engine runs in-process (VLLM_ENABLE_V1_MULTIPROCESSING=0,
synchronous scheduling) and is stepped by hand, so every engine step is one
scheduler iteration whose inputs (the SchedulerOutput) and wall time are
recorded.

  scenarios DIR OUT   every .serq/src/tools/oracle/*.json scenario on the real
                      engine: per request the step of its first and last token
                      and the preemptions (the format of *.out.json), plus the
                      step records
  steps OUT           step-cost sweeps: decode batches of n requests at context
                      K, and prefill chunks at context K; one JSON line per step:
                      {"t_ms", "npre", "ndec", "kvb", "kvp", "pre": [[n, K]...]}

Env: MODEL (default Qwen/Qwen3-8B).
"""
import json
import os
import sys
import time

os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")

import torch  # noqa: E402
from vllm import LLM, SamplingParams  # noqa: E402

MODEL = os.environ.get("MODEL", "Qwen/Qwen3-8B")


def make_llm(budget, max_seqs, block, num_blocks=None, chunk=0, max_len=40960, caching=True, eager=False):
    kw = dict(
        model=MODEL,
        block_size=block,
        max_num_batched_tokens=budget,
        max_num_seqs=max_seqs,
        enable_prefix_caching=caching,
        enable_chunked_prefill=True,
        long_prefill_token_threshold=chunk,
        max_model_len=max_len,
        gpu_memory_utilization=0.9,
        async_scheduling=False,
        enforce_eager=eager,
    )
    if num_blocks is not None:
        kw["num_gpu_blocks_override"] = num_blocks
    return LLM(**kw)


class Stepper:
    """Steps an in-process engine and records each iteration."""

    def __init__(self, llm, block):
        self.engine = llm.llm_engine
        core = self.engine.engine_core
        self.core = getattr(core, "engine_core", core)
        self.sched = self.core.scheduler
        self.block = block
        self.last_out = None
        orig = self.sched.schedule

        def schedule(*a, **k):
            out = orig(*a, **k)
            self.last_out = out
            return out

        self.sched.schedule = schedule
        self.first = {}
        self.done = {}
        self.preempt = 0
        self.steps = []
        self.n = 0

    def add(self, rid, ids, out):
        self.engine.add_request(
            rid, {"prompt_token_ids": list(ids)}, SamplingParams(max_tokens=out, ignore_eos=True, temperature=0.0)
        )

    def step(self):
        self.last_out = None
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        outs = self.engine.step()
        torch.cuda.synchronize()
        dt = (time.perf_counter() - t0) * 1000
        so = self.last_out
        if so is None or so.total_num_scheduled_tokens == 0:
            return outs, None
        self.n += 1
        self.preempt += len(so.preempted_req_ids or [])
        rec = {"step": self.n, "t_ms": dt, "npre": 0, "ndec": 0, "kvb": 0, "kvp": 0, "pre": [], "dec": []}
        for rid, n in so.num_scheduled_tokens.items():
            req = self.sched.requests.get(rid)
            if req is None:
                continue
            k_after = req.num_computed_tokens
            held = len(self.sched.kv_cache_manager.get_block_ids(rid)[0]) * self.block
            if k_after - n < req.num_prompt_tokens:
                rec["npre"] += n
                rec["kvp"] += held
                rec["pre"].append([n, k_after - n])
            else:
                rec["ndec"] += 1
                rec["kvb"] += held
                rec["dec"].append(k_after)
        self.steps.append(rec)
        for o in outs:
            if o.outputs and len(o.outputs[0].token_ids) >= 1 and o.request_id not in self.first:
                self.first[o.request_id] = self.n
            if o.finished:
                self.done[o.request_id] = self.n
        return outs, rec


def scenarios(dirname, outname):
    # one process per scenario: an engine's GPU memory is only freed on exit
    import subprocess
    res = {}
    for f in sorted(os.listdir(dirname)):
        if not f.endswith(".json") or f.endswith(".out.json") or f == "a100_engine.json":
            continue
        tmp = outname + "." + f
        subprocess.run([sys.executable, __file__, "scenario", os.path.join(dirname, f), tmp], check=True)
        res.update(json.load(open(tmp)))
    json.dump(res, open(outname, "w"))


def scenario(path, outname):
    res = {}
    for f in [os.path.basename(path)]:
        sc = json.load(open(path))
        need = max(r["prompt"] + r["out"] for r in sc["requests"])
        max_len = min(8192, (sc["num_blocks"] - 1) * sc["block_size"])
        max_len = max(max_len, need)
        llm = make_llm(sc["budget"], sc["max_seqs"], sc["block_size"], sc["num_blocks"], sc.get("chunk", 0),
                       max_len=max_len, caching=sc.get("prefix_caching", False), eager=True)
        st = Stepper(llm, sc["block_size"])
        pending = sorted(enumerate(sc["requests"]), key=lambda x: x[1].get("arrive", 0))
        steps = 0
        while pending or st.engine.has_unfinished_requests():
            # a request arriving at step s is present for step s+1 (the oracle's rule)
            while pending and pending[0][1].get("arrive", 0) <= steps:
                i, r = pending.pop(0)
                ids = [(i * 7919 + k) % 50000 + 1 for k in range(r["prompt"])]
                st.add(str(i), ids, r["out"])
            _, rec = st.step()
            steps += 1
            if steps > sc.get("max_steps", 10000):
                break
        res[f[:-5]] = {"first": st.first, "done": st.done, "preemptions": st.preempt, "steps": st.steps}
        print(f, {"first": st.first, "done": st.done, "preemptions": st.preempt}, flush=True)
    json.dump(res, open(outname, "w"))


def steps(outname):
    llm = make_llm(512, 64, 16)
    st = Stepper(llm, 16)
    f = open(outname, "w")
    rid = 0

    def run_batch(n, K, out):
        nonlocal rid
        for j in range(n):
            ids = [((rid + 1) * 104729 + k) % 150000 + 1 for k in range(K)]
            st.add(f"b{rid}", ids, out)
            rid += 1
        while st.engine.has_unfinished_requests():
            _, rec = st.step()
            if rec is not None:
                rec["batch"] = [n, K, out]
                f.write(json.dumps(rec) + "\n")
        f.flush()

    run_batch(1, 256, 8)  # warm-up
    for K in [256, 1024, 4096, 8192, 16384, 32768]:
        for n in [1, 2, 4, 8, 16, 32, 64]:
            if n * (K + 64) > 120000:
                continue
            run_batch(n, K, 64)
            print("steps", K, n, flush=True)
    f.close()


if __name__ == "__main__":
    if sys.argv[1] == "scenarios":
        scenarios(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "scenario":
        scenario(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "steps":
        steps(sys.argv[2])
    else:
        sys.exit(__doc__)
