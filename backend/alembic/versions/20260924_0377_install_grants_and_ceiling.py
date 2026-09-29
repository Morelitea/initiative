"""install grants and ceiling

The columns an app acting as its community is later authorized from:

- ``guild_apps.granted_scopes``: the scopes the community's seat consented to
  for the install. Empty on every existing install, since nothing is granted
  by default.
- ``resource_grants.app_install_id``: the fifth grantee kind, an installed app.
  ``resource_grants_one_grantee`` counts it and ``resource_grants_unique_grantee``
  includes it. Deleting the install deletes its grants.
- ``public.app_service_registrations.scope_ceiling``: the most any install of
  an operator-registered app may be granted. Empty on every existing row.

Nothing reads the new columns yet, and every existing row satisfies the new
constraints unchanged: its ``app_install_id`` is NULL.

Revision ID: 20260924_0377
Revises: 20260924_0376
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260924_0377"
down_revision = "20260924_0376"
branch_labels = None
depends_on = None


#: The grantee test, before and after. One kind per row either way.
_ONE_GRANTEE_BEFORE = (
    "(user_id IS NOT NULL)::int + (role_id IS NOT NULL)::int "
    "+ (all_initiative_members)::int + (dashboard_id IS NOT NULL)::int = 1"
)
_ONE_GRANTEE_AFTER = (
    "(user_id IS NOT NULL)::int + (role_id IS NOT NULL)::int "
    "+ (all_initiative_members)::int + (dashboard_id IS NOT NULL)::int "
    "+ (app_install_id IS NOT NULL)::int = 1"
)

#: The uniqueness of a grantee on a resource. NULLS NOT DISTINCT so the unused
#: grantee columns compare equal.
_UNIQUE_BEFORE = "(resource_type, resource_id, user_id, role_id, dashboard_id)"
_UNIQUE_AFTER = (
    "(resource_type, resource_id, user_id, role_id, dashboard_id, app_install_id)"
)


def _swap(one_grantee: str, unique: str) -> None:
    op.execute(
        "ALTER TABLE resource_grants DROP CONSTRAINT resource_grants_one_grantee"
    )
    op.execute(
        "ALTER TABLE resource_grants ADD CONSTRAINT resource_grants_one_grantee "
        f"CHECK ({one_grantee})"
    )
    op.execute(
        "ALTER TABLE resource_grants DROP CONSTRAINT resource_grants_unique_grantee"
    )
    op.execute(
        "ALTER TABLE resource_grants ADD CONSTRAINT resource_grants_unique_grantee "
        f"UNIQUE NULLS NOT DISTINCT {unique}"
    )


def _forced(bind, table: str) -> bool:
    """Whether ``table`` currently forces RLS on its owner."""
    return bool(
        bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )


#: Who may change what an install is granted: the community's seat, as the
#: standing statement read it (the same test the seat's write policies apply),
#: or the system engine. The rest of the install row stays writable by the
#: paths that already write it: a member creating a guild calendar records the
#: artifact on it, and a member disconnecting their own account locks it.
_GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION public.fn_guard_granted_scopes() RETURNS trigger
    LANGUAGE plpgsql AS $guard$
BEGIN
    IF (TG_OP = 'INSERT' AND NEW.granted_scopes <> '{}'::text[])
       OR (TG_OP = 'UPDATE'
           AND NEW.granted_scopes IS DISTINCT FROM OLD.granted_scopes) THEN
        IF NOT (
            EXISTS (SELECT 1 FROM pg_roles r
                     WHERE r.rolname = session_user AND r.rolbypassrls)
            OR (
                NULLIF(current_setting('app.standing_guild_id', true), '')
                    IS NOT DISTINCT FROM COALESCE(
                        NULLIF(current_setting('app.current_guild_id', true), ''),
                        NULLIF(current_setting('app.pam_guild_id', true), ''),
                        NULLIF(current_setting('app.settings_guild_id', true), ''))
                AND current_setting('app.guild_seat', true) = 'true'
                AND (current_setting('app.guild_admin', true) = 'true'
                     OR current_setting('app.pam_write', true) = 'true')
            )
        ) THEN
            RAISE EXCEPTION 'an install''s granted scopes are the seat''s to change'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END;
$guard$;
"""

_GUARD_TRIGGER = "tr_guild_apps_guard_granted_scopes"


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(_GUARD_FUNCTION)
    run_for_each_guild_schema(bind, _apply_upgrade)
    op.add_column(
        "app_service_registrations",
        sa.Column(
            "scope_ceiling",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        schema="public",
    )


def _apply_upgrade() -> None:
    op.add_column(
        "guild_apps",
        sa.Column(
            "granted_scopes",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "resource_grants",
        sa.Column("app_install_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "resource_grants_app_install_id_fkey",
        "resource_grants",
        "guild_apps",
        ["app_install_id"],
        ["id"],
        ondelete="CASCADE",
    )
    _swap(_ONE_GRANTEE_AFTER, _UNIQUE_AFTER)
    # What an install has been granted, which the uninstall cascade and the
    # install's own reads both look up by.
    op.execute(
        "CREATE INDEX ix_resource_grants_app_install ON resource_grants "
        "(app_install_id) WHERE app_install_id IS NOT NULL"
    )
    op.execute(
        f"CREATE OR REPLACE TRIGGER {_GUARD_TRIGGER} "
        "BEFORE INSERT OR UPDATE ON guild_apps "
        "FOR EACH ROW EXECUTE FUNCTION public.fn_guard_granted_scopes()"
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_column("app_service_registrations", "scope_ceiling", schema="public")
    run_for_each_guild_schema(bind, lambda: _apply_downgrade(bind))
    op.execute("DROP FUNCTION IF EXISTS public.fn_guard_granted_scopes()")


def _apply_downgrade(bind) -> None:
    # The rows go with the column: a grant naming only an app install has no
    # grantee once the column is gone, and the earlier CHECK would refuse it.
    forced = _forced(bind, "resource_grants")
    if forced:
        op.execute("ALTER TABLE resource_grants NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("DELETE FROM resource_grants WHERE app_install_id IS NOT NULL")
    finally:
        if forced:
            op.execute("ALTER TABLE resource_grants FORCE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_resource_grants_app_install")
    _swap(_ONE_GRANTEE_BEFORE, _UNIQUE_BEFORE)
    op.drop_constraint(
        "resource_grants_app_install_id_fkey", "resource_grants", type_="foreignkey"
    )
    op.drop_column("resource_grants", "app_install_id")
    op.execute(f"DROP TRIGGER IF EXISTS {_GUARD_TRIGGER} ON guild_apps")
    op.drop_column("guild_apps", "granted_scopes")
