"""The database privilege posture, asserted as CI invariants.

The actor model (see ``history/remove-superadmin-bypassrls-design.md``) is only
as durable as the catalog state that implements it — a hotfix migration adding
a broad ``GRANT``, a manually flipped role attribute, or a new RLS table
without a decision would all land silently. These tests re-derive the posture
from the live catalog on every run, the same way ``tenancy_test`` enforces
table placement:

* the app's role families never hold SUPERUSER; ``app_admin`` is the ONLY
  BYPASSRLS holder (PostgreSQL's trusted-batch actor, grant-bounded);
* ``app_admin`` (and ``app_user``) per-table grants equal the audited registry
  in ``app.db.system_grants`` — new shared tables give the system engine (and
  the bare login role) nothing until the registry (and a migration) says so;
* every RLS-enabled shared table is FORCEd (even table owners obey policies);
* the retired ``is_superadmin`` GUC appears in no policy anywhere;
* no app role may CREATE objects in ``public`` (search_path hijack guard);
* login-role memberships in scoped roles are INHERIT FALSE (no standing
  access without an explicit ``SET ROLE``).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.system_grants import (
    SHARED_TABLE_APP_USER_GRANTS,
    SHARED_TABLE_SYSTEM_GRANTS,
)

pytestmark = [pytest.mark.integration, pytest.mark.database]

# Shared tables that carry (FORCEd) row-level security.
_RLS_SHARED_TABLES = {
    "access_grants",
    "app_settings",
    "auth_provider_secrets",
    "auth_providers",
    "auth_sessions",
    "billing_event_log",
    "federated_identities",
    "federated_identity_secrets",
    "guild_invites",
    "guild_memberships",
    "guilds",
    "oidc_claim_mappings",
    "user_view_preferences",
    "users",
}


def _app_role_family() -> list[str]:
    """The fixed app roles plus this worker's prefixed platform ladder."""
    from app.db.schema_provisioning import (
        PLATFORM_TIERS,
        billing_role_name,
        platform_role_name,
    )

    return [
        "app_user",
        "app_admin",
        "app_guild_base",
        f"{settings.PLATFORM_ROLE_PREFIX}platform_base",
        *(platform_role_name(t) for t in PLATFORM_TIERS),
        billing_role_name(),
    ]


async def test_no_app_role_is_superuser_and_only_app_admin_bypasses_rls(engine):
    roles = _app_role_family()
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = ANY(:r)"
                ),
                {"r": roles},
            )
        ).all()
    found = {r[0]: (r[1], r[2]) for r in rows}
    assert "app_user" in found and "app_admin" in found, "login roles must exist"
    for name, (is_super, bypass) in found.items():
        assert not is_super, f"{name} must never be SUPERUSER"
        if name == "app_admin":
            assert bypass, (
                "app_admin is the designated trusted-batch actor (BYPASSRLS, "
                "bounded by enumerated grants)"
            )
        else:
            assert not bypass, f"{name} must not carry BYPASSRLS"


async def _table_grants_for(engine, role: str) -> dict[str, set[str]]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT c.relname, a.privilege_type FROM pg_class c, "
                    "LATERAL aclexplode(c.relacl) a "
                    "WHERE c.relnamespace = 'public'::regnamespace "
                    "AND c.relkind = 'r' "
                    "AND a.grantee = CAST(:role AS regrole)"
                ),
                {"role": role},
            )
        ).all()
    live: dict[str, set[str]] = {}
    for table, verb in rows:
        live.setdefault(table, set()).add(verb)
    return live


def _assert_matrix(role: str, live: dict[str, set[str]], matrix) -> None:
    for table, expected in matrix.items():
        got = live.pop(table, set())
        assert got == (expected or set()), (
            f"{role} grants drifted on {table!r}: expected "
            f"{sorted(expected or set())}, catalog has {sorted(got)}"
        )
    assert live == {}, (
        f"shared tables with {role} grants but no decision in the "
        f"app/db/system_grants.py registry (add an entry there, and have the "
        f"migration's GRANT/REVOKE match it): {sorted(live)}"
    )


async def test_app_admin_grants_match_audited_matrix(engine):
    live = await _table_grants_for(engine, "app_admin")
    _assert_matrix("app_admin", live, SHARED_TABLE_SYSTEM_GRANTS)


async def test_app_user_grants_match_audited_matrix(engine):
    live = await _table_grants_for(engine, "app_user")
    _assert_matrix("app_user", live, SHARED_TABLE_APP_USER_GRANTS)


