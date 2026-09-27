"""Step tracer for a served vLLM v1 engine (loaded through PYTHONPATH by
serve_gpu.sh when STEPTRACE is set). Every scheduler step writes one JSON
line to $STEPTRACE.<pid>: the monotonic time of `schedule()` and of the
`update_from_output()` that consumes it, and per scheduled request the
tokens, the tokens computed before, the prompt length and the blocks held.
These are ROUTE's step quantities (ntok, npre, ndec, kvb, attn), measured
on the serving path (async scheduling included)."""
import json
import os
import time

_path = os.environ.get("STEPTRACE")
if _path:
    try:
        import vllm.v1.core.sched.scheduler as _sm

        _S = _sm.Scheduler
        _orig_schedule = _S.schedule
        _orig_update = _S.update_from_output
        _f = [None]
        _pending = {}

        def _out():
            if _f[0] is None:
                _f[0] = open(f"{_path}.{os.getpid()}", "a", buffering=1)
            return _f[0]

        def schedule(self, *a, **k):
            t = time.monotonic()
            so = _orig_schedule(self, *a, **k)
            if so.total_num_scheduled_tokens:
                reqs = []
                for rid, n in so.num_scheduled_tokens.items():
                    r = self.requests.get(rid)
                    if r is None:
                        continue
                    held = len(self.kv_cache_manager.get_block_ids(rid)[0]) * self.block_size
                    reqs.append([n, r.num_computed_tokens - n, r.num_prompt_tokens, held])
                _pending[id(so)] = (t, reqs)
            return so

        def update_from_output(self, so, mro, *a, **k):
            t = time.monotonic()
            st = _pending.pop(id(so), None)
            if st is not None:
                _out().write(json.dumps({"t_sched": st[0], "t_done": t, "reqs": st[1],
                                         "free": self.kv_cache_manager.block_pool.get_num_free_blocks()}) + "\n")
            return _orig_update(self, so, mro, *a, **k)

        _S.schedule = schedule
        _S.update_from_output = update_from_output
    except Exception as e:  # never break the server
        print("steptrace: disabled:", e)

# Hypothesis H-pin (docs/research-plan.md): see pinpatch.py.
if os.environ.get("PIN_WAITING"):
    try:
        import vllm.v1.core.sched.scheduler as _sm2
        from pinpatch import apply_pin

        apply_pin(_sm2.Scheduler)
    except Exception as e:
        print("pin: disabled:", e)
