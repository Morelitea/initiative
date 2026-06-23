"""Enforcement for the initiative-member RLS layer.

Two guarantees, mirroring how ``tenancy_test.py`` keeps the table classification
honest:

- **Currency** (no DB): the committed ``guild_rls.sql`` equals
  ``gen_guild_rls.generate()`` — so the generated policies can't drift from the
  registry. (CI also regenerates + diffs; this catches it locally and in the
  main suite.)
- **Presence** (DB): in a freshly provisioned guild schema, every
  ``INITIATIVE_SCOPED_TABLES`` table actually has ``FORCE`` RLS + all four
  ``initiative_member_*`` policies, and no ``GUILD_LEVEL_TABLES`` table does.
  So an initiative-level table cannot reach a live schema without its policies.
"""

import pytest
from sqlalchemy import text

from app.db.schema_provisioning import (
    GUILD_RLS_SQL_PATH,
    drop_guild_schema,
    guild_schema_name,
    provision_guild_schema,
)
from app.db.soft_delete_filter import SOFT_DELETE_TABLES
from app.db.tenancy import GUILD_LEVEL_TABLES, INITIATIVE_SCOPED_TABLES
from scripts.gen_guild_rls import generate

_EXPECTED_POLICIES = {
    "initiative_member_select",
    "initiative_member_insert",
    "initiative_member_update",
    "initiative_member_delete",
}

_GID_POLICIES = 990_201
_GID_PURGE = 990_202

# EVERY soft-delete table carries the RESTRICTIVE admin-only purge guard. They split
# by how RLS reaches the table: initiative-scoped ones already have RLS (for the
# membership gate); the guild-level ones (initiatives, tags) get RLS enabled SOLELY
# to host the guard, with a permissive allow-all (guild_level_open) — isolation is
# the schema boundary, initiative is the gate, so this is not a membership scope.
_PURGE_GUARD_TABLES = frozenset(SOFT_DELETE_TABLES)
_GUILD_LEVEL_PURGE = frozenset(SOFT_DELETE_TABLES) - INITIATIVE_SCOPED_TABLES


def test_guild_rls_sql_is_current():
    """The committed SQL must match the generator output exactly."""
    expected = generate()
    actual = GUILD_RLS_SQL_PATH.read_text()
    assert actual == expected, (
        "alembic/guild/guild_rls.sql is out of date with scripts/gen_guild_rls.py. "
        "Run 'python scripts/gen_guild_rls.py' in backend/ and commit the result."
    )


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
