"""Render the per-guild DDL from its two live sources — no committed artifacts.

A guild schema has two layers, each with a single source of truth:

* **Structure** (tables, indexes, constraints, guild_id triggers) — the
  Alembic-maintained ``guild_template`` schema. :func:`render_guild_schema_ddl`
  reflects it live (columns/PK/UNIQUE via SQLAlchemy; CHECK/FK/index/trigger
  text via ``pg_get_*def`` — PG's authoritative text, preserving opclasses and
  partial-index predicates reflection loses) and emits idempotent,
  schema-relative DDL (run with ``search_path = <guild_schema>, public``).
  Cross-schema FKs (to public.users/guilds/…) are omitted — those refs stay
  soft; the schema is the tenant boundary.
* **Initiative RLS policies** — the ``INITIATIVE_PATHS`` registry.
  :func:`render_guild_rls_ddl` stamps the uniform policy boilerplate around
  each table's path.

``schema_provisioning.get_provisioning_bundle()`` renders both once per
process and derives the skip-stamp from them, so NEW guilds always match the
live template + registry by construction, and any change to either triggers
the one-time re-provisioning sweep. Guild-schema CHANGES are ordinary Alembic
migrations (``scripts/gen_guild_migration.py``).
"""

from __future__ import annotations

import re

from sqlalchemy import MetaData, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.schema import CheckConstraint, CreateTable

from app.db.initiative_rls import (
    INITIATIVE_PATHS,
    INITIATIVE_SCOPED_TABLES,
    PathBuilder,
)
from app.db.soft_delete_filter import SOFT_DELETE_TABLES
from app.db.tenancy import GUILD_SCOPED_TABLES, OWN_ROW_TABLES


# Hard delete = purge, and only a guild admin may purge (the interactive endpoint
# 403s otherwise; the background auto-purge worker runs as app_admin/BYPASSRLS, so
# RLS — including this RESTRICTIVE policy — does not apply to it). We back that with
# a DB-layer RESTRICTIVE FOR DELETE guard so a stray non-admin DELETE is refused by
# Postgres, not just by app code. The source of truth for "which tables are
# soft-deletable" is SOFT_DELETE_TABLES (derived from the SoftDeleteMixin
# subclasses). The guard goes on EVERY soft-delete table, split by how RLS is
# already set up on the table:
#   - initiative-scoped soft-delete tables already ENABLE RLS (for the membership
#     gate), so the RESTRICTIVE policy is appended to their existing block.
#   - the guild-level soft-delete tables (initiatives, tags) are RLS-free; they get
#     a dedicated guard block that ENABLEs RLS solely to host the purge guard (see
#     _guild_level_guard_block — the access policy there is a deliberate allow-all,
#     NOT a membership gate; initiative is the gate, guilds gate at the schema).
_PURGE_GUARD_TABLES: frozenset[str] = (
    frozenset(SOFT_DELETE_TABLES) & INITIATIVE_SCOPED_TABLES
)
_GUILD_LEVEL_PURGE_TABLES: frozenset[str] = (
    frozenset(SOFT_DELETE_TABLES) - INITIATIVE_SCOPED_TABLES
)

# Admit only a routed guild admin (the GUC ``set_rls_context`` writes from the
# request's validated membership role; a break-glass full-admin is routed as a
# synthetic guild admin and also sets it). Matches the guild-admin leg of
# public.initiative_access exactly.
_PURGE_GUARD_PREDICATE = (
    "current_setting('app.current_guild_role'::text, true) = 'admin'::text"
)

_HEADER = """\
-- RENDERED AT RUNTIME from app/db/initiative_rls.py (INITIATIVE_PATHS).
-- Initiative-member-level RLS for the per-guild CONTENT tables. Schema-relative
-- (run with search_path = <guild_schema>, public). Idempotent.
--
-- The access RULE lives in ONE place, public.initiative_access (initiative member
-- OR guild admin OR PAM, read from the request GUCs); each policy below is just the
-- join that resolves a table's initiative id and defers to it. The per-table paths
-- are the single source of truth in app/db/initiative_rls.py (INITIATIVE_PATHS).
--
-- SCOPE: only INITIATIVE-scoped CONTENT tables are here, exactly
-- app.db.initiative_rls.INITIATIVE_SCOPED_TABLES. The STRUCTURAL initiative tables
-- (initiatives, initiative_members, initiative_roles, initiative_role_permissions)
-- and guild-level / own-row tables (app.db.tenancy.GUILD_LEVEL_TABLES) are NOT
-- initiative-member-scoped: they are guild-scoped by the schema boundary (the
-- membership table can't be gated by the membership check it backs without
-- recursing; own-row scoping would break co-member rosters). The app layer still
-- does finer filtering (e.g. the initiatives list shows member-only for non-admins).
--
-- To add a new initiative-scoped table: add a path to INITIATIVE_PATHS in
-- app/db/initiative_rls.py — provisioning and the boot back-fill apply the
-- rendered policies automatically (the provisioning stamp includes this
-- rendering, so a registry change triggers the one-time sweep).
--
-- Soft-delete tables additionally carry a RESTRICTIVE FOR DELETE policy
-- (soft_delete_admin_purge): hard delete = purge, and only a routed guild admin
-- may. It is RESTRICTIVE, so it AND-combines with the PERMISSIVE delete policy
-- above — a write-member clears the latter but not this one. app_admin (the
-- auto-purge worker) bypasses RLS entirely. Source of truth for the table set is
-- app.db.soft_delete_filter.SOFT_DELETE_TABLES (the SoftDeleteMixin subclasses).
-- The guild-level soft-delete tables (initiatives, tags) are RLS-free, so they get
-- the guard via the dedicated section at the bottom of this file.
"""

