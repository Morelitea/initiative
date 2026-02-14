#!/usr/bin/env bash
# Seed TTRPG dev data
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../backend"
source .venv/bin/activate
python "$SCRIPT_DIR/seed_dev_data.py"
