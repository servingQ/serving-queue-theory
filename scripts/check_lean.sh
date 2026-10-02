#!/usr/bin/env bash
# Build the Lean project, then audit for `sorry` and non-standard axioms.
set -euo pipefail
cd "$(dirname "$0")/../lean"

echo "== lake build =="
lake build 2>&1 | tee build.log
if grep -q "declaration uses 'sorry'" build.log; then
  echo "FAIL: a declaration uses sorry"; exit 1
fi
if grep -rn --include='*.lean' -E '\bsorry\b' ServingQueueTheory ServingQueueTheory.lean; then
  echo "FAIL: literal 'sorry' found in sources"; exit 1
fi

echo "== serQ: the Lean pin runs the pinned release's IR and semantics =="
# lean/lakefile.toml pins serQ's Lean package at a commit; the validation
# package and fetch_serq.sh run the release in validation/pyproject.toml.
# Between the two, the interpreter (src/) and the IR the oracle theorems are
# generated from (tools/oracle/) may not differ.
TAG=$(sed -n '/^\[tool\.serq\]/,/^\[/ s/^tag = "\([^"]*\)".*/\1/p' ../validation/pyproject.toml)
PKG=.lake/packages/Serq
git -C "$PKG" rev-parse -q --verify "refs/tags/$TAG" >/dev/null || git -C "$PKG" fetch -q origin tag "$TAG"
# (a change of comments only, `//` lines, does not count)
if ! git -C "$PKG" diff --quiet -I'^[[:space:]]*//' "$TAG" HEAD -- src tools/oracle; then
  echo "FAIL: serQ's Lean pin ($(git -C "$PKG" rev-parse --short HEAD)) and the release $TAG differ in src/ or tools/oracle/:"
  git -C "$PKG" diff --stat -I'^[[:space:]]*//' "$TAG" HEAD -- src tools/oracle; exit 1
fi
echo "OK: the Lean pin and $TAG have the same interpreter and oracle IR"

echo "== axiom audit =="
lake env lean scripts/AxiomAudit.lean 2>&1 | perl -0pe 's/\n[ \t]+/ /g' | tee axioms.log
# Every line looks like: 'ServingQueueTheory.foo' depends on axioms: [propext, Classical.choice, Quot.sound]
# Strip the allowed axioms and fail if anything remains inside the brackets.
BAD=$(sed -n "s/.*depends on axioms: \[\(.*\)\]/\1/p" axioms.log \
      | tr ',' '\n' | sed 's/^ *//; s/ *$//' \
      | grep -v -E '^(propext|Classical\.choice|Quot\.sound)$' | grep -v '^$' || true)
if [ -n "$BAD" ]; then
  echo "FAIL: non-standard axioms used:"; echo "$BAD"; exit 1
fi
if grep -q "does not depend on any axioms" axioms.log; then :; fi
N=$(grep -c "depends on axioms\|does not depend on any axioms" axioms.log || true)
echo "OK: $N theorems audited; only standard axioms used."
