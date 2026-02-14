#!/usr/bin/env bash
# Wait for Postgres to be ready (up to 30 seconds)
for i in $(seq 1 30); do
    if pg_isready -h localhost -p 5432 -U initiative 2>/dev/null; then
        echo "Postgres is ready!"
        exit 0
    fi
    echo "Waiting for Postgres... ($i/30)"
    sleep 1
done
echo "Timed out waiting for Postgres"
exit 1
