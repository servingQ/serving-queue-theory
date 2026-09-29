#!/usr/bin/env bash
# seQ (https://github.com/vrvrv/seQ), the serving-deployment language: the CLI
# `seq-lang` that the validation package runs, the example programs, and the
# vLLM oracle with its test vectors (the Lean model of the language,
# lean/ServingQueueTheory/Seq*.lean, is generated from them). This script
# checks out the release pinned in validation/pyproject.toml ([tool.seq])
# into .seq/src and builds its CLI into .seq/bin/seq-lang with seQ's own
# pinned Rust toolchain (`--src`: the checkout only).
set -euo pipefail
cd "$(dirname "$0")/.."
PIN=validation/pyproject.toml
TAG=$(sed -n '/^\[tool\.seq\]/,/^\[/ s/^tag = "\([^"]*\)".*/\1/p' $PIN)
REV=$(sed -n '/^\[tool\.seq\]/,/^\[/ s/^rev = "\([^"]*\)".*/\1/p' $PIN)
[ -n "$TAG" ] || [ -n "$REV" ] || { echo "FAIL: no seQ tag or rev under [tool.seq] in $PIN"; exit 1; }
REF=${REV:-$TAG}
SRC_ONLY=0; [ "${1:-}" = "--src" ] && SRC_ONLY=1
if [ "$(cat .seq/tag 2>/dev/null)" != "$REF" ]; then
  rm -rf .seq
  if [ -n "$REV" ]; then
    mkdir -p .seq/src
    git -C .seq/src init -q
    git -C .seq/src -c advice.detachedHead=false fetch -q --depth 1 https://github.com/vrvrv/seQ "$REV"
    git -C .seq/src -c advice.detachedHead=false checkout -q FETCH_HEAD
  else
    git -c advice.detachedHead=false clone -q --depth 1 --branch "$TAG" https://github.com/vrvrv/seQ .seq/src
  fi
  echo "$REF" > .seq/tag
fi
if [ $SRC_ONLY = 0 ] && [ ! -x .seq/bin/seq-lang ]; then
  # build with seQ's own pinned toolchain (.seq/src/rust-toolchain.toml)
  (cd .seq/src && export PATH="$HOME/.cargo/bin:$PATH" && { rustup toolchain install >/dev/null 2>&1 || true; } \
     && cargo install -q --locked --path . --root .. --force)
fi
echo "OK: seQ $REF (.seq/src$([ $SRC_ONLY = 0 ] && echo ', .seq/bin/seq-lang'))"
