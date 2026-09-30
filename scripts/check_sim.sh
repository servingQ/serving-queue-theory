#!/usr/bin/env bash
# validation: every Lean theorem a validation check cites must exist, then
# ruff (format + lint), pytest (units, Lean instances, seQ adapters) and the
# validation report, which runs every named check and fails if one fails.
# Needs the seQ CLI pinned in validation/pyproject.toml (`make seq`).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
LEAN_DIR=${LEAN_DIR:-lean/ServingQueueTheory}

fail=0
names=$(python3 - <<'PY'
import ast
tree = ast.parse(open("validation/src/validation/checks.py").read())
names = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Check":
        names |= {e.value for e in node.args[2].elts}
print("\n".join(sorted(names)))
PY
)
for n in $names; do
  if ! grep -rqE "^(theorem|lemma|def|noncomputable def) +${n}\b" "$LEAN_DIR"; then
    echo "MISSING in Lean: $n (cited in validation/src/validation/checks.py)"; fail=1
  fi
done
echo "checked $(echo "$names" | wc -w) Lean names cited by validation checks"
[ "$fail" -eq 0 ] || exit 1

# The replay scenario's cost model is calibrated on the testbed: the constants
# must equal the cost fit (3 significant figures) where the fit is present.
if [ -f data/exp/e1/fit.json ]; then
  python3 - <<'PY' || exit 1
import json, re
fit = json.load(open("data/exp/e1/fit.json"))
src = open("validation/src/validation/constants.py").read()
def const(name):
    return float(re.search(rf"^{name} = ([0-9.e+-]+)", src, re.M).group(1))
bad = [n for n, k in [("CAL_PREFILL_LINEAR", "a"), ("CAL_PREFILL_QUADRATIC", "b"), ("CAL_PREFILL_OVERHEAD", "c0")]
       if f"{const(n):.3g}" != f"{fit[k]:.3g}"]
if bad:
    print("FAIL: calibrated constants differ from data/exp/e1/fit.json:", bad); raise SystemExit(1)
print("calibrated cost constants match data/exp/e1/fit.json")
PY
fi

cd validation
uv run --locked --quiet ruff format --check .
uv run --locked --quiet ruff check .
uv run --locked --quiet pytest -q -m "not checks"
uv run --locked --quiet python -m validation.report validation-report.md >/dev/null
echo "OK: validation, $(tail -1 validation-report.md)"
