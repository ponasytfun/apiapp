#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"

if ! command -v cargo >/dev/null 2>&1; then
  echo "Rust/Cargo was not found. Install Rust from https://rustup.rs and try again."
  exit 1
fi

exec cargo run --release
