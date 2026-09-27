#!/usr/bin/env bash
# route: the ROUTE language crate (parser, interpreter, CLI). fmt + clippy +
# tests (pool semantics, vLLM scheduler scenarios against the upstream
# oracle in route/tools/oracle) and a static check of every program in
# route/programs. The cross-checks against libqueuingsim's hand-written
# models and the paper's closed forms run under scripts/check_sim.sh
# (libqueuingsim/tests/route_*.rs).
set -euo pipefail
cd "$(dirname "$0")/../route"
export PATH="$HOME/.cargo/bin:$PATH"
cargo fmt --check
cargo clippy --all-targets --locked -- -D warnings
cargo test --release --locked
cargo build --release --locked --quiet
n=0
for f in programs/*.route; do
  ./target/release/route check "$f" >/dev/null || { echo "FAIL: $f does not link"; exit 1; }
  n=$((n + 1))
done
cd ..
python3 scripts/check_oracle_gpu.py
python3 scripts/gen_route_oracle.py --check
echo "OK: route, $n programs link, $(ls route/tools/oracle/*.out.json | wc -l) vLLM oracle scenarios + 1 prefix-cache trace (CPU oracle = A100 engine = ROUTE = Lean)"
