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
from app.db.tenancy import GUILD_SCOPED_TABLES  # noqa: E402

config = context.config

if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name)

# Only set URL for CLI invocations. When called programmatically via
# run_migrations(), _get_alembic_config() already sets the URL and marks
# url_configured=True so we don't override it here.
if not config.attributes.get("url_configured"):
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = SQLModel.metadata

# `alembic -x guild revision --autogenerate` (alembic's -x argument channel,
# driven by scripts/gen_guild_migration.py) flips autogenerate into guild
# mode: the comparison reflects the Alembic-maintained guild_template schema
# instead of public, the include filter inverts to guild-content tables ONLY,
# and script.py.mako (branching on config.attributes, the same pattern as
# alembic's bundled multidb template) wraps the generated ops in the
# per-guild-schema loop. Normal runs are unaffected.
GUILD_AUTOGEN = "guild" in context.get_x_argument(as_dictionary=True)
config.attributes["guild_autogen"] = GUILD_AUTOGEN


def _include_object(obj, name, type_, reflected, compare_to):
    """Keep each autogenerate mode on its own tables — and, in guild mode, on
    its own OBJECT KINDS.

    Default mode compares shared/public tables only: guild-content tables live
    in the per-guild schemas, so without the filter autogenerate would try to
    CREATE them in ``public`` on a fresh database (the model metadata still
    declares them for the ORM) or DROP/ALTER the frozen legacy copies on a
    pre-squash database.

    Guild mode (``-x guild``) inverts the table filter (guild-content tables
    only, compared against ``guild_template``) and additionally scopes WHAT
    autogenerate manages, mirroring the established division of labor:

    * models own **tables + columns** — that's what guild autogen diffs;
    * the artifacts own the dressing — FKs keep their PG-authored names and
      deliberately omit cross-schema references, partial/GIN indexes carry
      opclasses reflection loses (preserving them is WHY provisioning
      reflects pg catalogs — see app.db.guild_ddl), and CHECKs come from
      pg_get_constraintdef — so
      constraint/index objects that exist only on one side are not diffs to
      emit. Metadata-declared indexes/uniques missing from the template are
      still created (a real model change); reflected-only ones are never
      dropped.
    * ``guild_id`` columns are trigger-populated and DDL-owned (NOT NULL in
      the schema, Optional in models) — their nullability is not a diff.
    """
    if type_ == "table":
        return (name in GUILD_SCOPED_TABLES) == GUILD_AUTOGEN

    table = getattr(obj, "table", None)  # indexes/constraints/columns
    in_guild_tables = table is not None and table.name in GUILD_SCOPED_TABLES
    if not GUILD_AUTOGEN:
        return not in_guild_tables
    if table is not None and not in_guild_tables:
        return False

    if type_ == "foreign_key_constraint":
        return False  # wholly artifact-owned (names + cross-schema omissions)
    if type_ in ("index", "unique_constraint", "check_constraint"):
        return not reflected or compare_to is not None  # never drop artifact-owned
    if type_ == "column" and name == "guild_id":
        return False  # trigger-populated; DDL owns its NOT NULL
    return True


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
        if (
            len(name) >= 13
            and name[8] == "_"
            and name[:8].isdigit()
            and name[9:13].isdigit()
        ):
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
        include_object=_include_object,
        process_revision_directives=_process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    if GUILD_AUTOGEN:
        # Reflect guild_template as the "current" state: it is first on the
        # search_path, so it becomes the default schema autogenerate compares
        # the (schema-less) model metadata against. public stays on the path
        # so shared enum types resolve as schema-less on both sides.
        connection.exec_driver_sql("SET search_path TO guild_template, public")
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=True,
        # Commit after each migration to allow PostgreSQL enum values
        # added in one migration to be used in subsequent migrations
        transaction_per_migration=True,
        include_object=_include_object,
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