# Header for the guild-level guard section (initiatives, tags).
_GUILD_LEVEL_SECTION = """\
-- ===========================================================================
-- Guild-level soft-delete tables: admin-only purge guard ONLY.
--
-- These tables are NOT initiative-membership-gated: initiative is the gate (its
-- content tables point AT it via initiative_access), and the initiative anchor
-- tables can't gate themselves; guilds gate at the SCHEMA level (SET ROLE), which
-- already isolates these rows. RLS is enabled here SOLELY to host the RESTRICTIVE
-- admin-only-purge guard, so the access policy (guild_level_open) is a deliberate
-- allow-all — it adds no row gate, it just lets the RESTRICTIVE delete policy bind.
-- ==========================================================================="""

# Header for the own-row section (export_jobs, …).
_OWN_ROW_SECTION = """\
-- ===========================================================================
-- Own-row guild-level tables (app.db.tenancy.OWN_ROW_TABLES): rows belong to
-- ONE user. Unlike guild_level_open, this IS a row gate — a member must not
-- see another member's rows (an export_jobs row leaks the selector and gates
-- the artifact download). Owner OR routed guild admin; the admin leg matches
-- initiative_access / the purge guard exactly, so a break-glass full-admin
-- (routed as a synthetic guild admin) is covered. A read-only PAM grantee is
-- routed to guild_<id>_ro with neither leg set: no rows, by design.
-- ==========================================================================="""

# Own-row predicate: the owner column is compared against the request GUC.
# NULLIF-guard the cast — an unset context leaves the value empty, and a bare
# ''::int raises and faults the whole query for every PERMISSIVE policy on the
# table (same rule as the public shared-table policies; see CLAUDE.md §5).
_OWN_ROW_PREDICATE = (
    "({col} = NULLIF(current_setting('app.current_user_id'::text, true), '')::int"
    " OR current_setting('app.current_guild_role'::text, true) = 'admin'::text)"
)

_COMMANDS = (
    ("select", "SELECT", "USING", False),
    ("insert", "INSERT", "WITH CHECK", True),
    ("update", "UPDATE", "USING-CHECK", True),
    ("delete", "DELETE", "USING", True),
)


def _table_block(table: str, build: PathBuilder) -> str:
    lines = [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
    ]
    for suffix, command, clause, write in _COMMANDS:
        pred = build(table, write)
        name = f"initiative_member_{suffix}"
        lines.append(f"DROP POLICY IF EXISTS {name} ON {table};")
        lines.append(f"CREATE POLICY {name} ON {table} AS PERMISSIVE FOR {command}")
        if clause == "USING-CHECK":
            lines.append(f"  USING ({pred}) WITH CHECK ({pred});")
        elif clause == "WITH CHECK":
            lines.append(f"  WITH CHECK ({pred});")
        else:  # USING
            lines.append(f"  USING ({pred});")
    if table in _PURGE_GUARD_TABLES:
        # Admin-only hard delete (purge), AND-combined with the PERMISSIVE delete
        # policy above. RESTRICTIVE, so a write-member who clears the permissive
        # leg is still refused unless they are the routed guild admin.
        lines.append("DROP POLICY IF EXISTS soft_delete_admin_purge ON " + table + ";")
        lines.append(
            f"CREATE POLICY soft_delete_admin_purge ON {table} AS RESTRICTIVE FOR DELETE"
        )
        lines.append(f"  USING ({_PURGE_GUARD_PREDICATE});")
    return "\n".join(lines)


