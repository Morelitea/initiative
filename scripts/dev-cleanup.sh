#!/usr/bin/env bash
# Remove seeded dev data
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../backend"

# Dev superuser defaults
export FIRST_SUPERUSER_EMAIL="${FIRST_SUPERUSER_EMAIL:-admin@example.com}"
export FIRST_SUPERUSER_PASSWORD="${FIRST_SUPERUSER_PASSWORD:-changeme}"
export FIRST_SUPERUSER_FULL_NAME="${FIRST_SUPERUSER_FULL_NAME:-Admin User}"

source .venv/bin/activate
python "$SCRIPT_DIR/seed_dev_data.py" --clean
