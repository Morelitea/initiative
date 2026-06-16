"""One-time data conversion: move existing guilds' rows from the legacy
``public.<guild-scoped>`` tables into their per-guild ``guild_<id>`` schemas.

Runs automatically at app startup (``main.on_startup``, after migrations) so a
packaged Docker deploy converts itself with no extra step. Idempotent and
resumable: each guild is converted atomically and skipped on later boots, so a
converted deployment's boot is a handful of cheap marker checks.

Design:
  * Runs on the provisioning (superuser) engine, so a transaction-local
    ``session_replication_role = replica`` turns off FK checks + the guild_id
    triggers for the copy — rows go in **any order** with their **original ids**
    preserved (ids are globally unique today, so intra-schema FKs stay intact).
  * 36 of the 49 guild-scoped tables carry ``guild_id`` (partition
    ``WHERE guild_id = X``); the other 13 are junctions/children partitioned by a
    parent that does (see ``_CHAIN_PREDICATES``). A guard asserts those 13 still
    match the schema, so a newly-added guild_id-less table fails loudly here
    rather than silently skipping its rows.
  * Columns are named explicitly (not ``SELECT *``) so a column-order difference
    can't silently misassign data — a mismatch fails loudly instead.
    ``ON CONFLICT DO NOTHING`` keeps it idempotent; a guild already living in its
    schema (created post-cutover) has no public rows, so it's a no-op. Sequences
    are reset to ``max(id)`` so new inserts don't collide. Each converted schema
    is stamped with a marker comment in the same transaction, so the skip check
    can't be fooled by a guild with unusual data.
  * The ``public`` copies are KEPT (a backup + the source for
    ``gen_guild_schema.py``/the drift-guard). A later phase introduces
    ``guild_template``, drops the public copies, and re-points that tooling.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import session as db_session
from app.db.schema_provisioning import guild_schema_name, provision_guild
from app.db.tenancy import GUILD_SCOPED_TABLES

logger = logging.getLogger(__name__)

# A guild schema carries this comment once its conversion has fully committed —
# a definitive, atomic marker, so a guild with unusual data (e.g. no initiatives)
# can't be mistaken for "already converted" by a row-count heuristic.
_CONVERSION_MARKER = "schema-per-guild-converted"

# The 13 guild-scoped tables without a guild_id column: partition via a parent
# (chained up to a guild_id-bearing ancestor). ``{gid}`` is an int, injected safely.
_CHAIN_PREDICATES: dict[str, str] = {
    "initiative_roles": "initiative_id IN (SELECT id FROM public.initiatives WHERE guild_id = {gid})",
    "initiative_role_permissions": (
        "initiative_role_id IN (SELECT id FROM public.initiative_roles "
        "WHERE initiative_id IN (SELECT id FROM public.initiatives WHERE guild_id = {gid}))"
    ),
    "property_definitions": "initiative_id IN (SELECT id FROM public.initiatives WHERE guild_id = {gid})",
    "project_tags": "project_id IN (SELECT id FROM public.projects WHERE guild_id = {gid})",
    "task_tags": "task_id IN (SELECT id FROM public.tasks WHERE guild_id = {gid})",
    "task_property_values": "task_id IN (SELECT id FROM public.tasks WHERE guild_id = {gid})",
    "document_tags": "document_id IN (SELECT id FROM public.documents WHERE guild_id = {gid})",
    "document_property_values": "document_id IN (SELECT id FROM public.documents WHERE guild_id = {gid})",
    "calendar_event_tags": "calendar_event_id IN (SELECT id FROM public.calendar_events WHERE guild_id = {gid})",
    "calendar_event_property_values": "event_id IN (SELECT id FROM public.calendar_events WHERE guild_id = {gid})",
    "event_reminder_dispatches": "event_id IN (SELECT id FROM public.calendar_events WHERE guild_id = {gid})",
    "queue_item_tags": "queue_item_id IN (SELECT id FROM public.queue_items WHERE guild_id = {gid})",
    "task_assignment_digest_items": "task_id IN (SELECT id FROM public.tasks WHERE guild_id = {gid})",
}


async def _assert_predicates_cover_schema(conn: AsyncConnection) -> None:
    """Fail loudly if the set of guild_id-less guild-scoped tables no longer
    matches ``_CHAIN_PREDICATES`` (e.g. a new junction table was added) — better
    than silently leaving its rows behind."""
    rows = await conn.execute(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema='public' AND column_name='guild_id' AND table_name = ANY(:t)"
        ),
        {"t": list(GUILD_SCOPED_TABLES)},
    )
    has_guild_id = {r[0] for r in rows}
    without = set(GUILD_SCOPED_TABLES) - has_guild_id
    if without != set(_CHAIN_PREDICATES):
        missing = without - set(_CHAIN_PREDICATES)
        stale = set(_CHAIN_PREDICATES) - without
        raise RuntimeError(
            "guild_conversion partition predicates are out of date — "
            f"missing predicate for {sorted(missing)}, stale predicate for {sorted(stale)}"
        )


async def _public_columns(conn: AsyncConnection) -> dict[str, list[str]]:
    """Column lists (in order) for each guild-scoped public table, so the copy can
    name columns explicitly instead of ``SELECT *`` — robust to any column-order
    difference, and a loud failure (not a silent misassignment) on a mismatch."""
    rows = await conn.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ANY(:t) "
            "ORDER BY table_name, ordinal_position"
        ),
        {"t": list(GUILD_SCOPED_TABLES)},
    )
    columns: dict[str, list[str]] = {}
    for table, column in rows.all():
        columns.setdefault(table, []).append(column)
    return columns


async def _needs_conversion(conn: AsyncConnection, schema: str) -> bool:
    """True unless the schema exists and carries the conversion marker comment.
    A new (post-cutover) guild with no public rows runs once as a harmless no-op
    and then gets the marker."""
    marker = await conn.scalar(
        text("SELECT obj_description(n.oid) FROM pg_namespace n WHERE n.nspname = :s"),
        {"s": schema},
    )
    return marker != _CONVERSION_MARKER


async def _copy_guild(
    conn: AsyncConnection, gid: int, schema: str, columns: dict[str, list[str]]
) -> None:
    """Copy one guild's public rows into its schema. The caller provides the
    (atomic) transaction via ``engine.begin()``."""
    # Transaction-local: FK checks + guild_id triggers off for the bulk copy,
    # auto-reverted at commit/rollback (superuser-only; provisioning is super).
    await conn.execute(
        text("SELECT set_config('session_replication_role', 'replica', true)")
    )
    for table in sorted(GUILD_SCOPED_TABLES):
        # Name columns explicitly (not SELECT *) so a column-order difference can't
        # silently misassign data; a missing column fails loudly instead.
        cols = ", ".join(f'"{c}"' for c in columns[table])
        predicate = _CHAIN_PREDICATES.get(table, "guild_id = {gid}").format(gid=gid)
        await conn.execute(
            text(
                f'INSERT INTO "{schema}"."{table}" ({cols}) '
                f'SELECT {cols} FROM public."{table}" WHERE {predicate} '
                "ON CONFLICT DO NOTHING"
            )
        )
    # Reset every sequence in the schema to its owning column's max, so new
    # inserts don't collide with the copied (preserved) ids.
    seqs = await conn.execute(
        text(
            "SELECT s.relname seq, t.relname tbl, a.attname col "
            "FROM pg_class s "
            "JOIN pg_depend d ON d.objid = s.oid AND d.deptype = 'a' "
            "JOIN pg_class t ON t.oid = d.refobjid "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid "
            "JOIN pg_namespace n ON n.oid = s.relnamespace AND n.nspname = :s "
            "WHERE s.relkind = 'S'"
        ),
        {"s": schema},
    )
    for seq, tbl, col in seqs.all():
        await conn.execute(
            text(
                f'SELECT setval(\'"{schema}"."{seq}"\', '
                f'GREATEST((SELECT COALESCE(max("{col}"), 0) FROM "{schema}"."{tbl}"), 1))'
            )
        )
    # Mark the guild converted in the same transaction (constant literal, safe).
    await conn.execute(
        text(f"COMMENT ON SCHEMA \"{schema}\" IS '{_CONVERSION_MARKER}'")
    )


async def convert_public_to_guild_schemas() -> int:
    """Move every existing guild's public rows into its per-guild schema.

    Idempotent + resumable. Returns the number of guilds converted this run (0 on
    an already-converted or fresh deployment). Keeps the public copies as a backup.
    """
    engine = db_session.provisioning_engine  # superuser
    # One read connection decides what's left to do, so an already-converted
    # deployment's boot is just a sweep of cheap marker checks.
    async with engine.connect() as conn:
        await _assert_predicates_cover_schema(conn)
        columns = await _public_columns(conn)
        guild_ids = (
            (await conn.execute(text("SELECT id FROM public.guilds ORDER BY id")))
            .scalars()
            .all()
        )
        to_convert = [
            gid
            for gid in guild_ids
            if await _needs_conversion(conn, guild_schema_name(gid))
        ]

    for gid in to_convert:
        schema = guild_schema_name(gid)
        await provision_guild(
            gid
        )  # idempotent: ensure schema + roles exist (own transaction)
        async with engine.begin() as conn:  # atomic per guild
            await _copy_guild(conn, gid, schema, columns)
        logger.info(
            "schema-per-guild conversion: migrated guild %s into %s", gid, schema
        )
    if to_convert:
        logger.info(
            "schema-per-guild conversion: migrated %d guild(s)", len(to_convert)
        )
    return len(to_convert)
