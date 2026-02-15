#!/usr/bin/env bash
# Start Vite dev server with nvm-managed pnpm
set -e
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

# Kill any stale Vite process on port 5173
lsof -ti:5173 2>/dev/null | xargs -r kill 2>/dev/null || true
sleep 0.5

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../frontend"
pnpm dev
