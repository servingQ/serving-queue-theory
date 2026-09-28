#!/usr/bin/env python3
"""Closed-loop replica model with a block-level KV pool, for the testbed
replays (long-context replay E2, short-context replay E2b).

What it models (the engine that served the replays is vllm-rbln's
RBLNScheduler on upstream vLLM 0.26 block management; see
research/memory-model.md for the code lines):

  client   session i arrives at t0 + i * spacing and passes a FIFO gate that
           admits at most `cap` live sessions (0 = no gate); within a session,
           turn k+1 is sent `think` seconds after the model's completion of
           turn k (think = the trace's gap, capped as in the replay);
  memory   per rank, a pool of B allocatable blocks of `block` tokens with a
           block-level LRU free queue: completed requests free their blocks
           tail first; an admission first touches the session's own leading
           cached blocks, then takes blocks from the LRU end, evicting other
           sessions' cached prefixes; a request is admitted only if the free
           queue (which includes its own unreferenced cached blocks) holds its
           whole prompt (`full_sequence_must_fit`); during decode a request
           grows by one block each time its tokens cross a block boundary (a
           growth that finds no free block is counted as a preemption and not
           allocated; the victim is not freed, so the count is an upper bound);
           a sub-block hit copies its old tail into a new block, so it needs one
           free block more than a miss, and the old tail returns ownerless to
           the MRU end; only the previous prompt is reusable (the replayer
           sends the trace's text, not the generated tokens);
  queue    per rank, strict FCFS: the head blocks everyone behind it; one
           prefill at a time, and at most `max_seqs` running requests;
  cost     prefill time P(n, K) + c0 from the cost fit (E1), with K the
           model's own cached tokens (the hit/miss class is an output);
           decode time is the observed done - first_token of the same turn
           ("given measured decode", the default), output * itl
           (`--decode idle`), or output * itl plus the own rank's prefill
           pauses (`--decode nocross`); the last two are counterfactuals.

Hits are counted at the sub-block granularity (512 tokens) when all of the
previous prompt's blocks are resident, else at whole blocks. Classes use the
rule of analyze_e2.py (which compares with the previous prompt plus completion).

Outputs per run: classes and mean TTFT (model vs observed), door wait,
per-rank means, agreement metrics, preemptions, and a time-series check of
each rank's waiting count and running blocks against /metrics.

Usage:
  python3 scripts/exp/memory_model.py --fit data/exp/e1/fit.json \
      [--blocks 51] [--decode observed|idle] [--json out.json] data/exp/e2/*/rounds.jsonl
"""
import argparse
import heapq
import json
import math
import os
import statistics as st
from collections import OrderedDict

CLASSES = ["first", "hit", "partial", "miss"]


def classify(prefix, cached, subblock):
    if prefix is None:
        return "first"
    if prefix > 0 and cached >= min(0.9 * prefix, prefix - subblock):
        return "hit"
    return "partial" if cached > 0 else "miss"


def forced_turns(tag, traces_dir):
    """Forced-miss arm of the short-context replay: turns flagged forced_miss in
    the derived trace carry a nonce at the head of the prompt, so they reuse no
    cached prefix."""
    if "_m10" not in tag:
        return set()
    name = "short_m10" + ("_s1" if tag.endswith("_s1") else "") + ".jsonl"
    path = os.path.join(traces_dir, name)
    out = set()
    for l in open(path):
        s = json.loads(l)
        for k, q in enumerate(s["requests"]):
            if q.get("forced_miss"):
                out.add((s["id"], k))
    return out


