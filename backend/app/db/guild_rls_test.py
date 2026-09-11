"""Enforcement for the initiative-member RLS layer.

Two guarantees, mirroring how ``tenancy_test.py`` keeps the table classification
honest:

- **Presence** (DB): in a freshly provisioned guild schema, every
  ``INITIATIVE_SCOPED_TABLES`` table actually has ``FORCE`` RLS + all four
  ``initiative_member_*`` policies, and no ``GUILD_LEVEL_TABLES`` table does.
  So an initiative-level table cannot reach a live schema without its policies.
- **Agreement** (pure): the governing tool the app layer reads out of the
  registry is the one the rendered policy actually asks about. The endpoints
  resolving a sub-resource's parent and the policy gating that sub-resource's
  rows come from one declaration, and this is what keeps them there.
"""

import pytest
from sqlalchemy import text

from app.db.schema_provisioning import (
    drop_guild_schema,
    guild_schema_name,
    provision_guild_schema,
)
from app.db.soft_delete_filter import SOFT_DELETE_TABLES
from app.db.tenancy import (
    GUILD_LEVEL_TABLES,
    INITIATIVE_SCOPED_TABLES,
    OWN_ROW_TABLES,
)

_EXPECTED_POLICIES = {
    "initiative_member_select",
    "initiative_member_insert",
    "initiative_member_update",
    "initiative_member_delete",
}

_OWN_ROW_POLICIES = {
    "own_row_select",
    "own_row_insert",
    "own_row_update",
    "own_row_delete",
}

_GID_POLICIES = 990_201
_GID_PURGE = 990_202
_GID_OWN_ROW = 990_203

# EVERY soft-delete table carries the RESTRICTIVE admin-only purge guard. They split
# by how RLS reaches the table: initiative-scoped ones already have RLS (for the
# membership gate); the guild-level ones (initiatives, tags) get RLS enabled SOLELY
# to host the guard, with a permissive allow-all (guild_level_open) — isolation is
# the schema boundary, initiative is the gate, so this is not a membership scope.
_PURGE_GUARD_TABLES = frozenset(SOFT_DELETE_TABLES)
_GUILD_LEVEL_PURGE = frozenset(SOFT_DELETE_TABLES) - INITIATIVE_SCOPED_TABLES


@pytest.mark.database
async def test_initiative_access_is_the_only_access_function(engine):
    """One source of truth: the legacy ``is_initiative_member`` access rule must
    be gone (dropped in migration 0111), and ``initiative_access`` must exist."""
    async with engine.connect() as conn:
        legacy = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_proc WHERE proname = 'is_initiative_member'"
                )
            )
        ).scalar()
        current = (
            await conn.execute(
                text("SELECT count(*) FROM pg_proc WHERE proname = 'initiative_access'")
            )
        ).scalar()
    assert legacy == 0, (
        "public.is_initiative_member still exists — initiative_access is meant to "
        "be the single initiative access rule (see migration 0111)."
    )
    assert current >= 1, "public.initiative_access is missing."


@pytest.mark.database
async def test_every_initiative_scoped_table_has_policies(engine):
    """Provision a real guild schema and verify the policy invariant per table."""
    schema = guild_schema_name(_GID_POLICIES)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_POLICIES)
        async with engine.connect() as conn:
            pol_rows = await conn.execute(
                text(
                    "SELECT tablename, policyname FROM pg_policies "
                    "WHERE schemaname = :s"
                ),
                {"s": schema},
            )
            policies: dict[str, set[str]] = {}
            for tbl, pol in pol_rows:
                policies.setdefault(tbl, set()).add(pol)

            rls_rows = await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :s AND c.relkind = 'r'"
                ),
                {"s": schema},
            )
            rls = {row[0]: (row[1], row[2]) for row in rls_rows}

        # Every initiative-scoped table: FORCE RLS + the four policies.
        for tbl in sorted(INITIATIVE_SCOPED_TABLES):
            enabled, forced = rls.get(tbl, (False, False))
            assert enabled and forced, (
                f"{tbl} is initiative-scoped but RLS is not ENABLED+FORCED "
                f"(enabled={enabled}, forced={forced}) — regenerate guild_rls.sql."
            )
            missing = _EXPECTED_POLICIES - policies.get(tbl, set())
            assert not missing, (
                f"{tbl} is initiative-scoped but missing policies {sorted(missing)} "
                "— add a path in scripts/gen_guild_rls.py and regenerate."
            )

        # No guild-level table should carry the initiative-member policies.
        for tbl in sorted(GUILD_LEVEL_TABLES):
            leaked = _EXPECTED_POLICIES & policies.get(tbl, set())
            assert not leaked, (
                f"{tbl} is GUILD_LEVEL (exempt) but has initiative_member policies "
                f"{sorted(leaked)} — it should not. Reclassify or remove the path."
            )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_POLICIES)