def _own_row_block(table: str, owner_col: str) -> str:
    """RLS for an own-row guild-level table: per-command policies admitting the
    row's owner or the routed guild admin. INSERT/UPDATE WITH CHECK use the same
    predicate, so a member can't author rows owned by someone else either."""
    pred = _OWN_ROW_PREDICATE.format(col=owner_col)
    lines = [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
    ]
    for suffix, command, clause, _write in _COMMANDS:
        name = f"own_row_{suffix}"
        lines.append(f"DROP POLICY IF EXISTS {name} ON {table};")
        lines.append(f"CREATE POLICY {name} ON {table} AS PERMISSIVE FOR {command}")
        if clause == "USING-CHECK":
            lines.append(f"  USING ({pred}) WITH CHECK ({pred});")
        elif clause == "WITH CHECK":
            lines.append(f"  WITH CHECK ({pred});")
        else:  # USING
            lines.append(f"  USING ({pred});")
    return "\n".join(lines)


def _guild_level_guard_block(table: str) -> str:
    """RLS for a guild-level soft-delete table (initiatives, tags): a permissive
    allow-all (isolation is the schema boundary, not RLS) plus the RESTRICTIVE
    admin-only-purge guard. NOT an access gate — see _GUILD_LEVEL_SECTION."""
    return "\n".join(
        [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            f"DROP POLICY IF EXISTS guild_level_open ON {table};",
            f"CREATE POLICY guild_level_open ON {table} AS PERMISSIVE FOR ALL",
            "  USING (true) WITH CHECK (true);",
            f"DROP POLICY IF EXISTS soft_delete_admin_purge ON {table};",
            f"CREATE POLICY soft_delete_admin_purge ON {table} AS RESTRICTIVE FOR DELETE",
            f"  USING ({_PURGE_GUARD_PREDICATE});",
        ]
    )


def render_guild_rls_ddl() -> str:
    blocks = [_table_block(t, INITIATIVE_PATHS[t]) for t in sorted(INITIATIVE_PATHS)]
    out = _HEADER + "\n\n" + "\n\n".join(blocks)
    guards = [_guild_level_guard_block(t) for t in sorted(_GUILD_LEVEL_PURGE_TABLES)]
    if guards:
        out += "\n\n" + _GUILD_LEVEL_SECTION + "\n\n" + "\n\n".join(guards)
    own_rows = [_own_row_block(t, c) for t, c in sorted(OWN_ROW_TABLES.items())]
    if own_rows:
        out += "\n\n" + _OWN_ROW_SECTION + "\n\n" + "\n\n".join(own_rows)
    return out + "\n"


# ============================================================================
# Structure rendering (reflected live from guild_template)
# ============================================================================

_DIALECT = postgresql.dialect()

# The schema the artifact is reflected from: Alembic-maintained guild_template.
_SRC_SCHEMA = "guild_template"

# CHECK + FK constraint definitions straight from Postgres (authoritative text).
# The session search_path is set to "<src>, public" before these run, so
# pg_get_constraintdef / pg_get_indexdef / pg_get_triggerdef emit visible names
# UNQUALIFIED — the artifact stays schema-relative.
_CONSTRAINT_SQL = text(
    f"""
    SELECT cl.relname AS tbl, con.conname, con.contype::text AS contype,
           pg_get_constraintdef(con.oid) AS condef,
           tgt.relname AS tgt
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_namespace ns ON ns.oid = cl.relnamespace AND ns.nspname = '{_SRC_SCHEMA}'
    LEFT JOIN pg_class tgt ON tgt.oid = con.confrelid
    WHERE con.contype IN ('c', 'f') AND cl.relname = ANY(:t)
    ORDER BY con.contype, cl.relname, con.conname
    """
)


def _build_tables(sync_conn) -> list[str]:
    md = MetaData()
    md.reflect(
        bind=sync_conn, schema=_SRC_SCHEMA, only=lambda n, _m: n in GUILD_SCOPED_TABLES
    )
    rel = MetaData()
    out: list[str] = []
    for name in sorted(GUILD_SCOPED_TABLES):
        t = md.tables[f"{_SRC_SCHEMA}.{name}"].to_metadata(rel, schema=None)
        # CHECK + FK come from pg_get_constraintdef below; drop them here so the
        # CREATE TABLE only carries columns + PRIMARY KEY + UNIQUE.
        for con in list(t.constraints):
            if isinstance(con, CheckConstraint):
                t.constraints.discard(con)
        for col in t.columns:
            if hasattr(col.type, "create_type"):
                col.type.create_type = False  # ty: ignore[invalid-assignment]
        out.append(
            str(
                CreateTable(
                    t, if_not_exists=True, include_foreign_key_constraints=[]
                ).compile(dialect=_DIALECT)
            ).strip()
            + ";"
        )
    return out


