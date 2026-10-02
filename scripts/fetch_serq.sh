#!/usr/bin/env bash
# serQ (https://github.com/servingQ/serQ), the serving-deployment language: the
# example programs the validation package runs with pyserq (from PyPI, the
# same release), the vLLM oracle with its
# test vectors (serQ's lean/Serq/Oracle.lean is generated from
# them), and the CLI `serq` the scripts in scripts/exp run. This script
# checks out the release pinned in validation/pyproject.toml ([tool.serq])
# into .serq/src and builds its CLI into .serq/bin/serq with serQ's own
# pinned Rust toolchain (`--src`: the checkout only).
set -euo pipefail
cd "$(dirname "$0")/.."
PIN=validation/pyproject.toml
TAG=$(sed -n '/^\[tool\.serq\]/,/^\[/ s/^tag = "\([^"]*\)".*/\1/p' $PIN)
REV=$(sed -n '/^\[tool\.serq\]/,/^\[/ s/^rev = "\([^"]*\)".*/\1/p' $PIN)
[ -n "$TAG" ] || [ -n "$REV" ] || { echo "FAIL: no serQ tag or rev under [tool.serq] in $PIN"; exit 1; }
REF=${REV:-$TAG}
SRC_ONLY=0; [ "${1:-}" = "--src" ] && SRC_ONLY=1
if [ "$(cat .serq/tag 2>/dev/null)" != "$REF" ]; then
  rm -rf .serq
  if [ -n "$REV" ]; then
    mkdir -p .serq/src
    git -C .serq/src init -q
    git -C .serq/src -c advice.detachedHead=false fetch -q --depth 1 https://github.com/servingQ/serQ "$REV"
    git -C .serq/src -c advice.detachedHead=false checkout -q FETCH_HEAD
  else
    git -c advice.detachedHead=false clone -q --depth 1 --branch "$TAG" https://github.com/servingQ/serQ .serq/src
  fi
  echo "$REF" > .serq/tag
fi
if [ $SRC_ONLY = 0 ] && [ ! -x .serq/bin/serq ]; then
  # build with serQ's own pinned toolchain (.serq/src/rust-toolchain.toml)
  (cd .serq/src && export PATH="$HOME/.cargo/bin:$PATH" && { rustup toolchain install >/dev/null 2>&1 || true; } \
     && cargo install -q --locked --path . --root .. --force)
fi
echo "OK: serQ $REF (.serq/src$([ $SRC_ONLY = 0 ] && echo ', .serq/bin/serq'))"
