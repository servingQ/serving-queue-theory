# libqueuingsim

A seeded discrete-event simulator for the models in `paper/main.tex`.

The Lean proofs establish each proposition *inside* its model. This crate
asks two questions the proofs cannot answer:

1. **In-model:** does a simulation that satisfies a proposition's
   assumptions reproduce its closed form? A failure means a bug in the
   simulator or a transcription error in the formula.
2. **Beyond-model:** when an assumption is dropped, does the *decision* the
   proposition implies survive? Examples are non-Poisson arrivals, a hit rate
   that emerges from finite KV memory instead of being fixed, tandem PD pools
   with integer splits, and heuristic controllers instead of the optimum.

Design, validation-ladder status and the roadmap to the calibrated
simulator are in `docs/simulation-design.md`; where this phase sits in
the validation plan is in `docs/research-plan.md` §4.

Results come from synthetic workloads. They are not measurements of a
serving system and must not fill the `\tbd{}` cells of paper §4.2 (see
AGENTS.md rule 5).

## Run

```bash
make sim      # from the repo root: Lean-name check, fmt, clippy, tests, report
make report   # print the validation report only

cd libqueuingsim
cargo test --release                            # all tests (~12 s)
cargo run --release --example validate          # Markdown report to stdout
cargo run --release --example validate -- r.md  # also write it to a file
cargo run --release --example paper_tables      # regenerate ../paper/sim/*.tex and data/*.csv (~20 s)
make figs                                       # from the repo root: redraw ../paper/sim/fig-*.pdf
```

