#!/usr/bin/env bash
# Run database migrations and seed superuser
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../backend"

# Dev superuser defaults (launch.json sets these for the debug process,
# but preLaunchTask scripts need them too)
export FIRST_SUPERUSER_EMAIL="${FIRST_SUPERUSER_EMAIL:-user@example.com}"
export FIRST_SUPERUSER_PASSWORD="${FIRST_SUPERUSER_PASSWORD:-abc123}"
export FIRST_SUPERUSER_FULL_NAME="${FIRST_SUPERUSER_FULL_NAME:-Dungeon Master}"

source .venv/bin/activate
python -m app.db.init_db
