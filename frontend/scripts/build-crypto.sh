#!/usr/bin/env bash
# Rebuild the ratchet's WebAssembly artifact from `crypto/`.
#
# The output is committed, the way the Orval client is, so the frontend builds
# without a Rust toolchain and only this script needs one. Run it whenever
# `crypto/src` or `crypto/Cargo.toml` changes, and commit what it writes.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"

if ! command -v wasm-pack >/dev/null 2>&1; then
  echo "wasm-pack is not installed. cargo install wasm-pack" >&2
  exit 1
fi

cd "$root/crypto"
wasm-pack build \
  --target web \
  --release \
  --out-dir "$root/frontend/src/crypto/wasm" \
  --out-name initiative_ratchet

# wasm-pack writes a .gitignore that would hide the artifact it just built.
rm -f "$root/frontend/src/crypto/wasm/.gitignore"
echo "built $root/frontend/src/crypto/wasm"
