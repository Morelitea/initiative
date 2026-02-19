"""Alembic environment configuration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.core.config import settings  # noqa: E402
from app.db import base  # noqa: F401,E402  # ensure models are imported

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# Only set URL for CLI invocations. When called programmatically via
# run_migrations(), _get_alembic_config() already sets the URL and marks
# url_configured=True so we don't override it here.
if not config.attributes.get("url_configured"):
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = SQLModel.metadata


def _process_revision_directives(context, revision, directives):
    """Set the revision ID to YYYYMMDD_NNNN (date + sequential number)."""
    if not directives:
        return
    now = datetime.now(timezone.utc)
    date_prefix = now.strftime("%Y%m%d")

    # Find the highest existing revision number for any date
    versions_dir = Path(__file__).parent / "versions"
    max_seq = 0
    for f in versions_dir.glob("*.py"):
        name = f.stem
        # Match pattern: YYYYMMDD_NNNN_...
        if len(name) >= 13 and name[8] == "_" and name[:8].isdigit() and name[9:13].isdigit():
            max_seq = max(max_seq, int(name[9:13]))

    next_seq = max_seq + 1
    directives[0].rev_id = f"{date_prefix}_{next_seq:04d}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
        process_revision_directives=_process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=True,
        # Commit after each migration to allow PostgreSQL enum values
        # added in one migration to be used in subsequent migrations
        transaction_per_migration=True,
        process_revision_directives=_process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