# Non-constraint indexes from Postgres itself (pg_get_indexdef preserves opclasses
# like jsonb_path_ops, partial-index WHERE, etc. that SQLAlchemy reflection drops).
# The only interpolation below is the _SRC_SCHEMA string literal — no user input
# reaches this module's rendered SQL (scanner: hardcoded_sql_expressions is the
# point; this file IS the DDL renderer).
_INDEX_SQL = text(  # noqa: S608
    f"""
    SELECT tc.relname AS tbl, pg_get_indexdef(i.indexrelid) AS indexdef
    FROM pg_index i
    JOIN pg_class ic ON ic.oid = i.indexrelid
    JOIN pg_class tc ON tc.oid = i.indrelid
    JOIN pg_namespace n ON n.oid = tc.relnamespace AND n.nspname = '{_SRC_SCHEMA}'
    WHERE tc.relname = ANY(:t)
      AND NOT EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid = i.indexrelid)
    ORDER BY tc.relname, ic.relname
    """
)


def _schema_relative_index(indexdef: str) -> str:
    # CREATE [UNIQUE] INDEX name ON <src>.tbl USING ...  ->  schema-relative + idempotent
    indexdef = re.sub(
        r"^CREATE (UNIQUE )?INDEX ", r"CREATE \1INDEX IF NOT EXISTS ", indexdef
    )
    indexdef = indexdef.replace(f" ON {_SRC_SCHEMA}.", " ON ")
    return indexdef + ";"


# The guild_id denormalization triggers. The trigger FUNCTIONS are shared (in
# public, no pinned search_path) and read the parent table unqualified, so under
# search_path=<guild_schema>,public they populate guild_id from the guild's own
# rows. They must live in each guild schema or NOT NULL guild_id inserts fail.
_TRIGGER_SQL = text(  # noqa: S608 — interpolates only the _SRC_SCHEMA literal
    f"""
    SELECT cl.relname AS tbl, pg_get_triggerdef(tg.oid) AS triggerdef
    FROM pg_trigger tg
    JOIN pg_class cl ON cl.oid = tg.tgrelid
    JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = '{_SRC_SCHEMA}'
    WHERE NOT tg.tgisinternal AND cl.relname = ANY(:t)
    ORDER BY cl.relname, tg.tgname
    """
)


def _schema_relative_trigger(triggerdef: str) -> str:
    # CREATE TRIGGER name ... ON <src>.tbl ... EXECUTE FUNCTION fn()  ->
    # schema-relative + idempotent (CREATE OR REPLACE; the function stays shared).
    triggerdef = triggerdef.replace("CREATE TRIGGER ", "CREATE OR REPLACE TRIGGER ")
    triggerdef = triggerdef.replace(f" ON {_SRC_SCHEMA}.", " ON ")
    return triggerdef + ";"


def _guard(conname: str, body: str) -> str:
    # Idempotent ADD CONSTRAINT: skip if a constraint of this name already exists
    # in the current schema (search_path puts the guild schema first).
    return (
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        f"WHERE conname = '{conname}' AND connamespace = current_schema()::regnamespace) "
        f"THEN {body}; END IF; END $$;"
    )


async def render_guild_schema_ddl(engine: AsyncEngine) -> str:
    """Reflect the live ``guild_template`` and return the schema-relative,
    idempotent structure DDL for provisioning a guild schema."""
    async with engine.connect() as conn:
        # Visible-name resolution: with the template first on the search_path,
        # pg_get_*def emit its tables unqualified (and shared public objects
        # qualified only when shadowed) — keeping the DDL schema-relative.
        await conn.execute(text(f'SET search_path TO "{_SRC_SCHEMA}", public'))
        table_stmts = await conn.run_sync(_build_tables)
        index_rows = (
            await conn.execute(_INDEX_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})
        ).fetchall()
        rows = (
            await conn.execute(_CONSTRAINT_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})
        ).fetchall()
        trigger_rows = (
            await conn.execute(_TRIGGER_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})
        ).fetchall()

    indexes = [_schema_relative_index(r.indexdef) for r in index_rows]
    triggers = [_schema_relative_trigger(r.triggerdef) for r in trigger_rows]
    checks, fks = [], []
    for r in rows:
        if r.contype == "c":
            checks.append(
                _guard(
                    r.conname,
                    f'ALTER TABLE "{r.tbl}" ADD CONSTRAINT "{r.conname}" {r.condef}',
                )
            )
        elif r.contype == "f" and r.tgt in GUILD_SCOPED_TABLES:  # intra-schema only
            fks.append(
                _guard(
                    r.conname,
                    f'ALTER TABLE "{r.tbl}" ADD CONSTRAINT "{r.conname}" {r.condef}',
                )
            )

    header = (
        "-- RENDERED AT RUNTIME from the live guild_template schema. Schema-relative:\n"
        "-- run with search_path = <guild_schema>, public. Idempotent.\n\n"
    )
    return (
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
