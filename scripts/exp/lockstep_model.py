#!/usr/bin/env python3
"""Step-level lockstep replica model: memory_model.py with the decode durations
computed instead of measured (pre-registered in docs/memory-model.md).

The memory side is that of memory_model.py (51 blocks per rank, block-level
LRU with sub-block copies, prompt-only reuse, strict FCFS admission of whole
prompts, at most 8 running). The time side is a sequence of engine steps shared
by all ranks (the DP+EP ranks step in lockstep):

  * a rank with a prefill in progress computes one chunk of up to 512 tokens,
    costing a*m + b*m*(offset + m/2) from the cost fit (E1) (its intercept c0
    is client/frontend latency, added to the client-side first-token and
    completion times, not charged as engine time), and decodes nothing in that step (probe D: an own-rank prefill pauses
    decode for its whole length);
  * the other ranks decode one token per running request;
  * the step lasts max(chunk step, decode step), where the chunk step is the
    longest chunk, stretched by the probe-E factor when two or more ranks
    prefill, and the decode step is
        alpha + beta * sum_r bucket(b_r) + gamma * sum_r sum_i context_i
    over the decoding ranks (probes A, B; bucket = compiled size 1, 4, 8);
  * a growth that finds no free block preempts the most recently admitted
    running request of the rank: its blocks are freed and it re-enters the head
    of the queue with prompt + generated tokens to recompute.

All step-model parameters come from data/exp/decode/fit.json (probes on an
idle server); none from the replays.

  python3 scripts/exp/lockstep_model.py --fit data/exp/e1/fit.json \\
      --decode-fit data/exp/decode/fit.json data/exp/e2/*/rounds.jsonl
"""
import argparse
import heapq
import json
import math
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memory_model as mm  # noqa: E402


def bucket(b):
    return 0 if b == 0 else (1 if b == 1 else (4 if b <= 4 else 8))