def load_run(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    # a few E2b turns completed without a recorded first token (chunks = 0): they stay in
    # the simulation (they hold the server) and are left out of the TTFT comparison
    rows = [r for r in rows if not r.get("error") and r.get("done_monotonic_s")]
    d = os.path.dirname(path)
    params = json.load(open(os.path.join(d, "params.json")))
    meta = json.load(open(os.path.join(d, "meta.json"))) if os.path.exists(os.path.join(d, "meta.json")) else {}
    sessions = {}
    for r in rows:
        sessions.setdefault(r["session_index"], []).append(r)
    for s in sessions.values():
        s.sort(key=lambda r: r["round_index"])
        assert [r["round_index"] for r in s] == list(range(len(s))), "a session has a missing turn"
    assert sorted(sessions) == list(range(len(sessions))), "session_index is not contiguous"
    return rows, sessions, params, meta, d


class Rank:
    def __init__(self, blocks):
        self.free = OrderedDict((b, None) for b in range(blocks))  # front = evicted first (LRU)
        self.owner = {}          # block -> (sess, idx): a reusable cached block of that session's prompt
        self.queue = []          # waiting request ids, FCFS
        self.pf_until = 0.0      # exclusive prefill server busy until
        self.running = 0
        self.held = 0            # blocks held by running requests
        self.log = []            # (t, waiting, held) after every change
        self.tick_at = None      # time of the pending prefill-server wake-up
        self.decoding = set()    # requests in decode (for --decode nocross)


def simulate(sessions, params, fit, B, block, subblock, max_seqs, decode, itl, think_cap, t0, forced=frozenset()):
    a, b, c0 = fit["a"], fit["b"], fit["c0"]
    spacing = params["spacing_s"]
    cap = params.get("cap") or 0
    ranks = {}
    cache = {}                   # sess -> (reusable block ids in order, reusable tokens = previous prompt)
    reqs = {}
    ev = []
    seq = 0

    def push(t, kind, data):
        nonlocal seq
        heapq.heappush(ev, (t, seq, kind, data))
        seq += 1

    for s in sessions:           # session_index is contiguous (asserted in load_run)
        push(t0 + s * spacing, "arrive", s)
    live = 0
    gate = []
    preempt = 0

    def rank_of(s):
        r = sessions[s][0]["dp_rank_requested"]
        if r not in ranks:
            ranks[r] = Rank(B)
        return ranks[r]

    def evict_front(rk):
        bid, _ = rk.free.popitem(last=False)
        o = rk.owner.pop(bid, None)
        if o is not None and o[0] in cache:          # truncate that session's reusable prefix
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
        rid = (s, k)
        prev = sessions[s][k - 1] if k > 0 else None
        # the class rule of analyze_e2.py compares with previous prompt + completion
        prefix = None if prev is None else (prev.get("prompt_tokens") or 0) + (prev.get("completion_tokens") or 0)
        out = row.get("completion_tokens") or 0
        rk = rank_of(s)
        cb, ptok, lead = resident_prefix(rk, s)
        reqs[rid] = dict(sess=s, k=k, sent=t, prompt=row.get("prompt_tokens") or row["expected_in"], out=out,
                         prefix=prefix, obsD=(max(0.0, row["done_monotonic_s"] - row["first_token_monotonic_s"])
                                            if row.get("first_token_monotonic_s") else out * itl),
                         blocks=[], forced=(row["session_id"], row["round_index"]) in forced, ver=0,
                         queue_at_send=len(rk.queue) > 0,  # another request waiting (as the observed side)
                         resident_at_send=bool(cb) and len(lead) == len(cb))
        rk.queue.append(rid)
        rk.log.append((t, len(rk.queue), rk.held))

    def start_session(t, s):
        nonlocal live
        live += 1
        reqs[("door", s)] = {"door": t - (t0 + s * spacing)}
        send(t, s, 0)

    def try_admit(t, rk):
        while rk.queue and rk.pf_until <= t + 1e-9 and rk.running < max_seqs:
            rid = rk.queue[0]
            q = reqs[rid]
            s = q["sess"]
            need = math.ceil(q["prompt"] / block)
            own, src, cached = [], None, 0
            if q["prefix"] is not None and not q["forced"]:
                cb, ptok, lead = resident_prefix(rk, s)
                R = min(ptok, q["prompt"] - 1)        # reusable: the previous prompt (not the generated tokens)
                f, sub = R // block, ((R % block) // subblock) * subblock
                if len(lead) >= f + (1 if sub else 0):
                    own = lead[:f]
                    src = lead[f] if sub else None    # sub-block hit: the tail is copied, not reused
                    cached = f * block + sub
                else:
                    own = lead[:f]
                    cached = len(own) * block
            # the free count excludes the touched copy source (full_sequence_must_fit)
            if len(rk.free) - (1 if src is not None else 0) < need:
                if src is not None:
                    rk.free.move_to_end(src)          # a failed match is released to the MRU end
                return                                # FCFS head-of-line: nobody behind it is scheduled
            if src is not None:
                del rk.free[src]
            for bid in own:
                del rk.free[bid]
            new = [evict_front(rk) for _ in range(need - len(own))]
            if src is not None:                       # after the copy the source returns, stale, to the MRU end
                rk.owner.pop(src, None)
                rk.free[src] = None
            n, K = q["prompt"] - cached, cached
            P = c0 + a * n + b * n * (K + n / 2)
            q.update(start=t, P=P, cached=cached, blocks=own + new,
                     cls=classify(q["prefix"], cached, subblock))
            rk.queue.pop(0)
            rk.pf_until = t + P
            rk.running += 1
            rk.held += need
            rk.log.append((t, len(rk.queue), rk.held))
            push(t + P, "pf_done", rid)
            if decode == "nocross":                   # an admitted prefill pauses the rank's decodes
                for other in rk.decoding:
                    o = reqs[other]
                    o["ver"] += 1
                    o["dec_end"] += P
                    o["grow_t"] = [g + P if g > t else g for g in o["grow_t"]]
                    schedule_decode(t, other)

    def schedule_decode(t, rid):
        q = reqs[rid]
        for g in q["grow_t"]:
            if g > t:
                push(g, "grow", (rid, q["ver"]))
        push(q["dec_end"], "done", (rid, q["ver"]))

    while ev:
        t, _, kind, data = heapq.heappop(ev)
        if kind == "arrive":
            if cap and live >= cap:
                gate.append(data)
            else:
                start_session(t, data)
        elif kind == "pf_done":
            q = reqs[data]
            q["first"] = t
            rk = rank_of(q["sess"])
            D = q["obsD"] if decode == "observed" else q["out"] * itl
            tot0 = q["prompt"]
            q["grow_t"] = [t + D * (m - tot0 + 1) / max(1, q["out"])
                           for m in range(math.ceil(tot0 / block) * block, tot0 + q["out"], block)]
            q["dec_end"] = t + D
            rk.decoding.add(data)
            schedule_decode(t, data)
        elif kind == "grow":
            rid, ver = data
            q = reqs[rid]
            if ver != q["ver"]:
                continue
            rk = rank_of(q["sess"])
            if rk.free:
                q["blocks"].append(evict_front(rk))
                rk.held += 1
                rk.log.append((t, len(rk.queue), rk.held))
            else:
                preempt += 1
        elif kind == "done":
            rid, ver = data
            q = reqs[rid]
            if ver != q["ver"]:
                continue
            q["done"] = t
            s = q["sess"]
            rk = rank_of(s)
            rk.decoding.discard(rid)
            rk.running -= 1
            rk.held -= len(q["blocks"])
            # reusable: the blocks of the prompt; the tail block only if it has a sub-block hash
            fp, tail = q["prompt"] // block, q["prompt"] % block
            keep = fp + (1 if tail >= subblock else 0)
            reusable = q["blocks"][:keep]
            for idx, bid in enumerate(reusable):
                rk.owner[bid] = (s, idx)
            last = q["blocks"][-1] if q["blocks"] else None
            last_tokens = (q["prompt"] + q["out"]) % block
            hashless = last is not None and 0 < last_tokens < subblock and len(q["blocks"]) > keep
            for bid in reversed(q["blocks"]):         # tail first to the MRU end (evicted first among them)
                if hashless and bid == last:
                    rk.free[bid] = None
                    rk.free.move_to_end(bid, last=False)  # a block without a hash goes to the front
                else:
                    rk.free[bid] = None
            cache[s] = (list(reusable), q["prompt"])
            rk.log.append((t, len(rk.queue), rk.held))
            k = q["k"]
            if k + 1 < len(sessions[s]):
                nxt = sessions[s][k + 1]
                think = nxt["sent_monotonic_s"] - sessions[s][k]["done_monotonic_s"]
                if think_cap is not None:
                    think = min(think, think_cap)
                push(t + max(0.0, think), "send", (s, k + 1))
            else:
                live -= 1
                cache.pop(s, None)
                if gate:
                    start_session(t, gate.pop(0))
        elif kind == "send":
            send(t, *data)
        for rk in ranks.values():
            try_admit(t, rk)
        for rk in ranks.values():                     # one wake-up per rank for the end of its prefill
            if rk.queue and rk.pf_until > t and rk.tick_at != rk.pf_until:
                rk.tick_at = rk.pf_until
                push(rk.pf_until, "tick", None)
    return reqs, ranks, preempt


def spearman(x, y):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(o):
            r[i] = pos
        return r
    if len(x) < 3:
        return float("nan")
    rx, ry = rank(x), rank(y)
    return pearson(rx, ry)


def pearson(x, y):
    if len(x) < 3 or st.pstdev(x) == 0 or st.pstdev(y) == 0:
        return float("nan")
    mx, my = st.mean(x), st.mean(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) * st.pstdev(x) * st.pstdev(y))


