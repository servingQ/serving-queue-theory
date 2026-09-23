#!/usr/bin/env bash
# Every \leanref{Name} in the paper must name a theorem/def that exists in
# the Lean sources, and every paper-facing theorem must be in the axiom audit.
set -euo pipefail
cd "$(dirname "$0")/.."
fail=0
refs=$(sed 's/%.*//' paper/main.tex | grep -oE '\\leanref\{[^}]+\}' | sed -E 's/\\leanref\{([^}]+)\}/\1/; s/\\_/_/g' | sort -u)
for r in $refs; do
  short=${r##*.}
  if ! grep -rqE "^(theorem|lemma|def|noncomputable def|structure|inductive) +${short}\b" lean/ServingQueueTheory lean/ServingQueueTheory.lean; then
    echo "MISSING in Lean: $r"; fail=1
  fi
done
echo "checked $(echo "$refs" | wc -w) \\leanref citations"
# every proposition and example block must name its Lean proof via \provedby
missing=$(sed 's/%.*//' paper/main.tex | awk '
  /\\begin\{(proposition|example)\}/ { inblk=1; has=0; hdr=$0; ln=NR }
  inblk && /\\provedby\{/ { has=1 }
  inblk && /\\end\{(proposition|example)\}/ { if (!has) print "line " ln ": " hdr; inblk=0 }')
if [ -n "$missing" ]; then
  echo "NO \\provedby in:"; echo "$missing"; fail=1
fi
# theorems referenced in the paper should also be axiom-audited
for r in $refs; do
  short=${r##*.}
  if grep -rqE "^theorem +${short}\b" lean/ServingQueueTheory; then
    if ! grep -qE "#print axioms .*\b${short}\b" lean/scripts/AxiomAudit.lean; then
      echo "NOT AUDITED: $short (add '#print axioms' to lean/scripts/AxiomAudit.lean)"; fail=1
    fi
  fi
done
exit $fail
