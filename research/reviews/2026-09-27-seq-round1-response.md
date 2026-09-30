# Response to review round 1 with serQ (2026-09-27)

Each item of `2026-09-27-seq-round1.md`, what changed, and the evidence.

## A. Simulator semantics

A1. Fixed in the language, not in constants:
- `pool … { admit via engine; }`: a queue served by a step stage's
  scheduler, at the start of an iteration, with the budget left, never in
  an iteration that preempted; unit expressions are evaluated at admission
  (the lecture's `[Admit]` rule).
- `pool (u) fits (r)`: the admission needs room for `r`, allocates `u`.
- `hold … reuse (ρ)`: consume at most `ρ` of the own cached prefix; the
  rest stays cached as a dead entry of the same age.
- `end` keeps the session's cached prefixes (the lecture's `[End]`); the
  two libqueuingsim-equivalent programs write `drop kv;` before `end;`.
- Residents of a step stage are served in admission order; cache ties are
  broken by release order.
Evidence: `scripts/exp/diff_seq_vllm.sh` — serQ and the real scheduler
agree on 3 321 of 3 321 requests (send, first token, cached tokens) on the
base and forced-miss traces, for a constant step and for the A100 cost
model; on 40-session runs with 1 000 / 1 500 / 3 000 blocks (deadlocking at
the same step on 1 000); vLLM 0.30.0's scheduler (the testbed's) gives the
same answers as upstream on the pressured run.

A2. The cost model's engine terms were measured (A100 step sweeps, 3 022
steps, MAPE 2.7 % decode, 5.6 % prefill, 5.7 % mixed; `serQ tools/a100/`).
The two overhead constants are fitted on the light-load runs only; the
served-step trace (steptrace, below) is collected to identify them from
the serving path directly. Reported in `serQ `docs/language.md`` §8.

A3. Recorded in `docs/testbed-gpu.md` and §8; the 3.0 s point is reported
as bistable (two runs, one collapsed).

## B. libqueuingsim

B1. The claim is withdrawn from `serQ `docs/language.md``; the 20-seed
comparison is in §5 (`data/exp/seq/replica_seeds.csv`).

B2. `paper/simulation.tex` now says that least recently used, the order
vLLM uses, pays several times the TTFT of the size-aware keys, citing
`tab:sim-evict-dyn` (the numbers stay in the generated table).

B3. `replica.sq` says `decode first` (no change in results).

## C. Paper

C1. §2.2 "Prefill stage" gains one sentence: vLLM serves in admission
order, which coincides with decode-first unless a per-request cap limits a
prefill's tokens in a step, with `\provedby{serve_preserves_shape,
serve_eq_decode_first, chunk_cap_breaks_shape}` (`SerqServe.lean`).

C2. Not in the paper: the pinning result is a simulation. It is recorded as
hypothesis H-pin in `research/research-plan.md` with the testbed experiment
that would test it (touch a waiting request's cached blocks at enqueue in
vLLM, replay 3.0 s and 2.5 s).

## D. Lectures

D1. Lecture 1: the stage kind `step(B, τ)`, `run … growing`, the hold
notation, the iteration rule with preemption, and a paragraph "Production
schedulers" with the three admission refinements; "what the model leaves
out" no longer says preemption is inexpressible.

D2. Lecture 5: a paragraph "The wait channel is an admission rule", with
the simulated effect of pinning and the caveat that pinned bytes lower the
other prefixes' survival (so Prop. L5:prop:tarski(ii) applies only when the
first effect dominates).

D3. Exercise L1:exr:colocated now asks for the serving-order result and
its counterexample.

## E. Formal side

E1. `SerqExec.lean` (executable semantics of pools and one step engine on
the step clock, `Route Env ℕ` programs) and `SerqOracle.lean` (generated
by `scripts/gen_serq_oracle.py`): one theorem per scenario, proved by
`decide +kernel` in 6 s; serQ `make check` checks the file is current and that
the A100 engine's answers equal the CPU oracle's. The syntax is now
`Route Env V`, shared by the ℝ programs of the paper and the ℕ programs of
the executable semantics.

E2. The statement keywords are non-reserved (`declare_syntax_cat route
(behavior := symbol)`, `&"done"`, …).

E3 (found while answering E1). Proving that the executable eviction loop
makes the room it is asked for (`Exec.makeRoom_room`: with more fuel than
cached units it ends with `used + cached + need ≤ cap` or an empty cache)
exposed a defect in the executable semantics: the LRU comparison
`(last, seq) ≤ (last', seq')` is the componentwise order on pairs in
Lean, not the lexicographic one, so two entries could each fail to precede
the other. It is now lexicographic. The oracle scenarios run without a
prefix cache, so no theorem changed; the Rust interpreter compared keys
lexicographically all along.

E4. The six scenarios ran without a prefix cache, so a seventh was added:
three sessions of three turns on 20 blocks (`serQ tools/oracle/
cache_trace.*`), with a hit, a partial hit and misses by eviction,
answered by the real scheduler and KV-cache manager on a unit step clock.
The Rust program matched it at once (`serQ tests/vllm_cache.rs`); the
Lean executable semantics did not: it woke delays that end at the same tick
in session order, where the Rust interpreter and the replayed scheduler
take them in the order they started. With a start order on delays the Lean
semantics matches (`Oracle.vllm_cache_trace`, `decide +kernel`).
