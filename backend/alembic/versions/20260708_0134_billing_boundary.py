"""billing integration: tier label, event log, jti blocklist, billing role

Adds what the /billing endpoints need:

* ``guilds.tier_name`` — display label of the paid tier (NULL = none), plus
  non-negativity CHECKs on the billing-writable caps (NULL stays legal —
  it means unlimited);
* ``billing_event_log`` — idempotency claim (UNIQUE event id) and
  append-only record of billing writes; no FK so rows outlive the guild;
* ``billing_jti_blocklist`` — one-shot service-JWT jti redemption (the
  ``auto_delegation_jti_blocklist`` pattern);
* the NOLOGIN ``initiative_billing`` role the endpoints assume via
  ``SET ROLE`` (INHERIT FALSE), with column-scoped grants and RLS policies
  keyed on the per-request ``app.billing_guild_id`` GUC.

The public schema default-grants platform_base + app_guild_base full DML on
every new table, so both new tables REVOKE those; the login roles get
nothing (see app/db/system_grants.py). Unused unless both
BILLING_PUBLIC_KEY_PEM and BILLING_HMAC_SECRET are configured.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from app.core.config import settings

revision = "20260708_0134"
down_revision = "20260706_0133"
branch_labels = None
depends_on = None


def _billing_role() -> str:
    # Cluster-global role; carries the same prefix as the platform ladder so
    # test workers don't collide with a co-located dev DB's role.
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


# Always NULLIF-guard the cast: an unset GUC yields '' and a bare ''::int
# would fault every PERMISSIVE policy on the table.
_BILLING_GUILD_ID = "NULLIF(current_setting('app.billing_guild_id', true), '')::int"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    role = _billing_role()

    # --- Display-only tier label (NULL = no paid tier) ------------------------
    op.add_column("guilds", sa.Column("tier_name", sa.String(64), nullable=True))
    op.create_check_constraint(
        "ck_guilds_max_storage_bytes_nonnegative",
        "guilds",
        "max_storage_bytes IS NULL OR max_storage_bytes >= 0",
    )
    op.create_check_constraint(
        "ck_guilds_max_users_nonnegative",
        "guilds",
        "max_users IS NULL OR max_users >= 0",
    )

    # --- billing_event_log: idempotency claim + append-only audit ------------
    op.create_table(
        "billing_event_log",
        sa.Column("event_id", sa.String(128), primary_key=True),
        # No FK: rows outlive the guild they describe.
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("op", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(128), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_billing_event_log_guild_id", "billing_event_log", ["guild_id"])

    # --- billing_jti_blocklist: one-shot service-JWT redemption --------------
    op.create_table(
        "billing_jti_blocklist",
        sa.Column("jti", sa.String(64), primary_key=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    # --- The billing role: NOLOGIN, SET ROLE-only, column-scoped -------------
    op.execute(
        text(
            f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE "{role}" NOLOGIN;
                END IF;
            END $$;
            """
        )
    )
    _run(
        [
            # Not a member of platform_base/app_guild_base — no inherited
            # floor; USAGE only, grants explicit.
            f'GRANT USAGE ON SCHEMA public TO "{role}"',
            f"""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
                    GRANT "{role}" TO app_user WITH INHERIT FALSE;
                END IF;
            END $$;
            """,
            f"GRANT SELECT (id, tier_name, max_storage_bytes, max_users, status), "
            f"UPDATE (tier_name, max_storage_bytes, max_users, status, "
            f'status_changed_at, updated_at) ON public.guilds TO "{role}"',
            f'GRANT SELECT (guild_id) ON public.guild_memberships TO "{role}"',
            # Append-only: INSERT is the only verb on the event log.
            f'GRANT INSERT ON public.billing_event_log TO "{role}"',
            f'GRANT INSERT ON public.billing_jti_blocklist TO "{role}"',
        ]
    )

    # --- RLS: scope billing statements to the per-request guild GUC ----------
    # guild_select's membership-EXISTS leg is evaluated with the querying
    # role's privileges, so scope it to the roles that use it (previously
    # TO PUBLIC): the bare login role, the guild-role floor, and the
    # platform-ladder floor (tiers inherit it).
    op.execute(
        f"ALTER POLICY guild_select ON public.guilds "
        f'TO app_user, app_guild_base, "{_platform_base()}"'
    )
    _run(
        [
            f"CREATE POLICY billing_guild_select ON public.guilds FOR SELECT "
            f'TO "{role}" USING (id = {_BILLING_GUILD_ID})',
            f"CREATE POLICY billing_guild_update ON public.guilds FOR UPDATE "
            f'TO "{role}" USING (id = {_BILLING_GUILD_ID}) '
            f"WITH CHECK (id = {_BILLING_GUILD_ID})",
            f"CREATE POLICY billing_membership_select ON public.guild_memberships "
            f'FOR SELECT TO "{role}" USING (guild_id = {_BILLING_GUILD_ID})',
            "ALTER TABLE public.billing_event_log ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.billing_event_log FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY billing_event_insert ON public.billing_event_log "
            f'FOR INSERT TO "{role}" WITH CHECK (guild_id = {_BILLING_GUILD_ID})',
        ]
    )

    # --- Strip the schema-default DML from the routed floors -----------------
    base = _platform_base()
    _run(
        [
            f'REVOKE ALL ON TABLE public.billing_event_log FROM app_guild_base, "{base}"',
            f'REVOKE ALL ON TABLE public.billing_jti_blocklist FROM app_guild_base, "{base}"',
            # System-engine decisions (see app/db/system_grants.py): auditors
            # read the evidence via the ops surface; a janitor may prune
            # expired jtis. Neither may mutate the event log.
            "GRANT SELECT ON TABLE public.billing_event_log TO app_admin",
            "GRANT SELECT, DELETE ON TABLE public.billing_jti_blocklist TO app_admin",
        ]
    )


def downgrade() -> None:
    role = _billing_role()
    _run(
        [
            "ALTER POLICY guild_select ON public.guilds TO PUBLIC",
            "DROP POLICY IF EXISTS billing_guild_select ON public.guilds",
            "DROP POLICY IF EXISTS billing_guild_update ON public.guilds",
            "DROP POLICY IF EXISTS billing_membership_select ON public.guild_memberships",
            f'REVOKE ALL ON public.guilds FROM "{role}"',
            f'REVOKE ALL ON public.guild_memberships FROM "{role}"',
        ]
    )
    op.execute("DROP TABLE IF EXISTS public.billing_event_log CASCADE")
    op.execute("DROP TABLE IF EXISTS public.billing_jti_blocklist CASCADE")
    op.drop_constraint("ck_guilds_max_users_nonnegative", "guilds")
    op.drop_constraint("ck_guilds_max_storage_bytes_nonnegative", "guilds")
    op.drop_column("guilds", "tier_name")
    op.execute(
        text(
            f"""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    REVOKE USAGE ON SCHEMA public FROM "{role}";
                    BEGIN
                        DROP ROLE "{role}";
                    EXCEPTION WHEN dependent_objects_still_exist THEN
                        -- Role is referenced from another database on the same
                        -- cluster; leaving it is harmless (it holds nothing here).
                        NULL;
                    END;
                END IF;
            END $$;
            """
        )
    )
