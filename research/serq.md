# serQ: the serving-deployment language, and how this repository uses it

serQ is the language in which a serving deployment is a program: memory
pools and stages, a workload, and the program every session runs. Since
2026-09-27 it is its own project, https://github.com/vrvrv/serQ (private).
serQ holds the Rust interpreter and CLI (crate `serq`, library `serq`,
binary `serq`), the example programs (`examples/*/*.sq`, incl. the vLLM
v1 engine and its A100 replay), the vLLM scheduler oracle with its test
vectors (`tools/oracle/`, the A100 engine's answers), the language spec
(`docs/language.md`) and the review and tooling survey (`docs/review.md`).
serQ also holds the Lean model of the language (its `lean/` package
`Serq`, serQ `docs/lean.md`, since 2026-10-01; before that it lived here).
The Lean `Route` type and `[route| … ]` quotation are names in that formal
fragment, not the current serQ surface syntax.

A serQ program is defined by its IR (serQ `docs/ir.md`): a versioned JSON
data structure that the interpreter runs and tools build or edit. The text
syntax compiles to it. This repository requires serQ's Lean package and
proves its queueing results from it, and uses one pinned serQ release:

| Here | What it is | What it takes from serQ |
|---|---|---|
| `lean/lakefile.toml` (`[[require]] Serq`) | serQ's Lean package at a pinned commit: `Serq/Core` (syntax, pool semantics, invariant), `Serq/Exec` (executable semantics, ℕ step clock), `Serq/Serve` (serving order, cited in §2.2), `Serq/Oracle` (the vLLM scenarios as theorems, generated in serQ from `tools/oracle/*.ir.json`) | serQ `lean/`; its own `make lean` builds and audits it |
| `lean/ServingQueueTheory/Deployments.lean` | the paper's two replicas as serQ programs | `Serq.Core` |
| `validation/` | the validation package: every simulation of the paper as a serQ program (`src/sim/`), checked against closed forms that never import serQ (`src/theory/`); `tests/test_serq_models.py` checks serQ programs against closed forms | pyserq (PyPI, the pinned release), `.serq/src/examples` |
| `programs/replay_vllm.sq`, `validation/src/sim/replay_vllm.py` | §4.2's vLLM-rule replay; `scripts/exp/serq_replay42.py` runs LRU and finished-session ablations (`research/serq-replay42.md`) | pyserq; `.serq/bin/serq` for the ablations |
| `scripts/exp/*serq*`, `diff_serq_vllm.sh`, `first_divergence.sh` | testbed comparisons and calibration; each run passes the trace with `--trace` and records what ran as IR (`program.ir.json`) | `.serq/bin/serq`, `.serq/src/examples`, `.serq/src/tools` |

The pin is `v0.1.1` under `[tool.serq]` in `validation/pyproject.toml`, IR 10, and its
pyserq, `pyserq==0.1.1` from PyPI, is the validation package's engine:
`tests/test_units.py` holds pyserq's version equal to the checkout's
`[workspace.package] version` in `.serq/src/Cargo.toml` and to the
`pyserq==` dependency, and, when a tag is pinned, the tag to `v{version}`.
`sim/serq.py` uses pyserq's
report objects and adds only numpy arrays of the samples,
`sim/workload.py` reads a trace with `pyserq.read_trace`, and `theory`
draws from `pyserq.Rng` (rand 0.9's `StdRng`). `agentic_model.sq` and
`batch_sampled.sq` name their laws, class parameters and policy keys as
expression `def`s, which the adapters give bodies with `defs=` (`--def`);
the IR is the one the spliced text had. serQ's own examples do the same
(#192): `pd_tandem` and `pd_open` name `prefill_work`, `decode_work`,
`kv_tokens`, `routing` the four session laws, and `mg1` its `service` law and
`servers` (a `let`, given by `sets=`). The one splice left is `mg1`'s
`arrive poisson(lam)` → `arrive renewal(...)`, which changes the kind of the
arrival declaration. IR 10 makes a hold's `cache` clause what
consumes the session's own cached prefix (serQ #234: a hold without it
leaves the entry where it is, so a reservation written around the
request's hold on the same pool no longer costs it its hit; `cache (0)` is
the old meaning); the Lean `admit` follows, and no program here
holds a pool with entries without `cache`, so the oracle theorems and the
validation numbers are unchanged. IR 9 orders a
pool's waiting queue when a request is selected; no program here uses
`queue by`, so their FIFO queues keep their meaning. IR 6 added renewal
arrivals and requires finite runs to finish within their horizon; the queue
adapter retries deadline errors with the same seed and a larger horizon
(up to eight attempts). The oracle generator rejects finite arrival limits
and renewal workloads outside its explicit-session fragment. `scripts/fetch_serq.sh`
(`make serq`, first step of `make check`) checks that tag out into
`.serq/src` and installs its CLI into `.serq/bin/serq` (gitignored); `uv sync` in
`validation/` installs pyserq from PyPI, so the validation package needs no
Rust (the CLI, for `scripts/exp`, still does).

## Moving to a new serQ release

1. In serQ: bump `version` in `Cargo.toml`, push, then
   `git tag -a vX.Y.Z-rcN && git push origin vX.Y.Z-rcN` (or `vX.Y.Z`); the tag message body is the release notes.
   The release workflow runs the checks and publishes the GitHub release
   (a tag with a dash is a prerelease).
2. Here: change the tag under `[tool.serq]` (drop a `rev`, which wins
   over it) and the `pyserq==` version in `validation/pyproject.toml`
   together; `tests/test_units.py` fails unless pyserq, the checkout's
   `Cargo.toml` version and the tag are one version (a prerelease `vX.Y.Z-rcN` has no
   PyPI wheel: point `[tool.uv.sources] pyserq` at `../.serq/src/pyserq`
   meanwhile), `uv lock`, then `make check` (`make serq` checks out and
   builds the new release). Move the Lean pin with it: set `rev` of the
   `Serq` requirement in `lean/lakefile.toml` to the release's commit and
   run `cd lean && lake update Serq`. The Lean pin may run ahead of the
   release only in `lean/` and docs: `scripts/check_lean.sh` fails if the
   pinned commit's `src/` or `tools/oracle/` differs from the release tag.
   Today it is `79c6add` (v0.1.1 plus serQ#245, the Lean package, no change
   to the interpreter or the IR), until v0.1.2. The oracle theorems are
   regenerated in serQ (`scripts/gen_lean_oracle.py`, checked by its
   `make lean`), not here.

In serQ, the multi-turn prefix-cache theorem is generated the same way: its IR
(`tools/oracle/cache_trace.ir.json`) is `examples/replay/vllm_replay.sq` on a
unit step clock with the trace inlined as the sessions' turns, and the
Lean executable semantics reads those turns at every `turn` statement
(`Exec.Workload`) with serQ's rule.

## Access

serQ is private. Locally, git authenticates through the `gh` credential
helper of an account that can read serQ. CI uses a read-only deploy key: the public
half on vrvrv/serQ, the private half in `SERQ_DEPLOY_KEY` of this
repository (`.github/actions/serq-access`). The workflow falls back to the
existing `SEQ_DEPLOY_KEY` secret until the new secret is provisioned; GitHub
does not expose a secret's value for renaming. New installations use only
`SERQ_DEPLOY_KEY`. To create it:

```bash
ssh-keygen -t ed25519 -N "" -C "serving-queue-theory CI (read serQ)" -f /tmp/serq_deploy
gh repo deploy-key add /tmp/serq_deploy.pub -R vrvrv/serQ -t "serving-queue-theory CI"
gh secret set SERQ_DEPLOY_KEY -R vrvrv/serving-queue-theory < /tmp/serq_deploy
rm /tmp/serq_deploy /tmp/serq_deploy.pub
```

## Historical evidence

The experiment directories `data/exp/seq/`, `data/exp/gpu_seq/` and
`data/exp/gpu/seq*` keep their acquisition names. They are external measurement
and comparison artifacts, not runtime names. Analysis scripts still read them;
renaming the source data in prose would break reproducibility.
`research/lecture-results.json` likewise records the previous CLI's actual
binary name and commit. The optional baseline verifier reads that release's
`.seq` source files. Current programs, commands and documentation use serQ and
`.sq`; the baseline metadata is not a claim about today's runtime.
