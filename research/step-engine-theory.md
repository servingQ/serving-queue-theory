# Step-engine theory: serving proofs start from serQ

Started 2026-10-01. Working rule from the user: every proof about a serving
system starts from serQ's operational semantics (the step engine: budget,
scheduling order, iteration cost; pools and `hold`). Queue models (M/G/1,
PS, M/M/1//N) are not assumed about a replica; they enter as abstraction
theorems derived from the step semantics under stated conditions, or as
pure queueing lemmas.

## Why

* serQ's step engine is the object checked against the real vLLM v1
  scheduler (six oracle scenarios on a fake runner, the A100 engine, serQ
  and Lean; the 333-session trace, 3 321 of 3 321 requests with identical
  first-token time and cached tokens; serQ `docs/language.md` §7).
* The paper's prefill model (one FIFO server, per-request work
  `c0 + a n + b n (K + n/2)`) was never checked against the engine, and it
  loses prefill batching: vLLM fills the budget in arrival order with as
  many waiting prefills as fit (`scheduler.py:872`, no per-request cap by
  default, `long_prefill_token_threshold = 0`), so the per-iteration cost
  is shared by every prefill in the iteration. On the RBLN testbed
  (`serve exclusive prefill`) one prefill runs per step and the
  per-request form is the engine's.

## First numerical check (2026-10-01)

`scripts/step_engine/prefill_only.sq`: vLLM v1 step engine, A100 cost fit
of serQ `examples/replay/vllm_replay.sq` (`c_it = 4 ms` per iteration,
`a = 51.5 µs`/token, `b = 4.02e-9` s/token², budget 512), Poisson arrivals,
prefill only (one output token), no prefix cache, no memory limit.
`scripts/step_engine/sandwich_check.py` recomputes, on the same arrivals
and sizes, two FIFO single-server (Lindley) recursions per request:

* lower: work `S = a m + b m²/2` (the per-iteration cost fully shared);
* upper: work `S + c_it (1 + m/B)`, plus one iteration
  `δ = c_it + a B + b B (m_max + B/2)` at the end.

| λ (/s) | sizes (p_long) | ρ of S | mean TTFT lower / engine / upper (s) | violations |
|---|---|---|---|---|
| 10 | 64 / 2048 (0.2) | 0.25 | 0.042 / 0.057 / 0.060 | 0 / 0 |
| 20 | 64 / 2048 (0.2) | 0.51 | 0.077 / 0.114 / 0.135 | 0 / 0 |
| 25 | 64 / 2048 (0.2) | 0.64 | 0.111 / 0.184 / 0.270 | 0 / 0 |
| 100 | 64 only | 0.33 | 0.004 / 0.012 / 0.021 | 0 / 0 |
| 200 | 64 only | 0.66 | 0.007 / 0.025 / 837 (unstable) | 0 / 0 |
| 300 | 64 only | 0.99 | 0.16 / 184 / 1760 | 0 / 0 |
| 150 | 32 / 4096 (0.05) | 2.07 | 677 / 853 / 1236 (overloaded) | 0 / 0 |

Every request of every run (up to 788 227) lies inside the bracket and
completes in arrival order. The bracket is wide where it matters: with
short prefills the upper recursion is unstable while the engine is not
(the iteration cost is shared), and the lower one misses the wait for the
running iteration. A FIFO server with per-token work `a + c_it/B` plus one
iteration (`c_it`) is within 0.5–3 % of the engine when long prefills are
present, but 45 % low for 64-token prefills at λ = 200 (iterations run
below the budget, so the per-iteration cost is not shared by B tokens).
Simulator output, not a measurement (AGENTS.md rule 7). The program it runs
(`admit via engine`, `growing kv`) is wider than the fragment
`serq_engine_lower` covers (nobody waiting for the engine, no growth past an
allocation): the check is evidence that the bracket holds beyond the
theorem, not an instance of it.

## Status (2026-10-02)

serQ's Lean model moved into serQ (`lean/`, serQ #245) and became the
interpreter's: event-driven with an iteration cost (#247, #248),
three differences found by differential testing fixed (#249, #250), random
cases and the 333-session trace checked in CI (#251). serQ #252 proves that
an iteration of `Exec.assign` (nothing growing past its allocation, nobody
waiting for the engine) is the greedy fill of the budget in serving order
(`assign_eq_fillIter`, `fillAmounts_fifo`).

`lean/ServingQueueTheory/StepEngine.lean` now starts from that engine:
`serq_machines_lower` reads each iteration's tokens off serQ's machine (the
`assign` that `startIteration` calls, which is `fillIter` by serQ's
`assign_iter_eq_fillIter`; a request's tokens as `Exec.endIteration`
subtracts them) and proves every request completes no earlier than the FIFO
prefill server with work `a m + b m (K + m/2)`. What is derived from serQ is
one iteration's fill and its token accounting. What it still assumes about a
run:

- every resident is eligible (`D.only = none`, explicit since the v0.1.3
  migration);
- nobody waits for the engine during an iteration and no growth passes an
  allocation (serQ #253 is the admission case);
- the residents are the arrived unfinished requests in arrival order, as
  prefill jobs wanting what they have left (`hres`, `hjob`), so that serving
  order (`admSeq`), request index and arrival order agree;
- each iteration lasts at least its chunks' cost (`hdur`), which `D.cost`
  must dominate on serQ's ℕ clock.

Proving those as invariants of `Exec.step` on the prefill-only fragment is
the next step; then the upper bound and the bulk-service analysis below.

## Theorem plan

1. **Core engine** (the iteration is done: serQ's `Exec` itself, see Status;
   the duration and the run invariants are not): the serQ fragment
   "one `hold` on an engine-admitted pool with unbounded memory, `prefill m`
   (then `decode o`)", no chunk cap, admission order; iterations fill the
   budget greedily in arrival order; duration `τ = c + a P + b attn`.
   Refinement to `SerqExec` on this fragment is a separate target; until
   then the oracle scenarios are checked on both by evaluation.
2. **Token FIFO**: the tokens processed by any time form a prefix of the
   arrival-ordered token stream; requests complete in arrival order.
3. **Lower bound**: `D_k ≥ max_{i≤k} (A_i + Σ_{l=i}^{k} S_l)`, the FIFO
   recursion with `S = a m + b attn` (attention is additive over chunks).
4. **Upper bound**: `D_k ≤` the FIFO recursion with
   `S + c (1 + m/B)`, plus `δ`.
5. **Sharper**: the exact iteration recursion is a bulk-service FIFO
   queue (service time depends on the batch). Target: the price of a miss
   in that queue, or a bracket tighter than 3–4.
6. Decode in the same iteration (`d·decoders + e·kv_decode`, budget
   `B − decoders`), then exclusive prefill (RBLN) as the other scheduler.