`paper/simulation.tex` (the paper's simulation section) takes every number
from `paper/sim/*.tex`, which `examples/paper_tables.rs` generates. The
same run writes `paper/sim/data/*.csv` (one file per figure: the
admission-cap sweep, the open-session eviction table, the LPS comparison,
the offline eviction ratios with their per-instance samples), from which
`scripts/plot_sim.py` draws `paper/sim/fig-*.pdf`; a figure therefore
shows exactly the numbers of its table. In the policy-comparison tables
the best value per row or per group is bold (`\textbf` / `\mathbf`),
computed at the printed precision with ties all bold.
`check_sim.sh` regenerates tables and data and fails if the committed
copies are stale, then redraws the figures (PDF bytes are not diffed), so
after changing a model or scenario, rerun `paper_tables`, `make figs`, and
reread the prose in `simulation.tex` against the new tables. The CI job
runs on `ubuntu-22.04` so that libm matches the machine that generated
the tables.

The toolchain is pinned in `rust-toolchain.toml`. `make setup` installs
rustup user-locally if it is missing.

## Layout

| Module | Model | Paper |
|--------|-------|-------|
| `engine` | event list, clock, `Model` trait; ties broken by insertion order | |
| `dist` | D, Exp, Erlang, H2, Uniform, Discrete, HitMiss, each with exact moments | |
| `stats` | Welford moments, time averages, batch-means and replication CIs | |
| `analytic` | one function per Lean definition (`mm1Wait`, `pkWait`, `missPrice`, `psNum`, `psPrice`, `stationaryMean`, `expFit`, `pdFullCapacity`, …) | |
| `models::queue` | open G/G/c FIFO, cross-checked against Lindley's recursion | §2.1–2.2 |
| `models::batch` | batching replica: open sessions (Poisson `Λ`, closed loop turn → tool → resume w.p. `p` inside, optional cap on live sessions) or a closed population; servers `TwoStage` (the paper's two-resource replica: decode PS on bandwidth, prefill FIFO in the leftover compute), `Ps { φ }` (one PS station), `BlockingPrefill { φ }`, `Fifo`; exact limited PS (batch cap `B`, KV-memory admission, FIFO with head-of-line blocking); KV-dependent decode cost; resident KV as a prefix of the context; SF/LRU/Density/Priced/PricedMemory/PricedMemoryBlocks eviction with the price of the server mode; `fifo_admitted` for the footprint proposition | §2 (batch, sessions), Props. price, decode, memory, footprint |
| `models::agentic` | programs cycling queue → service → tool on one single-turn replica with finite KV; eviction and offload policies, including the congestion-priced ones (`Priced`, price of a miss from online estimates) | §2.2–2.3, §3.1–3.2 |
| `models::eviction` | offline eviction instances with an exact DP optimum; SF, density and guarded density greedy, on `p c²` or arbitrary weights | §3.1 |
| `models::pd` | aggregated pool vs prefill → KV link → decode tandem | App. B |
| `models::routing` | replicas with per-program KV locality; affinity, myopic, lookahead routing | §3.3 |
| `validation` | the named checks; each cites paper labels and Lean theorems | all |

## Tests

- `src/**` unit tests cover the engine, distribution moments, the DP
  optimum against brute force, the batching replica (`Fifo` against
  `agentic`, KV and batch-cap invariants for every server and the block
  policy, `ps_mean_number` against M/M/1 and M/M/∞, the `TwoStage` decode
  stage as an infinite server at zero context and its prefill stage as an
  M/D/1 without decode, block eviction freeing tail blocks only), the
  guarded density greedy's factor 2 against brute force on random
  general-weight instances, the Rust `shortest_first_lean` against the
  Lean definition, and DES against Lindley.
- `tests/lean_examples.rs` evaluates `analytic` at every numeric instance
  proved in Lean.
- `tests/propositions.rs` runs one test per `validation` check.
- `scripts/check_sim.sh` also fails if a check cites a Lean name that does
  not exist in `lean/ServingQueueTheory`.

## Modelling choices that matter

- **Service cost.** `CostModel::turn` is `overhead + a·new + b·new·(cached +
  new/2) + out·(d + β·K)`. A miss re-prefills what is not resident, so a
  full miss costs quadratic in context length, as in ThunderAgent
  Lemma 4.1. The decode term grows with the context `K` through
  `decode_kv = β` (KV read per output token per context token); the
  default `β = 0` reproduces the older context-free term, and the
  open-session scenario uses `β = 2·10⁻⁹` s (the KV of a 100k-token
  context takes as long to read as the weights).
- **Two-resource replica (`Server::TwoStage`).** One device runs
  iterations of length `T(n, K_B) = max(ω + β·K_B, n·a)`: memory time
  (weights once, the batch's KV once) or compute time (one token per
  batch member, sharing the prefill chunk's matmuls). Every decoding turn
  advances one token per iteration, so decode is processor sharing on
  bandwidth with demand `o·(β·K + ω/n)` and demand-proportional shares;
  hit or miss does not change it. Prefill is a FIFO server for the
  prefill work, one turn at a time in admission order, at rate
  `1 - n·a/T` (the compute the decode step leaves idle, `≈ 1 - ρ_D`).
  A long miss prefill therefore delays every prefill behind it while
  decode continues. Rates are fluid between events. With the example
  costs (`a = 2·10⁻⁵`, `ω = 2·10⁻⁴`) a batch of at most 8 is
  memory-bound and prefill keeps 70–98 % of the device: on this roofline
  model decode interferes little with prefill, and the price of a miss
  is paid almost entirely in the prefill queue. TTFT is ready → prefill
  done; turn response adds the decode time.
- **Resume uncertainty.** Whether a program issues another turn is drawn
  when its tool call returns. A suspended program therefore holds KV that
  may never be reused, which is what gives `p_i` meaning in eviction.
- **Eviction scope.** Programs in a tool call are evicted first. Queued
  programs are evicted only if that does not free enough memory. Resident
  KV is a prefix of the context; whole-session policies drop it entirely,
  `PricedMemoryBlocks` drops 512-token tail blocks, and the next turn
  re-prefills only what is missing (a turn is a hit iff its whole context
  was resident).
- **Prices.** `Priced` orders by `q_i Φ_i / c_i` with `Φ_i` the price of a
  miss of the server mode: under `Ps` it is `ΔS·L'(ρ̂)` (the `Density`
  order, Prop. decode); under `TwoStage`, `BlockingPrefill` and `Fifo`
  the M/G/1 price of Prop. price with the head-of-line term, from online
  `λ̂, ρ̂, Ŵ` of the FIFO part (prefill work divided by the stage's mean
  availability). `PricedMemory` divides by the expected remaining
  suspension `τ_i` (class mean tool time) so the order is per
  byte-second, the threshold rule of Prop. memory; `PricedMemoryBlocks`
  applies the same price to tail blocks with `ΔP = a·m + b·m·(K - m/2)`.
- **Fetch mode (`agentic`).** `Async` fetches finish before the turn
  queues. `Blocking` fetches hold the replica for the tier wait plus the
  transfer, as when KV loading sits on the batch's critical path.
- **Batching (`Ps`, `BlockingPrefill`).** Work is in seconds at rate 1.
  Under `Ps { φ }` every admitted turn gets `φ(n)/n`; the simulation
  tracks the service attained by every batch member (one virtual clock),
  so rate changes cost `O(log n)`. Under `BlockingPrefill { φ }` a prefill
  runs alone at `φ(1)` with priority over decode and freezes the decode
  batch. The theory models a batch cap by `φ` flattened at `B`;
  `batch_cap` is the exact rule, and `tab-lps` measures the gap. A turn is
  admitted only if its KV fits after evicting suspended sessions (tool
  calls first, then waiting ones); batch members are never evicted, and a
  turn that does not fit blocks the ones behind it.
- **Thrashing and the admission cap.** With finite KV, once misses start,
  turns pin KV longer, which evicts more suspended sessions. On the
  single-PS replica this made single seeds bistable. On the two-resource
  replica the open-session scenario degrades gradually at 24 live
  sessions, does not evict at 16, and thrashes (hit rate below 0.5 in most
  seeds) at 32; the admission cap moves the window more than the eviction
  order does, and its cost is the entry-queue wait, which the sweep table
  reports. Open-session tables report means over 20 seeds.
- **Not modelled:** iteration granularity (rates are fluid), block-level
  KV allocation and shared prefixes across sessions, collective-
  communication contention, PD memory caps, and offloading on the batching
  replica (`agentic` still serves one turn at a time; offloading exists
  only there).

## Adding a check

1. Write `pub fn my_check() -> Check` in `src/validation.rs` and add it to
   `all()`.
2. Add `my_check` to the `checks!` list in `tests/propositions.rs`. The
   `every_check_has_a_test` test fails if you forget.
3. List only Lean theorems whose *statement* the check exercises.
   `check_sim.sh` verifies that they exist.
4. Keep seeds fixed and tolerances explicit in `expected`. If a check
   needs a wide tolerance to pass, report it as an `Observation` instead.
