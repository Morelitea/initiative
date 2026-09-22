#!/bin/sh
set -e

# Resolve uvicorn/alembic/python from the uv-managed venv even if the runtime
# overrode the image's ENV PATH (e.g. Synology re-applying a stale container env).
export PATH="/app/.venv/bin:$PATH"

# Built as positional parameters rather than one string: every value below
# comes from the environment, and a path or address with a space in it has to
# survive reaching uvicorn as the single argument it is.
set -- app.main:app --host 0.0.0.0 --port 8173

if [ "${BEHIND_PROXY:-false}" = "true" ]; then
    set -- "$@" --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}"
fi

# Serve HTTPS here, for a deployment that holds a certificate and runs no
# reverse proxy in front. Both halves are required together: one on its own is
# a half-written setting rather than a choice, so it stops here and says which
# is missing.
if [ -n "${TLS_CERT_FILE:-}" ] || [ -n "${TLS_KEY_FILE:-}" ]; then
    if [ -z "${TLS_CERT_FILE:-}" ]; then
        echo "ERROR: TLS_KEY_FILE is set but TLS_CERT_FILE is not." >&2
        echo "Set both to serve HTTPS, or neither to serve HTTP." >&2
        exit 1
    fi
    if [ -z "${TLS_KEY_FILE:-}" ]; then
        echo "ERROR: TLS_CERT_FILE is set but TLS_KEY_FILE is not." >&2
        echo "Set both to serve HTTPS, or neither to serve HTTP." >&2
        exit 1
    fi
    set -- "$@" --ssl-certfile="$TLS_CERT_FILE" --ssl-keyfile="$TLS_KEY_FILE"
fi

exec uvicorn "$@"
