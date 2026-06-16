"""Generate alembic/guild/guild_schema.sql — the single, schema-relative source
for a guild schema's structure.

It reflects the public tables Alembic built and emits idempotent, schema-relative
DDL (run with ``search_path = <guild_schema>, public``):
  - columns, PRIMARY KEY, UNIQUE and indexes come from SQLAlchemy reflection;
  - CHECK and FOREIGN KEY constraints come from ``pg_get_constraintdef`` (PG's own
    authoritative text — SQLAlchemy mis-emits some reflected CHECK expressions);
  - cross-schema FKs (to public.guilds/users/...) are omitted, so those refs stay
    soft (the schema is the tenant boundary).

This is a build tool, not runtime: run it after a guild-scoped schema migration to
refresh the artifact. The model is never used to build the DB.

Usage:  python scripts/gen_guild_schema.py [database_name]   (default: initiative_test)
"""

import asyncio
import sys

import re

from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CheckConstraint, CreateTable
from sqlalchemy import text

from app.core.config import settings
from app.db.tenancy import GUILD_SCOPED_TABLES

_DIALECT = postgresql.dialect()
_OUT = "alembic/guild/guild_schema.sql"

# CHECK + FK constraint definitions straight from Postgres (authoritative text).
_CONSTRAINT_SQL = text(
    """
    SELECT cl.relname AS tbl, con.conname, con.contype::text AS contype,
           pg_get_constraintdef(con.oid) AS condef,
           tgt.relname AS tgt
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_namespace ns ON ns.oid = cl.relnamespace AND ns.nspname = 'public'
    LEFT JOIN pg_class tgt ON tgt.oid = con.confrelid
    WHERE con.contype IN ('c', 'f') AND cl.relname = ANY(:t)
    ORDER BY con.contype, cl.relname, con.conname
    """
)


def _build_tables(sync_conn) -> list[str]:
    md = MetaData()
    md.reflect(bind=sync_conn, schema="public", only=lambda n, _m: n in GUILD_SCOPED_TABLES)
    rel = MetaData()
    out: list[str] = []
    for name in sorted(GUILD_SCOPED_TABLES):
        t = md.tables[f"public.{name}"].to_metadata(rel, schema=None)
        # CHECK + FK come from pg_get_constraintdef below; drop them here so the
        # CREATE TABLE only carries columns + PRIMARY KEY + UNIQUE.
        for con in list(t.constraints):
            if isinstance(con, CheckConstraint):
                t.constraints.discard(con)
        for col in t.columns:
            if hasattr(col.type, "create_type"):
                col.type.create_type = False
        out.append(
            str(CreateTable(t, if_not_exists=True, include_foreign_key_constraints=[]).compile(dialect=_DIALECT)).strip()
            + ";"
        )
    return out


# Non-constraint indexes from Postgres itself (pg_get_indexdef preserves opclasses
# like jsonb_path_ops, partial-index WHERE, etc. that SQLAlchemy reflection drops).
_INDEX_SQL = text(
    """
    SELECT tc.relname AS tbl, pg_get_indexdef(i.indexrelid) AS indexdef
    FROM pg_index i
    JOIN pg_class ic ON ic.oid = i.indexrelid
    JOIN pg_class tc ON tc.oid = i.indrelid
    JOIN pg_namespace n ON n.oid = tc.relnamespace AND n.nspname = 'public'
    WHERE tc.relname = ANY(:t)
      AND NOT EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid = i.indexrelid)
    ORDER BY tc.relname, ic.relname
    """
)


def _schema_relative_index(indexdef: str) -> str:
    # CREATE [UNIQUE] INDEX name ON public.tbl USING ...  ->  schema-relative + idempotent
    indexdef = re.sub(r"^CREATE (UNIQUE )?INDEX ", r"CREATE \1INDEX IF NOT EXISTS ", indexdef)
    indexdef = indexdef.replace(" ON public.", " ON ")
    return indexdef + ";"


