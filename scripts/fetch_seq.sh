#!/usr/bin/env bash
# seQ (https://github.com/vrvrv/seQ), the serving-deployment language: the
# Rust crate `seq-lang` (a Cargo git dependency of libqueuingsim), the CLI
# `seq-lang`, and the vLLM oracle with its test vectors (the Lean model of
# the language, lean/ServingQueueTheory/Seq*.lean, is generated from them).
# This script checks out the release pinned in libqueuingsim/Cargo.toml
# into .seq/src and installs its CLI into .seq/bin/seq-lang
# (`--src`: the checkout only).
set -euo pipefail
cd "$(dirname "$0")/.."
TAG=$(sed -n 's/^seq = {.*tag = "\([^"]*\)".*/\1/p' libqueuingsim/Cargo.toml)
[ -n "$TAG" ] || { echo "FAIL: no seQ tag in libqueuingsim/Cargo.toml"; exit 1; }
SRC_ONLY=0; [ "${1:-}" = "--src" ] && SRC_ONLY=1
if [ "$(cat .seq/tag 2>/dev/null)" != "$TAG" ]; then
  rm -rf .seq
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$TAG" https://github.com/vrvrv/seQ .seq/src
  echo "$TAG" > .seq/tag
fi
if [ $SRC_ONLY = 0 ] && [ ! -x .seq/bin/seq-lang ]; then
  # build with seQ's own pinned toolchain (.seq/src/rust-toolchain.toml)
  (cd .seq/src && export PATH="$HOME/.cargo/bin:$PATH" && { rustup toolchain install >/dev/null 2>&1 || true; } \
     && cargo install -q --locked --path . --root .. --force)
fi
echo "OK: seQ $TAG (.seq/src$([ $SRC_ONLY = 0 ] && echo ', .seq/bin/seq-lang'))"