def series_check(ranks, rank_ids, metrics_path, off, t_lo, t_hi):
    """Waiting count and running blocks per rank: model (step functions) vs
    /metrics samples (vllm:num_requests_waiting, kv_cache_usage_perc * (B))."""
    if not metrics_path or not os.path.exists(metrics_path) or off is None:
        return {}
    samples = [json.loads(l) for l in open(metrics_path) if l.strip()]
    out = {}
    for r, rk in zip(rank_ids, [ranks[i] for i in rank_ids]):
        log = sorted(rk.log, key=lambda x: x[0])  # stable: keep the order of changes at equal times
        times = [x[0] for x in log]
        ow, mw, ok_, mk = [], [], [], []
        import bisect
        for smp in samples:
            tm = smp["t"] - off
            if not (t_lo <= tm <= t_hi):
                continue
            w = k = None
            for url, m in smp.items():
                if url == "t":
                    continue
                for key, v in m.items():
                    if f'engine="{r}"' in key:
                        if key.startswith("vllm:num_requests_waiting"):
                            w = v
                        elif key.startswith("vllm:kv_cache_usage_perc"):
                            k = v
            if w is None:
                continue
            i = bisect.bisect_right(times, tm) - 1
            state = log[i] if i >= 0 else (tm, 0, 0)
            ow.append(w)
            mw.append(state[1])
            if k is not None:
                ok_.append(k)
                mk.append(state[2])
        if ow:
            out[r] = dict(obs_wait=st.mean(ow), model_wait=st.mean(mw), corr_wait=pearson(ow, mw),
                          obs_kv=st.mean(ok_) if ok_ else float("nan"),
                          model_blocks=st.mean(mk) if mk else float("nan"),
                          corr_kv=pearson(ok_, mk) if ok_ else float("nan"), n=len(ow))
    return out


