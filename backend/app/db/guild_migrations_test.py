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
_GID_C = 990_203
_GID_D = 990_204
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


async def test_apply_to_all_guild_schemas_includes_public_by_default(engine):
    """The default include_public=True also changes the legacy public copy — the
    path every guild-scoped migration takes until public's copies are retired."""
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_C)
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: apply_to_all_guild_schemas(
                    c, f"ALTER TABLE tags ADD COLUMN IF NOT EXISTS {_COLUMN} boolean"
                )  # include_public defaults to True
            )
        async with engine.connect() as conn:
            assert await _tags_has_column(conn, "public")  # the default path hit public
            assert await _tags_has_column(conn, guild_schema_name(_GID_C))
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: apply_to_all_guild_schemas(
                    c, f"ALTER TABLE tags DROP COLUMN IF EXISTS {_COLUMN}"
                )  # remove from public + every guild schema
            )
            await drop_guild_schema(conn, _GID_C)


async def test_apply_to_all_guild_schemas_failure_propagates_and_reverts(engine):
    """A failing DDL must surface its OWN error (not a masking cleanup error) and
    leave no stale search_path on the connection after rollback."""
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_D)

        async with engine.connect() as conn:
            trans = await conn.begin()
            with pytest.raises(Exception) as exc_info:
                await conn.run_sync(
                    lambda c: apply_to_all_guild_schemas(
                        c, "ALTER TABLE tags ADD COLUMN _boom bogus_type_xyz", include_public=False
                    )
                )
            # The original DDL error, not a 'current transaction is aborted' mask.
            assert "current transaction is aborted" not in str(exc_info.value).lower()
            await trans.rollback()
            # is_local search_path reverts on rollback — no stale guild schema.
            search_path = (await conn.exec_driver_sql("SHOW search_path")).scalar()
            assert "guild_" not in search_path
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_D)
