# Simulator design

Design of the discrete-event simulator used in paper §7. Status: design
only, nothing implemented. Read `docs/research-plan.md` first.

## 1. Why a simulator, and where it is not needed

The closed-form model (paper §§2–6) ignores continuous batching,
correlated turn arrivals, block-level KV fragmentation, and bandwidth
sharing on transfers. The testbed has all of these, but it is slow to
sweep and cannot compute counterfactuals. For example, it cannot run the
exact eviction optimum on the same arrival sequence. The simulator sits
between the two.

| Experiment | Simulator needed? | Reason |
|------------|-------------------|--------|
| E1 calibration | no | testbed profiling only; the simulator *consumes* E1 |
| E2 variance | yes, for the hit-rate sweep | the testbed measures CV² at the natural hit rate; the simulator sweeps `p` by forcing evictions on identical traces |
| E3 offloading | yes | concurrency × policy × tier bandwidth grid is too large for the testbed; the testbed checks 2–3 points |
| E4 eviction | cost/OPT: no (offline); TTFT: yes | exact optimum needs replay of identical arrival sequences |
| E5 PD | no | few configurations; measured parameters feed a closed-form test |
| E6 routing | yes | the inversion load needs a fine load sweep |
| E7 scorecard | yes | the simulator is one of the two models being scored |

If E1 shows that service curves are simple (for example, linear in new
and cached tokens with a batch term), consider whether a semi-analytical
model such as MVA with load-dependent servers would answer E3 and E6
without a full simulator. Try that first if it is cheaper.

## 2. Scope

**In scope**
- Program-level workload: multi-turn programs with tool think-time,
  from trace replay or a synthetic generator.
- Replicas and pools: aggregated replicas, static PD pools, and dynamic
  PD with per-turn append-prefill routing.
- Continuous batching with a token budget per iteration, and chunked
  prefill.
- KV management at block granularity per device, a host or shared tier,
  and pluggable eviction, offload and prefetch policies.
- Transfers: device↔device and device↔tier links, with bandwidth shared
  among concurrent transfers.
- Pluggable routers: myopic, KV-aware, program-aware lookahead, strict
  affinity.

**Out of scope** (matches the paper's scope statement): collective
contention inside a model-parallel group, kernel-launch jitter, allocator
behaviour beyond block counts, network head-of-line blocking. Where the
E7 error decomposition blames these, report the gap rather than model
them.

## 3. Architecture

A single-threaded event loop over a `heapq` priority queue. No SimPy
dependency, so the core stays small and deterministic.

```
sim/
  core.py         event loop, clock, seeded RNG streams
  workload.py     Program, Turn; TraceReplay and SyntheticGenerator
  service.py      calibrated service-time models from E1 (fit files in data/)
  engine.py       Replica: iteration-level batching, prefill/decode queues
  kv.py           BlockPool per device and tier; residency map program→location
  transfer.py     Link with fair-share bandwidth; transfer completion events
  policies/
    eviction.py   LRU, hit-ratio, shortest-first, density (p_i c_i), utility (`eq:utility`), oracle
    offload.py    never, always, selective argmin
    routing.py    myopic, kv_aware, lookahead, affinity, append_prefill
  cluster.py      wires replicas, pools, tiers and links from a config
  metrics.py      per-turn records → TTFT/TPOT/p99, throughput, hit rate, CV²
  run.py          CLI: config (TOML) + seed → parquet of per-turn records
tests/
  test_closed_forms.py   validation ladder, steps 1–3
```

Tooling: Python 3.12 via `uv`; numpy, pandas or polars, pyarrow. Add
`make sim-test` once code exists.

### Events
`TurnArrival`, `IterationStart`/`IterationEnd` (per replica),
`TransferDone`, `ToolDone` (next turn of the program becomes ready),
`ProgramEnd`. Policies are called synchronously at decision points:
router on `TurnArrival`, eviction when an allocation fails, offload at
`IterationEnd` for programs entering tool phase.

### Service model
`S_prefill(L, K, B)` and `S_decode(B, KV)` are the E1 fits, evaluated per
iteration for the batch composition, not per request. This is the main
fidelity gain over the closed forms. Optional multiplicative noise uses
the E1 residual distribution.

### Policy interface
```python
class EvictionPolicy(Protocol):
    def choose(self, resident: list[ProgramState], need_blocks: int, now: float) -> list[ProgramId]: ...

class Router(Protocol):
    def route(self, turn: Turn, cluster: ClusterView, now: float) -> ReplicaId: ...
```
`ProgramState` exposes `c_i` (context length), resident location, phase,
time since suspension, and an estimated resume probability `p_i`. The
estimate is part of the policy, so a policy may be wrong about it.

The `oracle` eviction policy solves the eviction problem (`eq:evict`) exactly (small instances,
integer programming or DP over blocks), using realised future resumes.
It is an unattainable lower bound for E4.

## 4. Validation ladder

The simulator is trusted only after each step passes. Steps 1–3 are
unit tests against the paper's closed forms, so any bug that breaks a
proposition's prediction is caught mechanically.

1. **M/M/1.** One replica, batch size 1, exponential service, Poisson
   arrivals. Mean response time is within 2 % of `1/(μ−λ)` at
   ρ ∈ {0.5, 0.8, 0.9} (`prop:mm1`).
2. **M/G/1.** Deterministic, then two-point hit/miss service. Mean wait
   is within 3 % of PK (`eq:pk`). The ratio to exponential is
   `(1+CV²)/2` (`eq:cv2`).
3. **Closed network.** N programs with exponential think time. Check the
   interactive response-time law `R = N/X − Z` exactly (it is an
   identity, so any deviation is a bug), and check that throughput is
   non-decreasing in N when demands are fixed.
4. **PD capacity.** Saturated static PD with no batching effects. The
   measured capacity matches `min(N_P/s_P, N_D/s_D)` (`prop:pd`).
5. **Calibrated vs testbed.** With E1 fits, reproduce testbed TTFT and
   throughput at the E7 held-out points. Report MAPE. This step is
   itself a row of the paper's scorecard table (`tab:scorecard`).

## 5. Outputs

One parquet file per run with a row per turn: program id, turn index,
arrival, first-token and finish times, hit length, replica, transfer
bytes, and the policy decisions taken. All paper tables are computed from
these files by scripts in `sim/analysis/`, so every `\tbd` in §7 has one
reproducible source. Runs are keyed by (config hash, seed). Use at least
5 seeds per point and report 95 % intervals.

## 6. Milestones

| M | Deliverable | Depends on |
|---|-------------|------------|
| M0 | core, workload (synthetic), single replica, metrics, ladder steps 1–2 | none |
| M1 | closed-network programs with tool time, ladder step 3 | M0 |
| M2 | KV block pool, eviction policies, oracle; E4 end-to-end | M1, trace format |
| M3 | tiers, transfers, offload policies; E3 | M2 |
| M4 | PD pools and routers; ladder step 4; E6 | M3 |
| M5 | E1 service fits plugged in; ladder step 5; E7 | E1 data |

M0 to M4 can proceed on synthetic workloads before testbed data exists.
M5 cannot.