async def test_users_role_is_writable_only_by_the_system_engine(engine):
    """``users.role`` (the platform-tier ladder) is assigned only through the
    capability-gated endpoint that runs on the system engine. Each request-path
    floor holds a column-scoped UPDATE covering every ``users`` column *except*
    ``role``; ``app_admin`` keeps the full grant the endpoint relies on
    (migration 0144). A new ``users`` column must be granted to the request
    floors too, or this test fails — the same "decide it explicitly" discipline
    as the table-grant registry."""
    request_roles = [
        "app_guild_base",
        f"{settings.PLATFORM_ROLE_PREFIX}platform_base",
        "app_user",
    ]
    async with engine.connect() as conn:
        all_columns = set(
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'users'"
                    )
                )
            ).scalars()
        )
        expected = all_columns - {"role"}
        for role in request_roles:
            rows = (
                await conn.execute(
                    text(
                        "SELECT column_name, "
                        "has_column_privilege(:role, 'public.users', column_name, "
                        "'UPDATE') AS can_update "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'users'"
                    ),
                    {"role": role},
                )
            ).all()
            writable = {name for name, can_update in rows if can_update}
            assert "role" not in writable, (
                f"{role} must not hold UPDATE on users.role — role assignment is "
                "system-engine-only"
            )
            assert writable == expected, (
                f"{role} UPDATE columns on users drifted from 'every column but "
                f"role': missing {sorted(expected - writable)}, unexpected "
                f"{sorted(writable - expected)} (grant the new column, or exclude it)"
            )
        # Positive control: the system engine retains the role write its
        # sanctioned endpoint needs.
        admin_can = (
            await conn.execute(
                text(
                    "SELECT has_column_privilege('app_admin', 'public.users', "
                    "'role', 'UPDATE')"
                )
            )
        ).scalar()
        assert admin_can, "app_admin must retain UPDATE on users.role"


