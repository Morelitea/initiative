#!/usr/bin/env bash
# Run database migrations and seed the dev owner
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../backend"

. "$SCRIPT_DIR/dev-owner.sh"

source .venv/bin/activate
python -m app.db.init_db