@pytest.mark.database
async def test_own_row_tables_have_policies(engine):
    """Every ``OWN_ROW_TABLES`` table gets FORCE RLS + the four ``own_row_*``
    policies in a freshly provisioned schema — the row gate that keeps one
    member's rows (e.g. an export job's selector + artifact download) hidden
    from other members — and no ``initiative_member_*`` policies (own-row
    tables are guild-level, not membership-gated)."""
    schema = guild_schema_name(_GID_OWN_ROW)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_OWN_ROW)
        async with engine.connect() as conn:
            pol_rows = await conn.execute(
                text(
                    "SELECT tablename, policyname FROM pg_policies "
                    "WHERE schemaname = :s"
                ),
                {"s": schema},
            )
            policies: dict[str, set[str]] = {}
            for tbl, pol in pol_rows:
                policies.setdefault(tbl, set()).add(pol)

            rls_rows = await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :s AND c.relkind = 'r'"
                ),
                {"s": schema},
            )
            rls = {row[0]: (row[1], row[2]) for row in rls_rows}

        for tbl in sorted(OWN_ROW_TABLES):
            enabled, forced = rls.get(tbl, (False, False))
            assert enabled and forced, (
                f"{tbl} is own-row but RLS is not ENABLED+FORCED "
                f"(enabled={enabled}, forced={forced})."
            )
            missing = _OWN_ROW_POLICIES - policies.get(tbl, set())
            assert not missing, (
                f"{tbl} is in OWN_ROW_TABLES but missing policies "
                f"{sorted(missing)} — check guild_ddl._own_row_block."
            )
            leaked = _EXPECTED_POLICIES & policies.get(tbl, set())
            assert not leaked, (
                f"{tbl} is own-row (guild-level) but carries initiative_member "
                f"policies {sorted(leaked)} — it must not be membership-gated."
            )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_OWN_ROW)


@pytest.mark.database
async def test_soft_delete_tables_have_admin_only_purge_policy(engine):
    """Hard delete is admin-only at the DB layer: EVERY soft-delete table carries a
    RESTRICTIVE FOR DELETE ``soft_delete_admin_purge`` policy in a freshly
    provisioned schema, so a non-admin DELETE is refused by Postgres even if app
    code were bypassed. The guild-level soft-delete tables (initiatives, tags) have
    RLS enabled solely to host that guard, with a permissive allow-all
    (``guild_level_open``) — not a membership gate (initiative is the gate; guilds
    gate at the schema)."""
    schema = guild_schema_name(_GID_PURGE)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_PURGE)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename, policyname, permissive, cmd FROM pg_policies "
                    "WHERE schemaname = :s "
                    "AND policyname IN ('soft_delete_admin_purge', 'guild_level_open')"
                ),
                {"s": schema},
            )
            by_table: dict[str, dict[str, tuple[str, str]]] = {}
            for tbl, pol, perm, cmd in rows:
                by_table.setdefault(tbl, {})[pol] = (perm, cmd)

            rls_rows = await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :s AND c.relkind = 'r'"
                ),
                {"s": schema},
            )
            rls = {row[0]: (row[1], row[2]) for row in rls_rows}

        # Every soft-delete table: the RESTRICTIVE admin-purge guard.
        for tbl in sorted(_PURGE_GUARD_TABLES):
            guard = by_table.get(tbl, {}).get("soft_delete_admin_purge")
            assert guard is not None, (
                f"{tbl} is a soft-delete table but has no soft_delete_admin_purge "
                "policy — regenerate guild_rls.sql (scripts/gen_guild_rls.py)."
            )
            assert guard == ("RESTRICTIVE", "DELETE"), (
                f"{tbl}.soft_delete_admin_purge must be RESTRICTIVE FOR DELETE, "
                f"got {guard[0]} FOR {guard[1]}."
            )

        # Guild-level soft-delete tables: RLS enabled + permissive allow-all so the
        # guard can bind, but NO initiative-member policies (not a membership gate).
        for tbl in sorted(_GUILD_LEVEL_PURGE):
            enabled, forced = rls.get(tbl, (False, False))
            assert enabled and forced, (
                f"{tbl} must have RLS ENABLED+FORCED to host the purge guard "
                f"(enabled={enabled}, forced={forced})."
            )
            assert "guild_level_open" in by_table.get(tbl, {}), (
                f"{tbl} has RLS enabled but no permissive guild_level_open policy "
                "— provisioning would deny all access to it."
            )
            leaked = _EXPECTED_POLICIES & set(by_table.get(tbl, {}))
            assert not leaked, (
                f"{tbl} is guild-level but carries initiative_member policies "
                f"{sorted(leaked)} — it must not be membership-gated."
            )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_PURGE)


