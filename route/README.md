# route

ROUTE: a language in which an LLM serving deployment is a program, with a
discrete-event interpreter. Spec, semantics, the vLLM correspondence and
the validation status are in `../docs/route-language.md`; the review of
the lecture's first version, the design and the tooling survey in
`../docs/route-review.md`; the formal model in
`../lean/ServingQueueTheory/Route.lean`.

```bash
make route                                   # from the repo root: fmt, clippy, tests, programs link
cargo run --release -- run programs/vllm.route --seed 2 --horizon 3000
cargo run --release -- run programs/agentic.route --set N=32 --set C=3e5 --set maxctx=1.5e5 --json
cargo run --release -- run programs/vllm_replay.route --set spacing=3 --dump /tmp/replay   # per-turn CSVs
cargo run --release -- check programs/replica.route
```

| Path | Contents |
|---|---|
| `src/lexer.rs`, `parser.rs`, `ast.rs` | surface syntax |
| `src/link.rs` | name resolution, constants, compiled expressions |
| `src/sim.rs` | the interpreter (pools, stages incl. the `step` engine, sessions) |
| `src/report.rs`, `stats.rs`, `trace.rs` | reports, statistics, trace corpora |
| `programs/*.route` | the deployments of the paper, the lecture and vLLM; `programs/data/*.csv` the replay traces |
| `tools/vllm_oracle.py`, `tools/oracle/` | the real vLLM v1 scheduler as an oracle and its recorded scenarios |
| `tests/` | pool semantics, vLLM scheduler behaviours, the oracle scenarios |

The cross-checks against the paper's closed forms and `libqueuingsim`'s
hand-written models are `../libqueuingsim/tests/route_*.rs` (`make sim`).
