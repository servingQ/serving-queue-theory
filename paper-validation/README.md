# paper-validation

Paper-specific validation and report generation for `paper/main.tex`. seQ is the simulation engine.

Serving deployments and their workloads are specified in seQ programs. The Rust modules retain configurations, analytic references, and paper-specific
metrics. Queue, PD, routing, agentic and batch execution uses the seQ
interpreter and programs in `programs/`.

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
simulator are in `research/simulation-design.md`; where this phase sits in
the validation plan is in `research/research-plan.md` §4.

Results come from synthetic workloads. They are not measurements of a
serving system and must not fill the `\tbd{}` cells of paper §4.2 (see
AGENTS.md rule 5).

## Run

```bash
make sim      # from the repo root: Lean-name check, fmt, clippy, tests, report
make report   # print the validation report only

cd paper-validation
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
| `seq-lang` | parser, event scheduler, distribution sampling, and simulation reports | all |
| `stats` | Welford moments and batch-means intervals for paper tables | |
| `analytic` | one function per Lean definition (`mm1Wait`, `pkWait`, `missPrice`, `psNum`, `psPrice`, `stationaryMean`, `expFit`, `pdFullCapacity`, …) | |
| `models::queue` | seQ G/G/c FIFO program and Lindley cross-check | §2.1–2.2 |
| `models::batch` | seQ sampled-work FIFO, PS and exact LPS session checks; `fifo_admitted` for footprint | §2, Props. price, decode, footprint |
| `seq_price`, `seq_open`, `seq_replay` | the paper's evidence on a replica with vLLM v1's engine rules and the testbed's cost model: seQ programs `programs/{price,open,replay}_vllm.seq` run in-process by the `seq` crate (where a miss is paid; the eviction/admission experiment; §4.2's trace replay) | Props. price, decode; §3.1, §3.3, §4.2 |
| `models::agentic` | programs cycling queue → service → tool on one single-turn replica with finite KV; eviction and offload policies, including the congestion-priced ones (`Priced`, price of a miss from online estimates) | §2.2–2.3, §3.1–3.2 |
| `models::eviction` | offline eviction instances with an exact DP optimum; SF, density and guarded density greedy, on `p c²` or arbitrary weights | §3.1 |
| `models::pd` | aggregated pool vs prefill → KV link → decode tandem | App. B |
| `models::routing` | replicas with per-program KV locality; affinity, myopic, lookahead routing | §3.3 |
| `validation` | the named checks; each cites paper labels and Lean theorems | all |

## Tests

- `src/**` unit tests cover analytic helpers, the eviction DP against
  brute force, and seQ model results against queueing reference formulas.
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
- **The paper's two-resource replica** (decode one token per turn per
  iteration, prefill FIFO on the compute left, §2.2) is the model of the
  propositions, whose closed forms the checks use; it is not simulated
  here. Its time sharing matches vLLM v1's step rule, but a simulator of
  it would also need a memory model, and the evidence runs vLLM's (block
  eviction from the tail, chunk-wise growth with preemption, admission by
  the engine) as seQ programs (`seq_price`, `seq_open`, `seq_replay`).
- **Resume uncertainty.** Whether a program issues another turn is drawn
  when its tool call returns. A suspended program therefore holds KV that
  may never be reused, which is what gives `p_i` meaning in eviction.
- **Eviction scope.** The agentic seQ program evicts suspended programs
  first, then queued ones when needed. The vLLM scenarios use separate seQ
  programs with block-level KV and admission rules.
- **Prices.** The agentic seQ program uses its stage's online miss price for
  `Priced` and `PricedMemory` eviction.
- **Fetch mode (`agentic`).** `Async` fetches finish before the turn
  queues. `Blocking` fetches hold the replica for the tier wait plus the
  transfer, as when KV loading sits on the batch's critical path.
- **Batching (`Ps`).** The sampled-work seQ program gives each admitted
  turn `φ(n)/n` service under PS. `batch_cap` limits concurrent admission;
  `tab-lps` compares that exact rule with a saturating `φ`.
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
