#!/usr/bin/env bash
# Seed TTRPG dev data
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../backend"

# Dev superuser defaults
export FIRST_SUPERUSER_EMAIL="${FIRST_SUPERUSER_EMAIL:-admin@example.com}"
export FIRST_SUPERUSER_PASSWORD="${FIRST_SUPERUSER_PASSWORD:-changeme}"
export FIRST_SUPERUSER_FULL_NAME="${FIRST_SUPERUSER_FULL_NAME:-Admin User}"

source .venv/bin/activate
# The app imports alone take a few seconds before the seeder prints anything.
echo "Seeding dev data (loading the app first — this stays quiet for a moment)..."
python "$SCRIPT_DIR/seed_dev_data.py"
