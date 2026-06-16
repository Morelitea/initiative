#!/bin/sh
set -e

# Resolve uvicorn/alembic/python from the uv-managed venv even if the runtime
# overrode the image's ENV PATH (e.g. Synology re-applying a stale container env).
export PATH="/app/.venv/bin:$PATH"

ARGS="app.main:app --host 0.0.0.0 --port 8173"

if [ "${BEHIND_PROXY:-false}" = "true" ]; then
    FORWARDED_IPS="${FORWARDED_ALLOW_IPS:-*}"
    ARGS="$ARGS --proxy-headers --forwarded-allow-ips=$FORWARDED_IPS"
fi

# shellcheck disable=SC2086
exec uvicorn $ARGS
