"""Report long PostgreSQL waits in CI with bounded, literal-redacted SQL."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from typing import Any

import asyncpg

DEFAULT_DSN = "postgresql://initiative:initiative@localhost:5432/postgres"

ACTIVITY_SQL = """
SELECT
    pid,
    datname,
    usename,
    state,
    wait_event_type,
    wait_event,
    round(extract(epoch FROM clock_timestamp() - query_start)::numeric, 1) AS age_s,
    pg_blocking_pids(pid) AS blocking_pids
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
  AND wait_event_type = 'Lock'
  AND query_start <= clock_timestamp() - make_interval(secs => $1)
ORDER BY query_start, pid
"""

LOCK_SQL = """
SELECT
    locks.pid,
    locks.locktype,
    locks.mode,
    locks.granted,
    namespaces.nspname AS schema_name,
    classes.relname AS relation_name,
    locks.transactionid::text AS transaction_id
FROM pg_locks AS locks
LEFT JOIN pg_class AS classes ON classes.oid = locks.relation
LEFT JOIN pg_namespace AS namespaces ON namespaces.oid = classes.relnamespace
WHERE locks.pid = ANY($1::int[])
ORDER BY locks.pid, locks.granted, locks.locktype, locks.mode
"""

PARTICIPANT_SQL = """
SELECT
    pid,
    datname,
    usename,
    state,
    wait_event_type,
    wait_event,
    round(extract(epoch FROM clock_timestamp() - query_start)::numeric, 1) AS age_s,
    left(
        regexp_replace(query, $$'(?:''|[^'])*'$$, $$'<redacted>'$$, 'g'),
        300
    ) AS query_preview
FROM pg_stat_activity
WHERE pid = ANY($1::int[])
ORDER BY pid
"""


def _record(row: Any) -> dict[str, Any]:
    return dict(row)


async def report_once(conn: asyncpg.Connection, threshold_seconds: float) -> bool:
    """Print metadata for waits older than the threshold."""
    activities = await conn.fetch(ACTIVITY_SQL, threshold_seconds)
    if not activities:
        return False

    pids = {row["pid"] for row in activities}
    for row in activities:
        pids.update(row["blocking_pids"])
    participants = await conn.fetch(PARTICIPANT_SQL, sorted(pids))
    locks = await conn.fetch(LOCK_SQL, sorted(pids))

    print(
        "CI_POSTGRES_WAITS "
        + json.dumps([_record(row) for row in activities], default=str, sort_keys=True),
        flush=True,
    )
    print(
        "CI_POSTGRES_PARTICIPANTS "
        + json.dumps(
            [_record(row) for row in participants], default=str, sort_keys=True
        ),
        flush=True,
    )
    print(
        "CI_POSTGRES_LOCKS "
        + json.dumps([_record(row) for row in locks], default=str, sort_keys=True),
        flush=True,
    )
    return True


async def monitor(
    dsn: str,
    *,
    threshold_seconds: float,
    poll_seconds: float,
    once: bool,
) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        while True:
            await report_once(conn, threshold_seconds)
            if once:
                return
            await asyncio.sleep(poll_seconds)
    finally:
        await conn.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        default=os.environ.get("CI_POSTGRES_MONITOR_DSN", DEFAULT_DSN),
    )
    parser.add_argument("--threshold-seconds", type=float, default=5.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    asyncio.run(
        monitor(
            args.dsn,
            threshold_seconds=args.threshold_seconds,
            poll_seconds=args.poll_seconds,
            once=args.once,
        )
    )


if __name__ == "__main__":
    main()
