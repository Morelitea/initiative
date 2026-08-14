"""Move the operator-set fields off public.guilds into guild_administration.

``public.guilds`` carries two unrelated things under one name: a guild's
**identity** (id / name / description / icon — shown on an invite preview before
sign-in and rendered in every member's sidebar, so not private) and the
**operator-set** fields a deployment or a billing service sets. Keeping them on
one row made "who may read a guild" and "who may read its limits" the same
question, answerable only by whichever serializer remembered to omit the right
fields.

This splits them. ``guild_administration`` holds ``max_storage_bytes`` /
``max_users`` / ``tier_name`` / ``guild_auth_enabled``, one row per guild, and
**no request-path role may write it** — neither by grant nor by policy. The
operator endpoints run on the system engine; the verified billing path keeps a
column-scoped grant of its own. A guild's own admins read it (their settings
page shows usage against the caps) and can write none of it.

``guilds.status`` deliberately stays put: every guild request reads it off a row
the request already loads, so moving it would buy a join on the hottest path in
the app. ``status_changed_at`` stays with it so the pair is written together.

The public schema default-grants ``app_user`` / ``app_guild_base`` /
``platform_base`` full DML on every new table, so the new table REVOKEs that
before granting read. The dropped columns' own ACLs and CHECK constraints go
with the columns; the CHECKs are recreated on the new table.

Revision ID: 20260814_0178
Revises: 20260814_0177
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from app.core.config import settings

revision = "20260814_0178"
down_revision = "20260814_0177"
branch_labels = None
depends_on = None


#: Columns that move off ``guilds``, in the order they are copied.
_MOVED = ("max_storage_bytes", "max_users", "tier_name", "guild_auth_enabled")


def _billing_role() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


# Always NULLIF-guard the cast: an unset GUC yields '' and a bare ''::int would
# fault every PERMISSIVE policy on the table.
_GUILD_ID = "(NULLIF(current_setting('app.current_guild_id', true), ''))::integer"
_USER_ID = "(NULLIF(current_setting('app.current_user_id', true), ''))::integer"
_PAM_GUILD_ID = "(NULLIF(current_setting('app.pam_guild_id', true), ''))::integer"
_PAM_READ = "current_setting('app.pam_read', true) = 'true'"
_BILLING_GUILD_ID = "NULLIF(current_setting('app.billing_guild_id', true), '')::int"

# Mirrors ``guild_select`` on public.guilds: the guild currently routed into, or
# any guild the caller belongs to (the guild list reads caps across a member's
# own guilds, with no single guild routed).
_MEMBER = (
    "EXISTS (SELECT 1 FROM public.guild_memberships "
    "WHERE guild_memberships.guild_id = guild_administration.guild_id "
    f"AND guild_memberships.user_id = {_USER_ID})"
)


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def _copy_between_tables(sql: str, *, expect_from: str, into: str) -> None:
    """Run a copy that reads ``public.guilds`` and assert it moved every row.

    ``public.guilds`` has FORCE ROW LEVEL SECURITY and is owned by the role that
    runs migrations, so the owner is policy-bound like everyone else and a plain
    ``SELECT`` here returns **zero** rows — the copy would succeed while
    inserting nothing. Lift FORCE for the duration of the copy and restore it in
    the same transaction, then verify the row counts match before continuing.
    """
    conn = op.get_bind()
    op.execute("ALTER TABLE public.guilds NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(sql)
        expected = conn.execute(
            text(f"SELECT count(*) FROM {expect_from}")
        ).scalar_one()
        copied = conn.execute(text(f"SELECT count(*) FROM {into}")).scalar_one()
    finally:
        op.execute("ALTER TABLE public.guilds FORCE ROW LEVEL SECURITY")
    if copied != expected:
        raise RuntimeError(
            f"guild_administration backfill copied {copied} of {expected} rows; "
            "aborting so the migration is not applied with data missing"
        )


def upgrade() -> None:
    role = _billing_role()
    base = _platform_base()

    op.create_table(
        "guild_administration",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "guild_id",
            sa.Integer(),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("max_storage_bytes", sa.BigInteger(), nullable=True),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("tier_name", sa.String(64), nullable=True),
        sa.Column(
            "guild_auth_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    # One row per guild, and the lookup key for every read.
    op.create_index(
        "ix_guild_administration_guild_id",
        "guild_administration",
        ["guild_id"],
        unique=True,
    )
    # The originals ride the columns dropped below, so they are recreated here.
    op.create_check_constraint(
        "ck_guild_administration_max_storage_bytes_nonnegative",
        "guild_administration",
        "max_storage_bytes IS NULL OR max_storage_bytes >= 0",
    )
    op.create_check_constraint(
        "ck_guild_administration_max_users_nonnegative",
        "guild_administration",
        "max_users IS NULL OR max_users >= 0",
    )

    _copy_between_tables(
        f"""
        INSERT INTO public.guild_administration
            (guild_id, {", ".join(_MOVED)})
        SELECT id, {", ".join(_MOVED)} FROM public.guilds
        """,
        expect_from="public.guilds",
        into="public.guild_administration",
    )

    for column in _MOVED:
        op.drop_column("guilds", column)

    _run(
        [
            # Strip the schema-default DML before granting anything back.
            "REVOKE ALL ON TABLE public.guild_administration "
            f'FROM app_user, app_guild_base, "{base}"',
            # Read-only on the request path: a guild admin's settings page shows
            # usage against the caps, and the guild list reports them.
            "GRANT SELECT ON TABLE public.guild_administration "
            f'TO app_user, app_guild_base, "{base}"',
            # The operator endpoints and provisioning run on the system engine.
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
            "public.guild_administration TO app_admin",
            "GRANT ALL ON SEQUENCE public.guild_administration_id_seq TO app_admin",
            # The verified billing path writes the caps and the plan label, and
            # nothing else on this table (guild_auth_enabled is not billing's).
            "GRANT SELECT (guild_id, max_storage_bytes, max_users, tier_name) "
            f'ON TABLE public.guild_administration TO "{role}"',
            "GRANT UPDATE (max_storage_bytes, max_users, tier_name) "
            f'ON TABLE public.guild_administration TO "{role}"',
            "ALTER TABLE public.guild_administration ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.guild_administration FORCE ROW LEVEL SECURITY",
            "CREATE POLICY guild_administration_select ON public.guild_administration "
            f'FOR SELECT TO app_user, app_guild_base, "{base}" '
            f"USING (guild_id = {_GUILD_ID} OR {_MEMBER})",
            # PAM/break-glass grantees read the guild they hold a live grant on.
            "CREATE POLICY guild_administration_pam_read ON "
            "public.guild_administration FOR SELECT "
            f"USING (guild_id = {_PAM_GUILD_ID} AND {_PAM_READ})",
            "CREATE POLICY billing_guild_administration_select ON "
            f'public.guild_administration FOR SELECT TO "{role}" '
            f"USING (guild_id = {_BILLING_GUILD_ID})",
            "CREATE POLICY billing_guild_administration_update ON "
            f'public.guild_administration FOR UPDATE TO "{role}" '
            f"USING (guild_id = {_BILLING_GUILD_ID}) "
            f"WITH CHECK (guild_id = {_BILLING_GUILD_ID})",
        ]
    )


def downgrade() -> None:
    role = _billing_role()

    op.add_column(
        "guilds", sa.Column("max_storage_bytes", sa.BigInteger(), nullable=True)
    )
    op.add_column("guilds", sa.Column("max_users", sa.Integer(), nullable=True))
    op.add_column("guilds", sa.Column("tier_name", sa.String(64), nullable=True))
    op.add_column(
        "guilds",
        sa.Column(
            "guild_auth_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
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

    # Same FORCE-RLS caveat in reverse: the UPDATE ... FROM would match no rows.
    _copy_between_tables(
        """
        UPDATE public.guilds g SET
            max_storage_bytes = a.max_storage_bytes,
            max_users = a.max_users,
            tier_name = a.tier_name,
            guild_auth_enabled = a.guild_auth_enabled
        FROM public.guild_administration a WHERE a.guild_id = g.id
        """,
        expect_from="public.guilds",
        into="public.guild_administration",
    )

    _run(
        [
            f'REVOKE ALL ON TABLE public.guild_administration FROM "{role}"',
            "DROP POLICY IF EXISTS billing_guild_administration_update ON "
            "public.guild_administration",
            "DROP POLICY IF EXISTS billing_guild_administration_select ON "
            "public.guild_administration",
            "DROP POLICY IF EXISTS guild_administration_pam_read ON "
            "public.guild_administration",
            "DROP POLICY IF EXISTS guild_administration_select ON "
            "public.guild_administration",
            "ALTER TABLE public.guild_administration DISABLE ROW LEVEL SECURITY",
        ]
    )
    op.drop_index("ix_guild_administration_guild_id", table_name="guild_administration")
    op.drop_table("guild_administration")

    # Restore the column-scoped billing grants the dropped columns took with them.
    _run(
        [
            "GRANT SELECT (id, tier_name, max_storage_bytes, max_users, status) "
            f'ON public.guilds TO "{role}"',
            "GRANT UPDATE (tier_name, max_storage_bytes, max_users, status, "
            f'status_changed_at, updated_at) ON public.guilds TO "{role}"',
        ]
    )
