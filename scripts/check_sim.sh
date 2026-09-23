#!/usr/bin/env bash
# libqueuingsim: every Lean theorem a validation check cites must exist,
# then fmt + clippy + tests + validation report.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.cargo/bin:$PATH"
LEAN_DIR=${LEAN_DIR:-lean/ServingQueueTheory}

fail=0
names=$(awk '/lean: &\[/,/\]/' libqueuingsim/src/validation.rs | grep -oE '"[A-Za-z0-9_.]+"' | tr -d '"' | sort -u)
for n in $names; do
  if ! grep -rqE "^(theorem|lemma|def|noncomputable def) +${n}\b" "$LEAN_DIR"; then
    echo "MISSING in Lean: $n (cited in libqueuingsim/src/validation.rs)"; fail=1
  fi
done
echo "checked $(echo "$names" | wc -w) Lean names cited by validation checks"
[ "$fail" -eq 0 ] || exit 1

cd libqueuingsim
cargo fmt --check
cargo clippy --all-targets --locked -- -D warnings
cargo test --release --locked
cargo run --release --locked --example validate -- validation-report.md >/dev/null

# The paper's simulation tables and the data files behind the figures
# (paper/sim/data/*.csv) must be what the code produces now. The figure
# PDFs are not diffed (bytes depend on the matplotlib build); they are
# redrawn from the checked data below.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp" "$tmp.diff"' EXIT
cargo run --release --locked --quiet --example paper_tables -- "$tmp" 2>/dev/null
if ! diff -ru -x 'fig-*.pdf' ../paper/sim "$tmp" >"$tmp.diff"; then
  cat "$tmp.diff"
  echo "STALE: paper/sim/ differs from the simulator output."
  echo "       Regenerate: cd libqueuingsim && cargo run --release --example paper_tables && make figs"
  exit 1
fi
echo "paper/sim tables and data match the simulator ($(ls ../paper/sim/*.tex | wc -l) tables, $(ls ../paper/sim/data/*.csv | wc -l) data files)"

# Redraw the figures from the checked data; a plotting error fails the check.
cd ..
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
  echo "MISSING: uv (needed by scripts/plot_sim.py; run make setup)"; exit 1
fi
uv run --quiet --with matplotlib python scripts/plot_sim.py
echo "OK: libqueuingsim, $(tail -1 libqueuingsim/validation-report.md)"
