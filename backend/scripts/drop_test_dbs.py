"""Drop the test databases and cluster-global test roles a checkout leaves behind.

``conftest.py`` gives every (checkout, xdist worker) pair its own database and its
own role prefix so parallel runs and parallel checkouts don't collide. Those
persist on purpose — a warm database skips the migration — but a deleted worktree
has no way to clean up after itself, so they accumulate in the cluster.

    python scripts/drop_test_dbs.py           # this checkout's, and dry-run first
    python scripts/drop_test_dbs.py --yes     # actually drop them
    python scripts/drop_test_dbs.py --all --yes

Credentials come from POSTGRES_USER/POSTGRES_PASSWORD (the dev-compose bootstrap
superuser) and the host/port in DATABASE_URL, exactly as the suite does.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402

CHECKOUT_ID = hashlib.sha256(
    str(Path(__file__).resolve().parent.parent.parent).encode()
).hexdigest()[:8]


async def _connect() -> asyncpg.Connection:
    url = urlparse(settings.DATABASE_URL.replace("+asyncpg", ""))
    return await asyncpg.connect(
        user=os.environ.get("POSTGRES_USER", "initiative"),
        password=os.environ.get("POSTGRES_PASSWORD", "initiative"),
        host=url.hostname,
        port=url.port or 5432,
        database="postgres",
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="every checkout's, not just this one — run it when nothing is testing",
    )
    parser.add_argument("--yes", action="store_true", help="drop, instead of listing")
    args = parser.parse_args()

    scope = "" if args.all else f"{CHECKOUT_ID}_"
    db_like = f"initiative_test_{scope}%"
    mig_like = f"initiative_migrations_test_{scope}%"
    role_like = f"test_{scope}%"

    conn = await _connect()
    try:
        databases = [
            r["datname"]
            for r in await conn.fetch(
                "SELECT datname FROM pg_database WHERE datname LIKE $1 OR datname LIKE $2"
                " ORDER BY datname",
                db_like,
                mig_like,
            )
        ]
        roles = [
            r["rolname"]
            for r in await conn.fetch(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE $1 ORDER BY rolname",
                role_like,
            )
        ]

        where = "every checkout" if args.all else f"checkout {CHECKOUT_ID}"
        print(f"{len(databases)} database(s) and {len(roles)} role(s) for {where}")
        for name in databases:
            print(f"  db   {name}")
        for name in roles:
            print(f"  role {name}")

        if not args.yes:
            print("\nNothing dropped. Re-run with --yes to drop them.")
            return 0

        for name in databases:
            # FORCE disconnects a run that is still holding the database rather
            # than failing the whole sweep on it.
            await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            print(f"dropped db   {name}")
        for name in roles:
            # The roles' grants lived in the databases just dropped, so nothing
            # should own them by now; report the ones that still do.
            try:
                await conn.execute(f'DROP ROLE IF EXISTS "{name}"')
                print(f"dropped role {name}")
            except asyncpg.PostgresError as exc:
                print(f"kept role    {name}: {exc}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
