#!/usr/bin/env bash
# Start uvicorn dev server
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/dev-ports.sh"
# dev-ports.sh has already said why if it could not resolve them.
[ -n "${DEV_BACKEND_PORT:-}" ] || exit 1
cd "$SCRIPT_DIR/../backend"

. "$SCRIPT_DIR/dev-owner.sh"

source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port "$DEV_BACKEND_PORT"
