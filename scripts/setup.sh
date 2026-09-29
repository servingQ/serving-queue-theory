#!/usr/bin/env bash
# Idempotent, user-local toolchain setup. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p "$HOME/.local/bin"
export PATH="$HOME/.elan/bin:$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

if ! command -v elan >/dev/null; then
  echo "== installing elan"
  curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
    | sh -s -- -y --default-toolchain none
fi

if ! command -v rustup >/dev/null; then
  echo "== installing rustup (toolchain pinned by paper-validation/rust-toolchain.toml)"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain none --no-modify-path
fi

if ! command -v tectonic >/dev/null; then
  echo "== installing tectonic 0.17.0"
  curl -sSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.17.0/tectonic-0.17.0-x86_64-unknown-linux-musl.tar.gz" \
    | tar xz -C "$HOME/.local/bin" tectonic
fi

if ! command -v uv >/dev/null; then
  echo "== installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
fi

echo "== Lean toolchain + Mathlib cache"
( cd lean && lake exe cache get >/dev/null && lake build 2>&1 | tail -1 )

echo "== Rust toolchain + paper-validation build"
( cd paper-validation && rustup toolchain install >/dev/null && cargo build --release --quiet )

echo
echo "$(cd paper-validation && cargo --version) | elan $(elan --version | cut -d' ' -f2) | $(cd lean && lean --version) | $(tectonic --version) | $(uv --version)"
echo "OK. Try: make check"
