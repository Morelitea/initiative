#!/usr/bin/env bash
# Start Vite dev server with nvm-managed pnpm
set -e
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Sets VITE_DEV_PORT (the port vite.config.ts binds), plus VITE_API_URL and
# VITE_DEV_PROXY_TARGET so the app and its proxy reach this checkout's backend.
. "$SCRIPT_DIR/dev-ports.sh"
# dev-ports.sh has already said why if it could not resolve them.
[ -n "${DEV_BACKEND_PORT:-}" ] || exit 1

cd "$SCRIPT_DIR/../frontend"
# Forward extra args to Vite (e.g. --open, passed by the dev setup tasks to
# launch the browser once the server is up). Bare `pnpm dev` stays open-free.
pnpm dev "$@"