def simulate_lockstep(sessions, params, fit, dfit, B, block, subblock, max_seqs, t0, forced=frozenset()):
    a, b, c0 = fit["a"], fit["b"], fit["c0"]
    alpha, beta, gamma = dfit["alpha"], dfit["beta_bucket"], dfit["gamma_ctx"]
    stretch2, chunk = dfit["prefill_stretch_2"], dfit.get("chunk", 512)
    form, delta = dfit.get("form", "v1"), dfit.get("delta_rank", 0.0)
    spacing = params["spacing_s"]
    cap = params.get("cap") or 0
    ranks, cache, reqs = {}, {}, {}
    ev, seq = [], 0
    live, gate, preempt = 0, [], 0

    def push(t, kind, data):
        nonlocal seq
        heapq.heappush(ev, (t, seq, kind, data))
        seq += 1

    for s in sessions:
        push(t0 + s * spacing, "arrive", s)

    def rank_of(s):
        r = sessions[s][0]["dp_rank_requested"]
        if r not in ranks:
            rk = mm.Rank(B)
            rk.run = []          # running request ids in admission order
            rk.pf = None         # prefill in progress: dict(rid, rem, off, first)
            ranks[r] = rk
        return ranks[r]

    def evict_front(rk):
        bid, _ = rk.free.popitem(last=False)
        o = rk.owner.pop(bid, None)
        if o is not None and o[0] in cache:
            lst, tok = cache[o[0]]
            if bid in lst:
                j = lst.index(bid)
                cache[o[0]] = (lst[:j], min(tok, j * block))
        return bid

    def resident_prefix(rk, s):
        cb, ptok = cache.get(s, ([], 0))
        lead = []
        for idx, bid in enumerate(cb):
            if bid in rk.free and rk.owner.get(bid) == (s, idx):
                lead.append(bid)
            else:
                break
        return cb, ptok, lead

    def send(t, s, k):
        row = sessions[s][k]
        prev = sessions[s][k - 1] if k > 0 else None
        prefix = None if prev is None else (prev.get("prompt_tokens") or 0) + (prev.get("completion_tokens") or 0)
        rk = rank_of(s)
        rid = (s, k)
        reqs[rid] = dict(sess=s, k=k, sent=t, prompt=row.get("prompt_tokens") or row["expected_in"],
                         out=max(1, row.get("completion_tokens") or 1), prefix=prefix, gen=0, blocks=[],
                         forced=(row["session_id"], row["round_index"]) in forced, preempted=0,
                         queue_at_send=len(rk.queue) > 0, resident_at_send=False)
        cb, ptok, lead = resident_prefix(rk, s)
        reqs[rid]["resident_at_send"] = bool(cb) and len(lead) == len(cb)
        rk.queue.append(rid)
        rk.log.append((t, len(rk.queue), rk.held))

    def start_session(t, s):
        nonlocal live
        live += 1
        reqs[("door", s)] = {"door": t - (t0 + s * spacing)}
        send(t, s, 0)

    def release(t, rk, rid):
        q = reqs[rid]
        s = q["sess"]
        rk.held -= len(q["blocks"])
        fp, tail = q["prompt"] // block, q["prompt"] % block
        keep = fp + (1 if tail >= subblock else 0)
        reusable = q["blocks"][:keep]
        for idx, bid in enumerate(reusable):
            rk.owner[bid] = (s, idx)
        last = q["blocks"][-1] if q["blocks"] else None
        last_tokens = (q["prompt"] + q["gen"]) % block
        hashless = last is not None and 0 < last_tokens < subblock and len(q["blocks"]) > keep
        for bid in reversed(q["blocks"]):
            rk.free[bid] = None
            if hashless and bid == last:
                rk.free.move_to_end(bid, last=False)
        cache[s] = (list(reusable), q["prompt"])
        q["blocks"] = []

    def try_admit(t, rk):
        if rk.pf is not None or not rk.queue or len(rk.run) >= max_seqs:
            return
        rid = rk.queue[0]
        q = reqs[rid]
        s = q["sess"]
        total = q["prompt"] + q["gen"]          # a preempted request recomputes its generated tokens too
        need = math.ceil(total / block)
        own, src, cached = [], None, 0
        if (q["prefix"] is not None or q["gen"]) and not (q["forced"] and not q["gen"]):
            cb, ptok, lead = resident_prefix(rk, s)
            R = min(ptok, total - 1)
            f, sub = R // block, ((R % block) // subblock) * subblock
            if len(lead) >= f + (1 if sub else 0):
                own, src, cached = lead[:f], (lead[f] if sub else None), f * block + sub
            else:
                own = lead[:f]
                cached = len(own) * block
        if len(rk.free) - (1 if src is not None else 0) < need:
            if src is not None:
                rk.free.move_to_end(src)
            return
        if src is not None:
            del rk.free[src]
        for bid in own:
            del rk.free[bid]
        new = [evict_front(rk) for _ in range(need - len(own))]
        if src is not None:
            rk.owner.pop(src, None)
            rk.free[src] = None
        q["blocks"] = own + new
        if "start" not in q:
            q.update(start=t, cached=cached, cls=mm.classify(q["prefix"], cached, subblock))
        rk.queue.pop(0)
        rk.run.append(rid)
        rk.held += need
        rk.pf = dict(rid=rid, rem=total - cached, off=cached, first=True)
        rk.log.append((t, len(rk.queue), rk.held))

    def finish(t, rk, rid):
        nonlocal live
        q = reqs[rid]
        q["done"] = t + c0                   # client-side time, as the first token
        rk.run.remove(rid)
        release(t, rk, rid)
        rk.log.append((t, len(rk.queue), rk.held))
        s, k = q["sess"], q["k"]
        if k + 1 < len(sessions[s]):
            think = sessions[s][k + 1]["sent_monotonic_s"] - sessions[s][k]["done_monotonic_s"]
            push(t + max(0.0, think), "send", (s, k + 1))
        else:
            live -= 1
            cache.pop(s, None)
            if gate:
                start_session(t, gate.pop(0))

    t = t0
    while True:
        while ev and ev[0][0] <= t + 1e-12:
            _, _, kind, data = heapq.heappop(ev)
            if kind == "arrive":
                if cap and live >= cap:
                    gate.append(data)
                else:
                    start_session(t, data)
            elif kind == "send":
                send(t, *data)
        for rk in ranks.values():
            try_admit(t, rk)
        pf_ranks = [rk for rk in ranks.values() if rk.pf is not None]
        dec_ranks = [rk for rk in ranks.values() if rk.pf is None and rk.run]
        if not pf_ranks and not dec_ranks:
            if not ev:
                break
            t = ev[0][0]
            continue
        cstep = 0.0
        plan = {}
        for rk in pf_ranks:
            p = rk.pf
            m = min(chunk, p["rem"])
            ct = a * m + b * m * (p["off"] + m / 2)   # c0 is client/frontend latency, not engine time
            plan[id(rk)] = m
            cstep = max(cstep, ct)
        if len(pf_ranks) > 1:
            if "prefill_stretch" in dfit:        # measured for 1..4 ranks (probe G)
                cstep *= dfit["prefill_stretch"][min(len(pf_ranks), len(dfit["prefill_stretch"])) - 1]
            else:                                # probe E only: two ranks, extrapolated linearly
                cstep *= 1 + (stretch2 - 1) * (len(pf_ranks) - 1)
        dstep = 0.0
        if dec_ranks and form == "v2":        # all ranks pad to the largest bucket; the slowest rank's context
            dstep = alpha + beta * max(bucket(len(rk.run)) for rk in dec_ranks) + gamma * max(
                sum(reqs[r]["prompt"] + reqs[r]["gen"] for r in rk.run) for rk in dec_ranks) + delta * (len(dec_ranks) - 1)
        elif dec_ranks and form == "max":     # the rule the registration named, fitted on probes A, B only
            dstep = alpha + beta * max(bucket(len(rk.run)) for rk in dec_ranks) + gamma * max(
                sum(reqs[r]["prompt"] + reqs[r]["gen"] for r in rk.run) for rk in dec_ranks)
        elif dec_ranks:                       # v1 as run: sums over ranks (deviated from the registered maximum)
            dstep = alpha + beta * sum(bucket(len(rk.run)) for rk in dec_ranks) + gamma * sum(
                reqs[r]["prompt"] + reqs[r]["gen"] for rk in dec_ranks for r in rk.run)
        t += max(cstep, dstep)
        for rk in pf_ranks:
            p = rk.pf
            m = plan[id(rk)]
            p["rem"] -= m
            p["off"] += m
            p["first"] = False
            if p["rem"] <= 0:
                q = reqs[p["rid"]]
                rk.pf = None
                if "first" not in q:
                    q["first"] = t + c0          # the first token reaches the client c0 later
                    q["gen"] = 1
                if q["gen"] >= q["out"]:
                    finish(t, rk, p["rid"])
        for rk in dec_ranks:
            for rid in list(rk.run):
                if rid not in rk.run:
                    continue            # preempted earlier in this step
                q = reqs[rid]
                q["gen"] += 1
                if q["prompt"] + q["gen"] > len(q["blocks"]) * block:
                    if rk.free:
                        q["blocks"].append(evict_front(rk))
                        rk.held += 1
                    else:                # preempt the most recently admitted running request
                        preempt += 1
                        victim = rk.run[-1]
                        v = reqs[victim]
                        v["preempted"] += 1
                        rk.run.remove(victim)
                        release(t, rk, victim)
                        rk.queue.insert(0, victim)
                        if victim == rid:
                            continue
                        q["blocks"].append(evict_front(rk))
                        rk.held += 1
                    rk.log.append((t, len(rk.queue), rk.held))
                if q["gen"] >= q["out"]:
                    finish(t, rk, rid)
    return reqs, ranks, preempt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", required=True)
    ap.add_argument("--decode-fit", required=True)
    ap.add_argument("--blocks", type=int, default=51)
    ap.add_argument("--block-size", type=int, default=4096)
    ap.add_argument("--subblock", type=int, default=512)
    ap.add_argument("--max-seqs", type=int, default=8)
    ap.add_argument("--traces-dir", default="data/exp/traces")
    ap.add_argument("--min-decode", type=float, default=0.0,
                    help="leave turns with a shorter measured decode out of metric 1 (the registered metric has no filter)")
    ap.add_argument("--json")
    ap.add_argument("runs", nargs="+")
    args = ap.parse_args()
    fit = json.load(open(args.fit))
    dfit = json.load(open(args.decode_fit))
    args.decode, args.itl, args.think_cap = "lockstep", None, None

    def sim(sessions, params, fit_, t0, forced):
        return simulate_lockstep(sessions, params, fit_, dfit, args.blocks, args.block_size, args.subblock,
                                 args.max_seqs, t0, forced)
    out = []
    for p in args.runs:
        r = mm.analyse(p, fit, args, sim=sim)
        out.append(r)
        print(mm.fmt(r))
    if args.json:
        json.dump(out, open(args.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
