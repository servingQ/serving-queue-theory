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
serving system and must not fill the `\tbd{}` cells of paper §6 (see
AGENTS.md rule 5).

## Run

```bash
make sim      # from the repo root: Lean-name check, fmt, clippy, tests, report
make report   # print the validation report only

cd libqueuingsim
cargo test --release                            # all tests (~5 s)
cargo run --release --example validate          # Markdown report to stdout
cargo run --release --example validate -- r.md  # also write it to a file
cargo run --release --example paper_tables      # regenerate ../paper/sim/*.tex
```

`paper/simulation.tex` (the paper's simulation section) takes every number
from `paper/sim/*.tex`, which `examples/paper_tables.rs` generates.
`check_sim.sh` regenerates them and fails if the committed copies are
stale, so after changing a model or scenario, rerun `paper_tables` and
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
| `analytic` | one function per Lean definition (`mm1Wait`, `pkWait`, `pdFullCapacity`, …) | |
| `models::queue` | open G/G/c FIFO, cross-checked against Lindley's recursion | §2.1, §3 |
| `models::agentic` | programs cycling queue → service → tool on one replica with finite KV; eviction and offload policies | §2.2–2.3, §3.1 |
| `models::eviction` | offline eviction instances with an exact DP optimum | §3.2 |
| `models::pd` | aggregated pool vs prefill → KV link → decode tandem | App. B |
| `models::routing` | replicas with per-program KV locality; affinity, myopic, lookahead routing | §5 |
| `validation` | the named checks; each cites paper labels and Lean theorems | all |

## Tests

- `src/**` unit tests cover the engine, distribution moments, the DP
  optimum against brute force, the Rust `shortest_first_lean` against the
  Lean definition, and DES against Lindley.
- `tests/lean_examples.rs` evaluates `analytic` at every numeric instance
  proved in Lean.
- `tests/propositions.rs` runs one test per `validation` check.
- `scripts/check_sim.sh` also fails if a check cites a Lean name that does
  not exist in `lean/ServingQueueTheory`.

## Modelling choices that matter

- **Service cost.** `CostModel::turn` is `overhead + a·new + b·new·(cached +
  new/2) + d·out`. A miss re-prefills the whole context, so its cost is
  quadratic in context length, as in ThunderAgent Lemma 4.1.
- **Resume uncertainty.** Whether a program issues another turn is drawn
  when its tool call returns. A suspended program therefore holds KV that
  may never be reused, which is what gives `p_i` meaning in eviction.
- **Eviction scope.** Programs in a tool call are evicted first. Queued
  programs are evicted only if that does not free enough memory.
- **Fetch mode.** `Async` fetches finish before the turn queues.
  `Blocking` fetches hold the replica for the tier wait plus the transfer,
  as when KV loading sits on the batch's critical path.
- **Not modelled:** continuous batching (one turn at a time, with
  amortised per-turn costs), block granularity, partial prefix hits,
  collective-communication contention, and PD memory caps.

## Adding a check

1. Write `pub fn my_check() -> Check` in `src/validation.rs` and add it to
   `all()`.
2. Add `my_check` to the `checks!` list in `tests/propositions.rs`. The
   `every_check_has_a_test` test fails if you forget.
3. List only Lean theorems whose *statement* the check exercises.
   `check_sim.sh` verifies that they exist.
4. Keep seeds fixed and tolerances explicit in `expected`. If a check
   needs a wide tolerance to pass, report it as an `Observation` instead.
