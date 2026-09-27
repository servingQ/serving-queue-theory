"""Hypothesis H-pin (docs/research-plan.md): a waiting request's cached
prefix is pinned (its blocks touched) when the request arrives and released
once the scheduler has admitted it, or when it finishes unscheduled, so
that it cannot be evicted while it waits. vLLM itself leaves it evictable
until the request is scheduled (the wait channel of Lecture 5)."""


def apply_pin(S):
    pins = {}
    orig_add = S.add_request
    orig_sched = S.schedule
    orig_free = S._free_request

    def unpin(self, rid):
        bl = pins.pop(rid, None)
        if bl:
            self.kv_cache_manager.block_pool.free_blocks(reversed(bl))

    def add_request(self, request):
        orig_add(self, request)
        if request.num_computed_tokens == 0 and request.request_id in self.requests:
            blocks = self.kv_cache_manager.get_computed_blocks(request)[0]
            bl = [b for grp in blocks.blocks for b in grp]
            if bl:
                self.kv_cache_manager.block_pool.touch(bl)
                pins[request.request_id] = bl

    def schedule(self, *a, **k):
        so = orig_sched(self, *a, **k)
        for nr in so.scheduled_new_reqs:
            unpin(self, nr.req_id)
        return so

    def free_request(self, request, *a, **k):
        unpin(self, request.request_id)
        return orig_free(self, request, *a, **k)

    S.add_request = add_request
    S.schedule = schedule
    S._free_request = free_request
    return pins
