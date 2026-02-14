#!/usr/bin/env bash
# Start uvicorn dev server
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../backend"

# Dev superuser defaults
export FIRST_SUPERUSER_EMAIL="${FIRST_SUPERUSER_EMAIL:-admin@example.com}"
export FIRST_SUPERUSER_PASSWORD="${FIRST_SUPERUSER_PASSWORD:-changeme}"
export FIRST_SUPERUSER_FULL_NAME="${FIRST_SUPERUSER_FULL_NAME:-Admin User}"

# Kill any stale uvicorn on port 8000
lsof -ti:8000 2>/dev/null | xargs -r kill 2>/dev/null || true
sleep 0.5

source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
