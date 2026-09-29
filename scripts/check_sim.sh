#!/usr/bin/env bash
# validation: every Lean theorem a validation check cites must exist,
# then fmt + clippy + tests + validation report.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.cargo/bin:$PATH"
LEAN_DIR=${LEAN_DIR:-lean/ServingQueueTheory}

fail=0
names=$(awk '/lean: &\[/,/\]/' validation/src/validation.rs | grep -oE '"[A-Za-z0-9_.]+"' | tr -d '"' | sort -u)
for n in $names; do
  if ! grep -rqE "^(theorem|lemma|def|noncomputable def) +${n}\b" "$LEAN_DIR"; then
    echo "MISSING in Lean: $n (cited in validation/src/validation.rs)"; fail=1
  fi
done
echo "checked $(echo "$names" | wc -w) Lean names cited by validation checks"
[ "$fail" -eq 0 ] || exit 1

cd validation
cargo fmt --check
cargo clippy --all-targets --locked -- -D warnings
cargo test --release --locked
cargo run --release --locked --example validate -- validation-report.md >/dev/null

# The replay scenario's cost model is calibrated on the testbed: the constants
# in validation.rs must equal the E1 fit (3 significant figures).
if [ -f data/exp/e1/fit.json ]; then
  python3 - <<'PY' || exit 1
import json, re
fit = json.load(open("data/exp/e1/fit.json"))
src = open("validation/src/validation.rs").read()
def const(name):
    return float(re.search(rf"pub const {name}: f64 = ([0-9.e+-]+);", src).group(1))
bad = [n for n, k in [("CAL_PREFILL_LINEAR", "a"), ("CAL_PREFILL_QUADRATIC", "b"), ("CAL_PREFILL_OVERHEAD", "c0")]
       if f"{const(n):.3g}" != f"{fit[k]:.3g}"]
if bad:
    print("FAIL: calibrated constants differ from data/exp/e1/fit.json:", bad); raise SystemExit(1)
print("calibrated cost constants match data/exp/e1/fit.json")
PY
fi
echo "OK: validation, $(tail -1 validation-report.md)"