def analyse(path, fit, args, sim=None):
    rows, sessions, params, meta, d = load_run(path)
    t0 = sessions[0][0]["sent_monotonic_s"] - (sessions[0][0].get("admission_wait_s") or 0.0)
    forced = forced_turns(params.get("tag", ""), args.traces_dir)
    if sim is None:
        reqs, ranks, preempt = simulate(sessions, params, fit, args.blocks, args.block_size, args.subblock,
                                        args.max_seqs, args.decode, args.itl, args.think_cap, t0, forced)
    else:
        reqs, ranks, preempt = sim(sessions, params, fit, t0, forced)
    # observed classes and TTFT per (session, round)
    obs = {}
    for s, lst in sessions.items():
        for k, r in enumerate(lst):
            prev = lst[k - 1] if k else None
            prefix = None if prev is None else (prev.get("prompt_tokens") or 0) + (prev.get("completion_tokens") or 0)
            cached = r.get("cached_tokens") or 0
            n, K = r["prompt_tokens"] - cached, cached
            P = fit["c0"] + fit["a"] * n + fit["b"] * n * (K + n / 2)
            if not r.get("first_token_monotonic_s"):
                continue
            obs[(s, k)] = dict(ttft=r["ttft_s"], cls=classify(prefix, cached, args.subblock),
                               rank=r["dp_rank_requested"], door=r.get("admission_wait_s") or 0.0,
                               sent=r["sent_monotonic_s"], first=r["first_token_monotonic_s"],
                               start=r["first_token_monotonic_s"] - P,
                               think=(r["sent_monotonic_s"] - prev["done_monotonic_s"]) if prev else None,
                               D=r["done_monotonic_s"] - r["first_token_monotonic_s"])
    # observed facts about misses: think time before each class, arrival to a queue
    # (another request of the rank sent earlier and not yet started), FCFS order
    by_rank = {}
    for o in obs.values():
        by_rank.setdefault(o["rank"], []).append(o)
    inversions = 0
    for lst in by_rank.values():
        lst.sort(key=lambda o: o["sent"])
        for j, o in enumerate(lst):
            o["queue_at_send"] = any(x["sent"] < o["sent"] < x["start"] for x in lst[max(0, j - 60):j])
        firsts = [o["first"] for o in lst]
        inversions += sum(1 for j in range(1, len(firsts)) if firsts[j] < max(firsts[:j]))
    pairs = [(obs[k], reqs[k]) for k in obs if k in reqs and "first" in reqs[k]]
    res = {"run": os.path.basename(d), "B": args.blocks, "decode": args.decode, "n": len(pairs),
           "unfinished": len(obs) - len(pairs), "no_first_token": len(rows) - len(obs)}
    for c in CLASSES:
        o = [p["ttft"] for p, _ in pairs if p["cls"] == c]
        m = [q["first"] - q["sent"] for _, q in pairs if q["cls"] == c]
        res[c] = dict(n_obs=len(o), n_model=len(m), obs=st.mean(o) if o else float("nan"),
                      model=st.mean(m) if m else float("nan"))
    o_all = [p["ttft"] for p, _ in pairs]
    m_all = [q["first"] - q["sent"] for _, q in pairs]
    res["all"] = dict(obs=st.mean(o_all), model=st.mean(m_all),
                      obs_p99=sorted(o_all)[int(0.99 * (len(o_all) - 1))],
                      model_p99=sorted(m_all)[int(0.99 * (len(m_all) - 1))])
    fu = [(p, q) for p, q in pairs if p["cls"] != "first"]
    res["hit_agreement"] = st.mean([(p["cls"] == "hit") == (q["cls"] == "hit") for p, q in fu]) if fu else float("nan")
    res["class_agreement"] = st.mean([p["cls"] == q["cls"] for p, q in fu]) if fu else float("nan")
    # per observed class: median relative error and Spearman (turn by turn)
    res["by_obs_class"] = {}
    for c in CLASSES:
        sel = [(p["ttft"], q["first"] - q["sent"]) for p, q in pairs if p["cls"] == c]
        if sel:
            res["by_obs_class"][c] = dict(
                mre=st.median(abs(m - o) / o for o, m in sel if o > 0),
                spearman=spearman([o for o, _ in sel], [m for _, m in sel]))
    # Cohen's kappa for hit vs non-hit
    if fu:
        po = res["hit_agreement"]
        pa = st.mean([p["cls"] == "hit" for p, _ in fu]); pb = st.mean([q["cls"] == "hit" for _, q in fu])
        pe = pa * pb + (1 - pa) * (1 - pb)
        res["kappa"] = (po - pe) / (1 - pe) if pe < 1 else float("nan")
    res["facts"] = {}
    for c in ["hit", "partial", "miss"]:
        th = [p["think"] for p, _ in pairs if p["cls"] == c and p["think"] is not None]
        qo = [p["queue_at_send"] for p, _ in pairs if p["cls"] == c]
        qm = [q["queue_at_send"] for _, q in pairs if q["cls"] == c]
        res["facts"][c] = dict(think_obs=st.mean(th) if th else float("nan"),
                               gap30_obs=st.mean([x >= 29.0 for x in th]) if th else float("nan"),
                               queue_obs=st.mean(qo) if qo else float("nan"),
                               queue_model=st.mean(qm) if qm else float("nan"))
    nh = [q for _, q in pairs if q["cls"] in ("partial", "miss")]
    res["facts"]["nonhit_resident_at_send_model"] = st.mean([q["resident_at_send"] for q in nh]) if nh else float("nan")
    res["fcfs_inversions_obs"] = inversions
    # per-turn decode duration, model against measured (pre-registered metric 1)
    dd = [(p["D"], q["done"] - q["first"]) for p, q in pairs if "done" in q and p["D"] > getattr(args, "min_decode", 0.0)]
    if dd:
        res["decode_fit"] = dict(mre=st.median(abs(m - o) / o for o, m in dd),
                             spearman=spearman([o for o, _ in dd], [m for _, m in dd]),
                             obs_mean=st.mean(o for o, _ in dd), model_mean=st.mean(m for _, m in dd), n=len(dd))
    res["log_corr"] = pearson([math.log(max(1e-3, x)) for x in o_all], [math.log(max(1e-3, x)) for x in m_all])
    res["per_rank"] = {}
    for r in sorted({p["rank"] for p, _ in pairs}):
        o = [p["ttft"] for p, _ in pairs if p["rank"] == r]
        m = [q["first"] - q["sent"] for p, q in pairs if p["rank"] == r]
        mo = [p["ttft"] for p, _ in pairs if p["rank"] == r and p["cls"] == "miss"]
        res["per_rank"][r] = dict(n=len(o), obs=st.mean(o), model=st.mean(m), obs_miss=len(mo),
                                  model_miss=sum(1 for p, q in pairs if p["rank"] == r and q["cls"] == "miss"))
    doors_o = [p["door"] for (s, k), p in obs.items() if k == 0]
    doors_m = [reqs[("door", s)]["door"] for s in sessions if ("door", s) in reqs]
    res["door"] = dict(obs=st.mean(doors_o), model=st.mean(doors_m))
    res["preemptions_model"] = preempt
    # /metrics time series
    t_lo = min(q["sent"] for _, q in pairs)
    t_hi = max(q.get("done", q["first"]) for _, q in pairs)
    res["series"] = series_check(ranks, sorted(ranks), os.path.join(d, "metrics.jsonl"),
                                 meta.get("epoch_minus_monotonic"), t_lo, t_hi)
    return res


