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

Both autogenerate modes are gated, and neither carries a tolerance list: the
assertion is an empty diff. Anything the models genuinely don't own belongs in
``include_object`` (where ``alembic revision --autogenerate`` honors it too),
not in a per-diff exception here.
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlmodel import SQLModel

from app.db import base  # noqa: F401 — register every model on SQLModel.metadata
from app.db.migration_filters import make_include_object
from app.db.tenancy import GUILD_SCOPED_TABLES


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


#: ``pg_constraint.confdeltype``, as a model's ``ondelete`` spells it.
_ON_DELETE = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}


async def test_guild_keys_let_go_as_the_models_say(engine):
    """Every key between two guild tables does on delete what its model says.

    Guild mode leaves keys to the template (their names, and the references
    out of the schema it omits), so the comparison above never sees them. What
    a key does on delete is still read from the models: the trash tree skips a
    key that lets go, and a purge leaves the rest to the database."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT c.conrelid::regclass::text, a.attname,
                           c.confdeltype::text
                      FROM pg_constraint c
                      JOIN pg_attribute a
                        ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                     WHERE c.contype = 'f'
                       AND c.connamespace = 'guild_template'::regnamespace
                       AND cardinality(c.conkey) = 1
                    """
                )
            )
        ).all()
    in_template = {
        (table.removeprefix("guild_template."), column): _ON_DELETE[action]
        for table, column, action in rows
    }
    drift = [
        f"{table.name}.{column.name}: model {declared}, template {actual}"
        for table in SQLModel.metadata.tables.values()
        if table.name in GUILD_SCOPED_TABLES
        for column in table.columns
        for key in column.foreign_keys
        if key.column.table.name in GUILD_SCOPED_TABLES
        and (actual := in_template.get((table.name, column.name))) is not None
        and actual != (declared := (key.ondelete or "NO ACTION").upper())
    ]
    assert not drift, "\n".join(drift)


async def test_models_match_public_schema(engine):
    """Shared/platform models == the migrated ``public`` schema. A diff means a
    model changed without running ``alembic revision --autogenerate``.

    Public mode compares more than guild mode does: FKs, indexes and unique
    constraints are all model-declared here, so a model that leaves an
    ``ondelete`` or a composite index to its migration reads as drift."""
    async with engine.connect() as conn:
        await conn.execute(text("SET LOCAL search_path TO public"))
        diffs = await conn.run_sync(_model_diffs, False)
    assert not diffs, (
        "SQLModel models have drifted from the public schema — generate the "
        'migration with: cd backend && alembic revision --autogenerate -m "desc". '
        f"Autogenerate sees:\n{_render(diffs)}"
    )
