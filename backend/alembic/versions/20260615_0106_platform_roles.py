"""Platform-role ladder (Phase 1): five NOLOGIN platform_<tier> roles + a
shared platform_base floor, assumed per request on the public/platform path.

Symmetric to the per-guild roles already shipped (``guild_<id>`` + ``app_guild_base``,
migration 0100): the guild half routes guild requests via ``SET ROLE guild_<id>``;
this adds the platform half so an authenticated *no-guild* request runs as
``platform_<users.role>`` instead of the broad login role ``app_user`` — role-scoped
and fail-closed at the database.

What this migration does (Phase 1 — foundation only):
  * Create ``platform_base`` and ``platform_member … platform_owner`` as NOLOGIN
    roles. **None carries BYPASSRLS** — the platform ladder never holds a standing
    all-guild bypass (least privilege; cross-guild reach is a separate, time-bound
    PAM grant, added in a later phase).
  * ``platform_base`` carries the SAME broad ``public`` working grants ``app_user``
    holds today. Phase 1 deliberately leaves RLS unchanged, so a ``platform_member``
    request behaves exactly like today's ``app_user`` request (existing row-level
    policies still scope every read/write). Per-tier *least-privilege* tightening
    (``TO platform_<tier>`` policies, owner-only config grants) is Phase 2.
  * Each ``platform_<tier>`` is granted ``platform_base`` (INHERIT), so assuming a
    tier yields the floor's privileges.
  * The login roles ``app_user``/``app_admin`` are granted every tier
    ``WITH INHERIT FALSE`` — they can ``SET ROLE`` into a tier but hold none of its
    privileges standing (identical fail-closed discipline to the guild roles).

What this migration does NOT do (intentionally deferred — see
``history/platform-postgres-roles-design.md`` §5 / §11 and the implementation audit):
  * It does NOT narrow ``app_user``. The doc's Phase-1 "narrow app_user to
    pre-routing reads" is unsafe as written: ``app_user`` still serves the entire
    *unauthenticated/bootstrap* surface (register, login, password reset, OIDC,
    public ``/config``, push registration) and *service-layer/background* calls
    (notifications, stats, oidc_sync, cross_guild) that legitimately read AND write
    with no platform tier to assume. Narrowing it safely requires a full enumeration
    of that surface plus role-aware tests (the default suite connects as superuser
    and would not catch an over-narrowing) — that is its own reviewed step.

Roles are cluster-global, so the names carry ``settings.PLATFORM_ROLE_PREFIX``
(empty in prod/dev; ``test_`` under the suite) — read at apply time so a co-located
test DB and dev DB never collide on the catalog. The routing role-name helper
(``app.db.schema_provisioning.platform_role_name``) reads the same setting, so a
``SET ROLE`` always targets the role this migration actually created.

Revision ID: 20260615_0106
Revises: 20260615_0105
Create Date: 2026-06-15
"""

from alembic import op

from app.core.config import settings
from app.db.schema_provisioning import PLATFORM_TIERS

revision = "20260615_0106"
down_revision = "20260615_0105"
branch_labels = None
depends_on = None


def _role_names() -> tuple[str, list[str]]:
    """(`platform_base`, [`platform_<tier>` …]) under the active prefix.

    Read the prefix at call time, not import time: the suite sets it on
    ``settings`` before running migrations, so a deferred read targets the
    prefixed (``test_``) roles in the test DB and the unprefixed roles in prod.
    """
    prefix = settings.PLATFORM_ROLE_PREFIX
    base = f"{prefix}platform_base"
    tiers = [f"{prefix}platform_{tier}" for tier in PLATFORM_TIERS]
    return base, tiers


def upgrade() -> None:
    base, tier_roles = _role_names()
    all_roles = [base, *tier_roles]

    # 1. Create roles, idempotently. NOLOGIN (assumed only via SET ROLE) and never
    #    BYPASSRLS — the platform ladder holds no standing all-guild bypass.
    for role in all_roles:
        op.execute(
            f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE "{role}" NOLOGIN;
                END IF;
            END $$;
            """
        )

    # 2. platform_base: the shared public working floor. Mirrors app_user's grants
    #    (baseline) and app_guild_base (migration 0100) so a routed platform request
    #    can do exactly what an app_user request does today; existing RLS still
    #    scopes the rows. Default privileges cover tables added by later migrations.
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{base}"')
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{base}"'
    )
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{base}"')
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{base}"'
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f'GRANT USAGE, SELECT ON SEQUENCES TO "{base}"'
    )
    # EXECUTE on the RLS helper (mirrors app_user). Guarded: the function may not
    # exist on a partially-built DB, and EXECUTE was revoked from PUBLIC.
    op.execute(
        f"""
        DO $$ BEGIN
            GRANT EXECUTE ON FUNCTION is_initiative_member(integer, integer) TO "{base}";
        EXCEPTION WHEN undefined_function THEN null;
        END $$;
        """
    )

    # 3. Each tier inherits the base floor (default INHERIT on the tier role, so
    #    `SET ROLE platform_<tier>` yields platform_base's privileges).
    for role in tier_roles:
        op.execute(f'GRANT "{base}" TO "{role}"')

    # 4. The login roles may ASSUME any tier but hold none standing. WITH INHERIT
    #    FALSE so a (mis)configured INHERIT login role still can't wield a tier
    #    without an explicit SET ROLE — fail-closed, like the guild roles.
    tier_list = ", ".join(f'"{r}"' for r in tier_roles)
    for login_role in ("app_user", "app_admin"):
        op.execute(
            f"""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{login_role}') THEN
                    GRANT {tier_list} TO "{login_role}" WITH INHERIT FALSE;
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    base, tier_roles = _role_names()

    # Revoke the ladder membership from the login roles, then drop the tier roles
    # (their only privileges are membership in base + the WITH INHERIT FALSE grant
    # to the login roles; DROP ROLE clears the pg_auth_members rows).
    tier_list = ", ".join(f'"{r}"' for r in tier_roles)
    for login_role in ("app_user", "app_admin"):
        op.execute(
            f"""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{login_role}') THEN
                    REVOKE {tier_list} FROM "{login_role}";
                END IF;
            END $$;
            """
        )
    for role in tier_roles:
        op.execute(f'DROP ROLE IF EXISTS "{role}"')

    # Reverse platform_base's grants (mirror migration 0100's downgrade), then drop.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{base}"'
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f'REVOKE USAGE, SELECT ON SEQUENCES FROM "{base}"'
    )
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{base}') THEN
                DROP OWNED BY "{base}";
                DROP ROLE "{base}";
            END IF;
        END $$;
        """
    )
