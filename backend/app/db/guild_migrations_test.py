"""Tests for the guild-scoped migration helper (the forward migration pattern).

Synthetic, high guild ids so the temporary ``guild_<id>`` schemas can't collide
with real data; dropped in teardown. Runs against the test DB as the owning role
(the ``engine`` fixture), which has DDL privileges.
"""

import pytest
from sqlalchemy import text

from app.db.guild_migrations import apply_to_all_guild_schemas, guild_schema_names
from app.db.schema_provisioning import (
    drop_guild_schema,
    guild_schema_name,
    provision_guild_schema,
)

pytestmark = pytest.mark.database

_GID_A = 990_201
_GID_B = 990_202
_COLUMN = "_mig_helper_test"


async def _tags_has_column(conn, schema: str) -> bool:
    return bool(
        await conn.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = 'tags' AND column_name = :c)"
            ),
            {"s": schema, "c": _COLUMN},
        )
    )


async def test_apply_to_all_guild_schemas_hits_every_guild(engine):
    """A guild-scoped DDL change applied via the helper lands in every provisioned
    guild schema — the core of the forward migration pattern (a normal migration
    would only touch one schema)."""
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_A)
            await provision_guild_schema(conn, _GID_B)

        # The provisioned schemas are enumerated.
        async with engine.connect() as conn:
            names = await conn.run_sync(guild_schema_names)
        assert guild_schema_name(_GID_A) in names
        assert guild_schema_name(_GID_B) in names

        # Apply an idempotent, schema-relative ALTER to every guild schema.
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: apply_to_all_guild_schemas(
                    c, f"ALTER TABLE tags ADD COLUMN IF NOT EXISTS {_COLUMN} boolean",
                    include_public=False,
                )
            )

        async with engine.connect() as conn:
            assert await _tags_has_column(conn, guild_schema_name(_GID_A))
            assert await _tags_has_column(conn, guild_schema_name(_GID_B))
            # public was excluded (include_public=False).
            assert not await _tags_has_column(conn, "public")

        # The reverse (a downgrade) removes it everywhere.
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: apply_to_all_guild_schemas(
                    c, f"ALTER TABLE tags DROP COLUMN IF EXISTS {_COLUMN}",
                    include_public=False,
                )
            )
        async with engine.connect() as conn:
            assert not await _tags_has_column(conn, guild_schema_name(_GID_A))
            assert not await _tags_has_column(conn, guild_schema_name(_GID_B))
    finally:
        # Best-effort: ensure no other guild schema keeps the throwaway column.
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: apply_to_all_guild_schemas(
                    c, f"ALTER TABLE tags DROP COLUMN IF EXISTS {_COLUMN}",
                    include_public=False,
                )
            )
            await drop_guild_schema(conn, _GID_A)
            await drop_guild_schema(conn, _GID_B)
