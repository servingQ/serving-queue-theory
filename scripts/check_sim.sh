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

# The paper's simulation tables must be what the code produces now.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cargo run --release --locked --quiet --example paper_tables -- "$tmp" 2>/dev/null
if ! diff -ru ../paper/sim "$tmp" >"$tmp.diff"; then
  cat "$tmp.diff"
  echo "STALE: paper/sim/ differs from the simulator output."
  echo "       Regenerate: cd libqueuingsim && cargo run --release --example paper_tables"
  exit 1
fi
echo "paper/sim tables match the simulator ($(ls ../paper/sim | wc -l) files)"
echo "OK: libqueuingsim, $(tail -1 validation-report.md)"