def fmt(res):
    lines = []
    r = res
    lines.append(f"{r['run']}  B={r['B']}  decode={r['decode']}  turns {r['n']} (unfinished {r['unfinished']})")
    lines.append("  class      n obs/model    TTFT obs / model (s)")
    for c in CLASSES:
        x = r[c]
        lines.append(f"  {c:8s} {x['n_obs']:4d} / {x['n_model']:<4d}   {x['obs']:7.1f} / {x['model']:7.1f}")
    a = r["all"]
    lines.append(f"  all                 {a['obs']:7.1f} / {a['model']:7.1f}   p99 {a['obs_p99']:.0f} / {a['model_p99']:.0f}")
    lines.append(f"  hit agreement {r['hit_agreement']:.2f}  class agreement {r['class_agreement']:.2f}  "
                 f"log-TTFT corr {r['log_corr']:.2f}  door wait {r['door']['obs']:.0f} / {r['door']['model']:.0f} s  "
                 f"preemptions (model) {r['preemptions_model']}")
    f = r["facts"]
    lines.append(f"  kappa {r.get('kappa', float('nan')):.2f}  FCFS inversions (obs, first tokens, no tolerance) {r['fcfs_inversions_obs']}  "
                 f"non-hits whose prefix was resident at send (model) {f['nonhit_resident_at_send_model']:.2f}")
    if "decode_fit" in r:
        d = r["decode_fit"]
        lines.append(f"  decode duration per turn: MRE {d['mre']:.2f}  Spearman {d['spearman']:.2f}  "
                     f"mean obs {d['obs_mean']:.1f}s / model {d['model_mean']:.1f}s  (n {d['n']})")
    lines.append("  think before / arrived to a queue (obs, model): " + "  ".join(
        f"{c} {f[c]['think_obs']:.1f}s (>=29s {f[c]['gap30_obs']:.2f}) {f[c]['queue_obs']:.2f}/{f[c]['queue_model']:.2f}" for c in ["hit", "partial", "miss"]))
    lines.append("  by observed class: " + "  ".join(
        f"{c} MRE {v['mre']:.2f} rho {v['spearman']:.2f}" for c, v in r["by_obs_class"].items()))
    lines.append("  per rank (TTFT obs/model, misses obs/model): " + "  ".join(
        f"r{k} {v['obs']:.1f}/{v['model']:.1f} ({v['obs_miss']}/{v['model_miss']})" for k, v in r["per_rank"].items()))
    if r["series"]:
        lines.append("  /metrics per rank (waiting obs/model corr; running blocks model, kv% obs corr): " + "  ".join(
            f"r{k} {v['obs_wait']:.2f}/{v['model_wait']:.2f} {v['corr_wait']:.2f}; {v['model_blocks']:.1f} {v['corr_kv']:.2f}"
            for k, v in r["series"].items()))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", required=True)
    ap.add_argument("--blocks", type=int, default=51, help="allocatable KV blocks per rank (52 minus the null block)")
    ap.add_argument("--block-size", type=int, default=4096)
    ap.add_argument("--subblock", type=int, default=512)
    ap.add_argument("--max-seqs", type=int, default=8)
    ap.add_argument("--decode", choices=["observed", "idle", "nocross"], default="observed",
                    help="observed: measured decode time; idle: output x itl; "
                         "nocross: output x itl plus the own rank's prefill pauses (no cross-rank stretch)")
    ap.add_argument("--itl", type=float, default=0.017, help="idle inter-token latency for --decode idle")
    ap.add_argument("--think-cap", type=float, default=None)
    ap.add_argument("--traces-dir", default="data/exp/traces", help="derived traces with forced_miss flags (E2b)")
    ap.add_argument("--json")
    ap.add_argument("runs", nargs="+")
    args = ap.parse_args()
    fit = json.load(open(args.fit))
    out = []
    for p in args.runs:
        r = analyse(p, fit, args)
        out.append(r)
        print(fmt(r))
    if args.json:
        json.dump(out, open(args.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
