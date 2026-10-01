# §4.2's trace replay in serQ, with libqueuingsim's rules and with vLLM's

Current status (2026-10-01): paper §4.2 runs `programs/replay_vllm.sq`
in process through `validation/src/sim/replay_vllm.py`; `make tables`
generates its tables and macros. `scripts/exp/serq_replay42.py` runs the
LRU (`lru=1`) and finished-session (`keep=0`) ablations, recorded in
`research/serq-replay42-tables.md`. All of these are simulator output on
replayed WEKA sessions, not serving measurements (AGENTS.md rule 7).

The rest of this note records the engine-rule comparison made on 2026-09-27.
The user selected the vLLM-rule replay that day; that port is complete.
The old `TwoStage` server and its replay program were removed. The baseline
comparison is available at commit `1fc3d27` in git history; its old program
paths and numeric conclusions below refer to that snapshot, not the current
serQ release. Current programs use `.sq` and the Python validation package.

## Historical comparison (2026-09-27)

## Programs

| Program | Rules |
|---|---|
| `programs/replay_twostage.sq` | libqueuingsim's: the batch reserves a turn's whole KV at admission, FCFS; decode first, the head-of-line prefill takes the compute left; eviction of whole sessions outside the batch, tool calls before waiting sessions, cheapest price per byte-second first; a turn hits iff its whole context is resident, else re-prefills all of it; a finished session's KV is dropped |
| `programs/replay_vllm.sq` | vLLM v1's: the engine admits at iteration start with the budget left, in admission order; admission needs room for the whole prompt but allocates the first chunk, the hold grows per computed token, a failed growth preempts LIFO; 16-token blocks evicted from an entry's tail, reuse bounded by the previous turn's full computed blocks, the rest dead; every computed token cached; a finished session's blocks stay. Variants: `lru=1` (vLLM's LRU order), `keep=0` (drop a finished session's blocks) |

Both use the same workload (WEKA sessions, Poisson arrivals, live-session
cap), the same time model (RBLN cost fit: prefill `c0 + a n + b n (K +
n/2)`, decode iteration `ω`, β = 0), and the same eviction key where priced.
The comparison that isolates the engine rules is `twostage` against `vllm`
(same interpreter, same key). The budget is rounded to whole tokens and
the overhead up (`floor(ω/a)`, `ceil(c0/a)`) in both: with fractional
chunks the position of a growing hold accumulates rounding error and loses
a block when rounded down (found here; serQ could keep positions integral).

**Baseline.** `replay_twostage.sq` lies inside libqueuingsim's 95 %
intervals in every cell (hit rate, TTFT, mixture share). Those intervals
are wide (5 seeds; the finite-pool TTFT half-widths exceed the means), and
the serQ TTFT means sit lower in the finite cells. serQ's priced key uses the
engine's estimator, which sees decode as well as prefill jobs, where
libqueuingsim's sees the prefill queue only.

## What stays

- **Open replica.** With no eviction every follow-up turn hits and the mean
  TTFT is set by the cold first prompts, under every rule set.
- **The admission cap decides whether the replica thrashes.** In every
  pool and under every rule set, the looser cap has the lower hit rate and
  the higher TTFT, by 2.5 to 5 times. The policy ranking that §4.2 and
  Algorithm 1's step 7 rest on holds.
- **Priced eviction beats LRU, or ties.** Under vLLM's rules the priced key
  gives the lower or equal TTFT in every finite cell.

## What moves

1. **The numbers §4.2 quotes.** Under vLLM's rules the tight caps' lowest
   hit rate, the mixture's share of prefill-work variance, the loose caps'
   highest hit rate and lowest TTFT all move, some by a factor (generated
   table "The quantities §4.2 quotes"). The mixture share falls most: it
   is a property of whole-session eviction.
2. **Misses become partial and cheap.** Block eviction from an entry's tail
   turns a lost context into a lost tail. A turn that does not reuse its
   whole prefix still reuses most of it (the reused share stays high where
   the hit rate falls), so the mean TTFT in the finite cells falls by 1.3
   to 3.7 times against libqueuingsim's rules, and the hit/miss mixture
   supplies far less of the prefill-work variance. The binary hit rate
   overstates the damage; the reused share and the TTFT are the quantities
   to report under block eviction.
3. **A priced key needs to know that a session ended.** Keeping a finished
   session's blocks (vLLM's rule) and pricing them like a session in a
   tool call lowers the hit rate by up to 0.23 against dropping them
   (`keep=0`), with little effect on TTFT because the lost prefixes are
   tails. LRU ages the stale entries out and does not show it. For the
   scheduler of §3 on vLLM, the end of a program is an input: price a
   finished session at p = 0, or drop its blocks.
4. **Priced vs LRU.** The priced key's margin over LRU under vLLM's rules
   is at most 1.65 times in TTFT, well below the synthetic
   `tab:sim-evict-dyn` ("several times"). That table is not a trace
   result, so no sentence of §4.2 is contradicted, but the margin on the
   real workload is smaller.
5. **Preemption appears.** Under vLLM's rules the smallest pool at the
   loose cap preempts about 13 times per run. libqueuingsim cannot preempt,
   since it reserves the whole turn up front.

## Paper decision (completed)

The vLLM-rule replay replaced whole-session eviction on 2026-09-27. Its
current Python adapter is `validation/src/sim/replay_vllm.py`, and its
numbers enter through `make tables`. The paper reports reused-prefix share
alongside hit rate. End-of-program information remains an input to the
priced eviction policy; the `keep=0` ablation isolates its effect. The old
options to retain or report both replicas are superseded.