# ---------------------------------------------------------------------------
# Agreement: one declaration, read two ways
# ---------------------------------------------------------------------------


#: Tables the app layer deliberately derives NO single governing tool for, and
#: why. Stated rather than tolerated: a new sub-resource that the app cannot
#: resolve a parent for has to be added here on purpose, which is the moment to
#: notice it needs one.
_NO_SINGLE_PARENT = {
    # Polymorphic — the governing tool is a property of the row, and the policy
    # is a CASE over the column naming it.
    "comments": "one of eight tools, per row",
    "reactions": "one of eight tools, per row",
    "reaction_digest_items": "gated exactly like the reaction it describes",
    "recent_views": "one of eight tools, per row",
    "search_entries": "names its tool in dac_tool",
    # One tool, two parents: a link must clear the gate on BOTH documents, so
    # there is no single row to authorize against.
    # Two parents of any kind: an edge clears the gate on each end through
    # relationship_endpoint_access, which asks each end's own entry here.
    "relationships": "source and target must both clear it, whatever they are",
    # No sharing leg at all — see the registry for each.
    "event_outbox": "the change log is no tool's own table",
    "property_definitions": "initiative configuration, not a tool's content",
    "resource_grants": "sharing itself; resource_access reads this table",
    "webhook_subscriptions": "integration config, gated by the initiative",
}


def test_the_app_reads_the_same_governing_tool_the_policy_asks_about():
    """``governing_path`` must name the tool the rendered sharing leg calls.

    The app layer asks this registry which tool governs a sub-resource — a
    task's project, an event's calendar — and the DDL renderer asks the same
    entry to build the policy. A table where those two answered differently
    would be one where an endpoint authorized against one resource while the
    database gated on another.
    """
    import re

    from app.db.initiative_rls import INITIATIVE_PATHS, governing_path

    mismatches = []
    for table, path in sorted(INITIATIVE_PATHS.items()):
        derived = governing_path(table)
        leg = path.dac.predicate(table, "SELECT", False) if path.dac else None
        asked = set(re.findall(r"resource_access\('([a-z_]+)'", leg or ""))
        if derived is None:
            if table not in _NO_SINGLE_PARENT:
                mismatches.append(
                    f"{table}: policy asks {sorted(asked) or 'nothing'}, app derives "
                    "nothing and the table is not in _NO_SINGLE_PARENT"
                )
            continue
        if asked != {derived[0].value}:
            mismatches.append(
                f"{table}: policy asks {sorted(asked)}, app derives {derived[0].value}"
            )
    assert mismatches == [], mismatches


def test_no_single_parent_names_only_real_tables():
    """The exemption list cannot outlive the tables it names."""
    from app.db.initiative_rls import INITIATIVE_PATHS

    stale = sorted(set(_NO_SINGLE_PARENT) - set(INITIATIVE_PATHS))
    assert stale == [], stale


def test_every_declared_hop_walks_a_real_column_to_a_real_table():
    """``via`` is walked to load a parent, so every step of it has to exist.

    Each hop names a column on the table reached so far and the table that
    column points at, and the walk has to arrive at the governing tool's own
    table. Checking only the first hop would let a renamed intermediate — the
    ``tasks`` in ``task_tags -> tasks -> projects`` — reach CI green and fail
    at the moment something followed it.

    A table absent from the mapped metadata fails rather than skips: it means
    the registry names something the models do not, which is the drift this
    is here to catch.
    """
    import app.db.base  # noqa: F401 — imported for its side effect
    from sqlmodel import SQLModel

    from app.db.initiative_rls import INITIATIVE_PATHS, governing_path

    # app.db.base registers every model, so the metadata is complete whether
    # this runs alone or in a suite. Without it an unimported model looks like
    # registry drift.
    mapped = SQLModel.metadata.tables
    problems: list[str] = []

    for table, _path in sorted(INITIATIVE_PATHS.items()):
        derived = governing_path(table)
        if derived is None:
            continue
        tool, hops = derived

        current = table
        if current not in mapped:
            problems.append(f"{current}: registered but not a mapped table")
            continue

        for column, target in hops:
            if column not in mapped[current].columns:
                problems.append(f"{current}.{column}: no such column")
                break
            if target not in mapped:
                problems.append(f"{current}.{column} -> {target}: no such mapped table")
                break
            current = target
        else:
            # The walk has to end AT the governing resource, not merely near
            # it — that is what makes the tool and the chain one declaration.
            if current != tool.plural:
                problems.append(
                    f"{table}: chain ends at {current}, governed by {tool.value} "
                    f"(expected {tool.plural})"
                )

    assert problems == [], problems
