"""Drift gate: SQLModel models must match the migrated database schemas.

The frozen baseline seeds are write-once and every schema change flows through
a migration, so the one seam that CAN drift is models ↔ the Alembic-maintained
schemas: a model change merged without ``scripts/gen_guild_migration.py`` (guild
content) or ``alembic revision --autogenerate`` (shared/public) leaves the ORM
disagreeing with every deployed database. A missing column fails loudly at
runtime, but index / type / constraint drift is silent.

This test runs Alembic's own comparison (``compare_metadata``) against the
migrated test database through the exact ``include_object`` filter
``alembic/env.py`` uses (shared via ``app.db.migration_filters``) and requires
an empty diff — the database twin of the ``check-generated-types`` CI gate: if
you changed a model, you must have generated the migration.

Scope: guild mode only. The ``public`` schema carries known benign drift that
predates this gate (index names left behind by the admin_api_keys →
user_api_keys rename, FK ``ondelete`` behaviors that exist only in migrations,
``ix_access_grants_user_guild`` undeclared in models) — a public-mode gate
needs that cleanup migration first, tracked separately rather than baselined
here as a tolerance list.
"""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlmodel import SQLModel

from app.db import base  # noqa: F401 — register every model on SQLModel.metadata
from app.db.migration_filters import make_include_object


def _model_diffs(sync_conn, guild_autogen: bool) -> list:
    ctx = MigrationContext.configure(
        sync_conn,
        opts={
            "compare_type": True,
            "include_object": make_include_object(guild_autogen),
        },
    )
    return compare_metadata(ctx, SQLModel.metadata)


def _render(diffs: list) -> str:
    return "\n".join(f"  {diff}" for diff in diffs)


@pytest.mark.database
async def test_models_match_guild_template(engine):
    """Guild-content models == the migrated ``guild_template`` (the schema every
    guild is provisioned from). A diff means a model changed without running
    ``python scripts/gen_guild_migration.py "desc"``."""
    async with engine.connect() as conn:
        # Mirror env.py's guild mode: guild_template first on the search_path
        # becomes the default schema the (schema-less) metadata compares
        # against. SET LOCAL, so it dies with this transaction instead of
        # riding the pooled connection into another test.
        await conn.execute(text("SET LOCAL search_path TO guild_template, public"))
        diffs = await conn.run_sync(_model_diffs, True)
    assert not diffs, (
        "SQLModel models have drifted from guild_template — generate the guild "
        "migration with: cd backend && python scripts/gen_guild_migration.py "
        f'"desc". Autogenerate sees:\n{_render(diffs)}'
    )
