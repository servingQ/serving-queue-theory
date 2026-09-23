#!/usr/bin/env bash
# Claude Code PostToolUse hook (Edit|Write). Reads the tool payload on stdin,
# and if a Lean or paper file changed, runs the matching check and reports
# problems back to the model as additionalContext. Never blocks.
set -uo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.elan/bin:$HOME/.local/bin:$PATH"

f=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path") or d.get("tool_response",{}).get("filePath") or "")' 2>/dev/null)
[ -z "$f" ] && exit 0

emit() {  # $1 = message
  python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":sys.argv[1]}}))' "$1"
}

case "$f" in
  *.lean)
    out=$(cd lean && lake build 2>&1 | grep -vE "^(✔|⚠ \[|trace:)" | grep -E "error|sorry|warning: .*unused|Build completed" | head -30)
    if echo "$out" | grep -qE "error|sorry"; then
      emit "lake build after editing ${f#$PWD/}:"$'\n'"$out"
    fi
    ;;
  */paper/main.tex)
    out=$(scripts/check_lean_refs.sh 2>&1)
    if echo "$out" | grep -qE "MISSING|NOT AUDITED"; then
      emit "check_lean_refs after editing paper/main.tex:"$'\n'"$out"
    fi
    ;;
esac
exit 0
