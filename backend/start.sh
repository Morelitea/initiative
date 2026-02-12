#!/bin/sh
set -e

ARGS="app.main:app --host 0.0.0.0 --port 8173"

if [ "${BEHIND_PROXY:-false}" = "true" ]; then
    FORWARDED_IPS="${FORWARDED_ALLOW_IPS:-*}"
    ARGS="$ARGS --proxy-headers --forwarded-allow-ips=$FORWARDED_IPS"
fi

exec uvicorn $ARGS
