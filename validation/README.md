# validation

Paper-specific validation and report generation for `paper/main.tex`, in
Python. serQ is the simulation engine: every simulated system is a serQ
program (`programs/*.sq` here, the general ones in serQ's `examples/`), run
in process by pyserq, which `uv sync` builds from the release pinned in
`pyproject.toml` (`[tool.serq]`) with serQ's Rust toolchain. This
package holds the configurations, the analytic references, the offline
eviction instances, the statistics and the table generation.

The Lean proofs establish each proposition *inside* its model. This package
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

Results come from synthetic workloads or replayed traces on a simulated
replica. They are not measurements of a serving system and must not fill
the `\tbd{}` cells of the paper (AGENTS.md rule 7).

## Run

```bash
make serq      # from the repo root: the pinned serQ release into .serq/src (pyserq's source) and its CLI
make sim      # Lean-name check, ruff, pytest, validation report
make report   # print the validation report only
make tables   # regenerate ../paper/sim/*.tex and ../paper/sim/data/*.csv
make figs     # redraw ../paper/sim/fig-*.pdf from the data files

cd validation
uv sync                                        # the Python environment (uv.lock)
uv run pytest -m "not checks"                  # units, Lean instances, serQ adapters
uv run pytest -m checks                        # one test per named check (slow)
uv run python -m report.validation r.md     # Markdown report, also written to r.md
uv run python -m report.paper_tables        # the paper's simulation tables
uv run python -m report.inversion_explore   # affinity vs always-move by rate and link
```

`paper/simulation.tex` (the paper's simulation section) takes every number
from `paper/sim/*.tex`, which `report.paper_tables` generates. The same
run writes `paper/sim/data/*.csv` (one file per figure), from which
`scripts/plot_sim.py` draws `paper/sim/fig-*.pdf`; a figure therefore shows
exactly the numbers of its table. In the policy-comparison tables the best
value per row or per group is bold (`\textbf` / `\mathbf`), computed at the
printed precision with ties all bold. After changing a model or scenario,
rerun `make tables` and `make figs`, and reread the prose in
`simulation.tex` against the new tables.

The package reproduces the Rust crate it replaced bit for bit:
`rng` is rand 0.9's `StdRng` (ChaCha12) with its range samplers,
`fmt` is Rust's float formatting and `f64::round`, and sums run
left to right (`fmt.ssum`), so the offline eviction instances, the
footprint Monte Carlo and every generated file are unchanged. serQ's
trajectories depend on the platform's libm; the CI job runs on
`ubuntu-22.04` so that libm matches the machine that generated the tables.

## Layout

`src/` is four layers. `theory` computes what a check expects and never
imports serQ, so the checked party does not compute its own expected value;
`sim` runs serQ and measures; `checks` sets one against the other; `report`
writes the results, and nothing imports it. `fmt` and `constants` are
leaves every layer may use. `tests/test_layers.py` enforces the directions.

| Module | Model | Paper |
|--------|-------|-------|
| `theory.analytic` | one function per Lean definition (`mm1Wait`, `pkWait`, `missPrice`, `psNum`, `psPrice`, `stationaryMean`, `expFit`, `pdFullCapacity`, …) | |
| `theory.dist` | the scenarios' laws: exact moments and seeded sampling | |
| `theory.rng` | rand 0.9's `StdRng` | |
| `theory.queue` | Lindley's recursion on the streams of `mg1.sq`, an independent reproduction of a serQ run | §2.1 |
| `theory.batch` | the PS capacity `φ(n)`, the mean number at a PS queue, and `fifo_admitted` for footprint | §2, Props. price, decode, footprint |
| `theory.pd` | the capacity of an integer prefill/decode split | App. B |
| `theory.eviction` | offline eviction instances with an exact DP optimum; SF, density and guarded density greedy, on `p c²` or arbitrary weights | §3.1 |
| `sim.serq` | runs a serQ program in process with pyserq (`compile`, `run`); pyserq's report, with an observation's samples as numpy arrays | all |
| `sim.laws` | a law of `theory.dist` as an expression in serQ's sampler | |
| `sim.stats` | Welford moments, batch-means and replication intervals, paired differences | |
| `sim.workload` | replayed real sessions (`TraceCorpus`, the bundled WEKA sessions, read by `pyserq.read_trace`) | §4.2 |
| `sim.queue` | serQ's `mg1.sq` as a G/G/c FIFO queue | §2.1–2.2 |
| `sim.batch` | `programs/batch_sampled.sq`: sampled-work FIFO, PS and exact LPS session checks | §2, Props. price, decode |
| `sim.price_vllm`, `sim.open_vllm`, `sim.replay_vllm` | the paper's evidence on a replica with vLLM v1's engine rules and the testbed's cost model: `programs/{price,open,replay}_vllm.sq` (where a miss is paid; the eviction/admission experiment; §4.2's trace replay) | Props. price, decode; §3.1, §3.3, §4.2 |
| `sim.agentic` | `programs/agentic_model.sq`: programs cycling queue → service → tool on one replica with finite KV; eviction and offload policies, including the congestion-priced ones | §2.2–2.3, §3.1–3.2 |
| `sim.pd` | serQ's `pd_tandem.sq`, `pd_open.sq`: aggregated pool vs prefill → KV link → decode tandem | App. B |
| `sim.routing` | serQ's `routing.sq`: affinity, myopic, lookahead routing | §3.3 |
| `checks` | the named checks; each cites paper labels and Lean theorems | all |
| `report.validation`, `report.paper_tables` | the Markdown report; `paper/sim/*.tex` and `paper/sim/data/*.csv` | all |
| `report.inversion_explore` | affinity vs always-move by rate and link bandwidth (printed, not asserted) | §3.3 |
| `fmt`, `constants` | Rust's number formatting; the calibrated cost model and the scenario grids | |

## Tests

- `tests/test_units.py` covers the RNG port, the laws, the formatting, the
  statistics, the trace parser and the eviction DP against brute force.
- `tests/test_lean_examples.py` evaluates `theory.analytic` at every numeric
  instance proved in Lean.
- `tests/test_serq_models.py` runs serQ programs against queueing reference
  formulas and the adapters against alternate serQ scenarios.
- `tests/test_layers.py` fails if a module imports across the layers
  (theory importing serQ, sim, checks or report; sim importing checks;
  anything importing report).
- `tests/test_propositions.py` runs one test per named check (marker
  `checks`; `scripts/check_sim.sh` runs them through the report instead).
- `scripts/check_sim.sh` also fails if a check cites a Lean name that does
  not exist in `lean/ServingQueueTheory`.

## Modelling choices that matter

- **Service cost.** `CostModel.turn` is `overhead + a·new + b·new·(cached +
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
  the engine) as serQ programs (`sim.price_vllm`, `sim.open_vllm`, `sim.replay_vllm`).
- **Resume uncertainty.** Whether a program issues another turn is drawn
  when its tool call returns. A suspended program therefore holds KV that
  may never be reused, which is what gives `p_i` meaning in eviction.
- **Eviction scope.** The agentic serQ program evicts suspended programs
  first, then queued ones when needed. The vLLM scenarios use separate serQ
  programs with block-level KV and admission rules.
- **Prices.** The agentic serQ program uses its stage's online miss price for
  `Priced` and `PricedMemory` eviction.
- **Fetch mode (`agentic`).** `Async` fetches finish before the turn
  queues. `Blocking` fetches hold the replica for the tier wait plus the
  transfer, as when KV loading sits on the batch's critical path.
- **Batching (`Ps`).** The sampled-work serQ program gives each admitted
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

1. Write `def my_check() -> Check` in `src/checks.py` and add it
   to `ALL`; `tests/test_propositions.py` picks it up.
2. List only Lean theorems whose *statement* the check exercises, as the
   third argument of `Check`. `check_sim.sh` verifies that they exist.
3. Keep seeds fixed and tolerances explicit in `expected`. If a check
   needs a wide tolerance to pass, report it as an `Observation` instead.