async def test_users_request_path_insert_is_pinned_to_member(engine):
    """A request-path insert into ``users`` may only create a plain member; the
    RESTRICTIVE policy from migration 0144 enforces it (``app_admin`` bypasses
    RLS and still seeds the bootstrap owner)."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT permissive, cmd, with_check FROM pg_policies "
                    "WHERE schemaname = 'public' AND tablename = 'users' "
                    "AND policyname = 'users_request_insert_member_only'"
                )
            )
        ).one_or_none()
    assert row is not None, "member-only insert policy on users is missing"
    permissive, cmd, with_check = row
    assert permissive == "RESTRICTIVE", "insert-member policy must be RESTRICTIVE"
    assert cmd == "INSERT"
    assert "role" in (with_check or "") and "member" in (with_check or ""), (
        f"insert-member policy check does not pin role to member: {with_check!r}"
    )


async def test_guild_membership_role_is_writable_only_by_the_system_engine(engine):
    """A guild membership's ``role`` is changed only on the system engine (the
    guild-admin endpoint). The request-path floors hold no UPDATE on
    ``guild_memberships``; ``app_guild_base`` keeps INSERT (create-user) and
    DELETE (self-leave), ``platform_base`` keeps only SELECT, and ``app_admin``
    keeps the full grant (migration 0145)."""
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    async with engine.connect() as conn:

        async def privs(role: str) -> dict[str, bool]:
            row = (
                await conn.execute(
                    text(
                        "SELECT "
                        "has_table_privilege(:r, 'public.guild_memberships', "
                        "'SELECT') AS s, "
                        "has_table_privilege(:r, 'public.guild_memberships', "
                        "'INSERT') AS i, "
                        "has_table_privilege(:r, 'public.guild_memberships', "
                        "'UPDATE') AS u, "
                        "has_table_privilege(:r, 'public.guild_memberships', "
                        "'DELETE') AS d"
                    ),
                    {"r": role},
                )
            ).one()
            return {
                "SELECT": row[0],
                "INSERT": row[1],
                "UPDATE": row[2],
                "DELETE": row[3],
            }

        guild = await privs("app_guild_base")
        assert not guild["UPDATE"], (
            "app_guild_base must not hold UPDATE on guild_memberships — a guild "
            "role change is system-engine-only"
        )
        assert guild["SELECT"] and guild["INSERT"] and guild["DELETE"], (
            "app_guild_base still needs SELECT/INSERT/DELETE (create-user, "
            f"self-leave): {guild}"
        )

        platform = await privs(base)
        assert platform == {
            "SELECT": True,
            "INSERT": False,
            "UPDATE": False,
            "DELETE": False,
        }, f"platform_base should hold only SELECT on guild_memberships: {platform}"

        admin = await privs("app_admin")
        assert admin["UPDATE"], "app_admin must retain UPDATE on guild_memberships"


async def test_guild_membership_write_policies_are_tightened(engine):
    """Self-leave DELETE is scoped to the caller's own row, and a request-path
    insert is pinned to a plain member (migration 0145)."""
    async with engine.connect() as conn:
        policies = {
            name: (permissive, cmd, qual, with_check)
            for name, permissive, cmd, qual, with_check in (
                await conn.execute(
                    text(
                        "SELECT policyname, permissive, cmd, qual, with_check "
                        "FROM pg_policies WHERE schemaname = 'public' "
                        "AND tablename = 'guild_memberships'"
                    )
                )
            ).all()
        }
    delete_policy = policies.get("guild_memberships_delete")
    assert delete_policy is not None, "guild_memberships_delete policy is missing"
    assert "current_user_id" in (delete_policy[2] or ""), (
        f"delete policy must scope to the caller's own row: {delete_policy[2]!r}"
    )
    insert_policy = policies.get("guild_memberships_request_insert_member_only")
    assert insert_policy is not None, "member-only insert policy is missing"
    assert insert_policy[0] == "RESTRICTIVE", "insert-member policy must be RESTRICTIVE"
    assert "member" in (insert_policy[3] or ""), (
        f"insert-member policy must pin role to member: {insert_policy[3]!r}"
    )


async def test_rls_shared_tables_are_forced(engine):
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                    "AND relkind = 'r'"
                )
            )
        ).all()
    rls_tables = {r[0] for r in rows if r[1]}
    assert rls_tables == _RLS_SHARED_TABLES, (
        "the set of RLS-enabled shared tables changed — decide FORCE + policies "
        f"+ update this invariant. Diff: +{sorted(rls_tables - _RLS_SHARED_TABLES)} "
        f"-{sorted(_RLS_SHARED_TABLES - rls_tables)}"
    )
    not_forced = {r[0] for r in rows if r[1] and not r[2]}
    assert not_forced == set(), (
        f"RLS tables must be FORCEd (owners obey policies too): {sorted(not_forced)}"
    )


async def test_no_policy_references_retired_superadmin_guc(engine):
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT schemaname, tablename, policyname FROM pg_policies "
                    "WHERE COALESCE(qual, '') LIKE '%is_superadmin%' "
                    "OR COALESCE(with_check, '') LIKE '%is_superadmin%'"
                )
            )
        ).all()
    assert rows == [], f"policies still reference the retired GUC: {rows}"


async def test_no_app_role_can_create_in_public(engine):
    """A role that can CREATE in ``public`` could shadow the shared,
    unqualified-name trigger functions/types via search_path — only the
    provisioning (owner) role may define objects."""
    async with engine.connect() as conn:
        for role in _app_role_family():
            can_create = (
                await conn.execute(
                    text("SELECT has_schema_privilege(:r, 'public', 'CREATE')"),
                    {"r": role},
                )
            ).scalar()
            assert not can_create, f"{role} must not CREATE in public"


async def test_login_role_memberships_in_scoped_roles_are_inherit_false(engine):
    """The login roles may only reach scoped (guild/platform) roles via an
    explicit ``SET ROLE`` — a standing (INHERIT) membership would grant every
    request ambient access to every guild."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT m.rolname AS member, r.rolname AS granted, "
                    "am.inherit_option "
                    "FROM pg_auth_members am "
                    "JOIN pg_roles m ON m.oid = am.member "
                    "JOIN pg_roles r ON r.oid = am.roleid "
                    "WHERE m.rolname IN ('app_user', 'app_admin') "
                    "AND (r.rolname LIKE '%guild\\_%' OR r.rolname LIKE '%platform\\_%' "
                    "OR r.rolname LIKE '%initiative\\_billing')"
                )
            )
        ).all()
    inheriting = [(m, g) for m, g, inh in rows if inh]
    assert inheriting == [], (
        f"login-role memberships must be INHERIT FALSE (SET ROLE only): {inheriting}"
    )


async def test_no_default_privileges_for_login_roles(engine):
    """New shared tables must grant the login roles nothing until a migration
    decides (0129/0130 revoked the blanket future-table grants). Routed access
    for new tables comes via platform_base / app_guild_base, whose defaults
    are deliberately kept."""
    async with engine.connect() as conn:
        hits = (
            await conn.execute(
                text(
                    "SELECT r.rolname, d.defaclobjtype, a.privilege_type "
                    "FROM pg_default_acl d, LATERAL aclexplode(d.defaclacl) a "
                    "JOIN pg_roles r ON r.oid = a.grantee "
                    "WHERE d.defaclnamespace = 'public'::regnamespace "
                    "AND r.rolname IN ('app_admin', 'app_user')"
                )
            )
        ).all()
    assert hits == [], (
        f"default privileges silently grant future objects to login roles: {hits}"
    )