# The guild_id denormalization triggers. The trigger FUNCTIONS are shared (in
# public, no pinned search_path) and read the parent table unqualified, so under
# search_path=<guild_schema>,public they populate guild_id from the guild's own
# rows. They must live in each guild schema or NOT NULL guild_id inserts fail.
_TRIGGER_SQL = text(
    """
    SELECT cl.relname AS tbl, pg_get_triggerdef(tg.oid) AS triggerdef
    FROM pg_trigger tg
    JOIN pg_class cl ON cl.oid = tg.tgrelid
    JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = 'public'
    WHERE NOT tg.tgisinternal AND cl.relname = ANY(:t)
    ORDER BY cl.relname, tg.tgname
    """
)


def _schema_relative_trigger(triggerdef: str) -> str:
    # CREATE TRIGGER name ... ON public.tbl ... EXECUTE FUNCTION fn()  ->
    # schema-relative + idempotent (CREATE OR REPLACE; the function stays shared).
    triggerdef = triggerdef.replace("CREATE TRIGGER ", "CREATE OR REPLACE TRIGGER ")
    triggerdef = triggerdef.replace(" ON public.", " ON ")
    return triggerdef + ";"


def _guard(conname: str, body: str) -> str:
    # Idempotent ADD CONSTRAINT: skip if a constraint of this name already exists
    # in the current schema (search_path puts the guild schema first).
    return (
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        f"WHERE conname = '{conname}' AND connamespace = current_schema()::regnamespace) "
        f"THEN {body}; END IF; END $$;"
    )


async def main() -> None:
    db = sys.argv[1] if len(sys.argv) > 1 else "initiative_test"
    url = settings.DATABASE_URL.rsplit("/", 1)[0] + f"/{db}"
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        table_stmts = await conn.run_sync(_build_tables)
        index_rows = (await conn.execute(_INDEX_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})).fetchall()
        rows = (await conn.execute(_CONSTRAINT_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})).fetchall()
        trigger_rows = (await conn.execute(_TRIGGER_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})).fetchall()
    await engine.dispose()

    indexes = [_schema_relative_index(r.indexdef) for r in index_rows]
    triggers = [_schema_relative_trigger(r.triggerdef) for r in trigger_rows]
    checks, fks = [], []
    for r in rows:
        if r.contype == "c":
            checks.append(_guard(r.conname, f'ALTER TABLE "{r.tbl}" ADD CONSTRAINT "{r.conname}" {r.condef}'))
        elif r.contype == "f" and r.tgt in GUILD_SCOPED_TABLES:  # intra-schema only
            fks.append(_guard(r.conname, f'ALTER TABLE "{r.tbl}" ADD CONSTRAINT "{r.conname}" {r.condef}'))

    header = (
        "-- AUTOGENERATED by scripts/gen_guild_schema.py from the public schema Alembic\n"
        "-- builds. This is THE source for a guild schema's structure. Schema-relative:\n"
        "-- run with search_path = <guild_schema>, public. Idempotent. Do not hand-edit;\n"
        "-- regenerate after any guild-scoped schema migration.\n\n"
    )
    sql = (
        header
        + "\n".join(table_stmts)
        + "\n\n-- indexes\n"
        + "\n".join(indexes)
        + "\n\n-- CHECK constraints\n"
        + "\n".join(checks)
        + "\n\n-- intra-schema FOREIGN KEYs\n"
        + "\n".join(fks)
        + "\n\n-- guild_id denormalization triggers (functions are shared in public)\n"
        + "\n".join(triggers)
        + "\n"
    )
    with open(_OUT, "w") as fh:
        fh.write(sql)
    print(
        f"wrote {_OUT}: {len(table_stmts)} table + {len(indexes)} index + "
        f"{len(checks)} check + {len(fks)} FK + {len(triggers)} trigger stmts"
    )


if __name__ == "__main__":
    asyncio.run(main())
