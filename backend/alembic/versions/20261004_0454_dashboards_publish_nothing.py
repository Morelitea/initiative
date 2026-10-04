"""dashboards publish nothing

A dashboard used to be able to publish over individual resources: a
``resource_grants`` row naming the dashboard as grantee, which the access
functions honoured while ``app.via_dashboard_id`` named that dashboard. A
dashboard now says whose access it runs as instead (``dashboards.view_mode``,
revision 20261004_0453), so the per-resource mechanism goes:

- the grants made to a dashboard are deleted, and ``resource_grants`` loses
  ``dashboard_id`` with its index, foreign key and the checks that named it;
- ``public.standing`` loses ``via_dashboard_id``, and ``current_standing()`` in
  every guild schema that has one is restated to build the shorter value;
- the per-schema ``standing_via_dashboard_id()`` helper is dropped.

The access functions that read the field, and the row-level policies on
``resource_grants`` that read the column, are rendered from the application at
boot: the policies are dropped here so the column can go, and the next start
writes them all back from the current render. The bodies here are stated
in full, as they were and as they become, so this revision reads the same
whatever the module says later.

Revision ID: 20261004_0454
Revises: 20261004_0453
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names, run_for_each_guild_schema

revision = "20261004_0454"
down_revision = "20261004_0453"
branch_labels = None
depends_on = None

_TABLE = "resource_grants"

#: ``public.standing``'s attributes after ``via_dashboard_id``, in order. A
#: composite's attributes are positional, so putting the field back means
#: putting these back after it.
_AFTER_VIA_DASHBOARD = (
    ("install_id", "integer"),
    ("install_read", "text[]"),
    ("install_write", "text[]"),
    ("content_hold", "boolean"),
)

_ONE_GRANTEE_BEFORE = (
    "(user_id IS NOT NULL)::int + (role_id IS NOT NULL)::int "
    "+ (all_initiative_members)::int + (dashboard_id IS NOT NULL)::int "
    "+ (app_install_id IS NOT NULL)::int = 1"
)
_ONE_GRANTEE_AFTER = (
    "(user_id IS NOT NULL)::int + (role_id IS NOT NULL)::int "
    "+ (all_initiative_members)::int "
    "+ (app_install_id IS NOT NULL)::int = 1"
)

#: ``current_standing()`` with ``via_dashboard_id``.
CURRENT_STANDING_BEFORE = """\
CREATE OR REPLACE FUNCTION current_standing()
 RETURNS standing
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN ROW(
        EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname = session_user AND r.rolbypassrls),
        NULLIF(current_setting('app.standing_guild_id'::text, true), ''::text) IS NOT DISTINCT FROM COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)),
        (NULLIF(current_setting('app.standing_guild_id'::text, true), ''::text) IS NOT DISTINCT FROM COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)) AND current_setting('app.guild_admin'::text, true) = 'true'::text),
        current_setting('app.guild_auth_ok'::text, true) = 'true'::text,
        NULLIF(current_setting('app.scope_initiative_id'::text, true), ''::text)::integer,
        current_setting('app.pam_read'::text, true) = 'true'::text,
        current_setting('app.pam_write'::text, true) = 'true'::text,
        COALESCE(string_to_array(NULLIF(current_setting('app.member_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.manager_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.override_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.member_role_ids'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.role_grants'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.role_denies'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.enabled_tools'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        NULLIF(current_setting('app.via_dashboard_id'::text, true), ''::text)::integer,
        NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer,
        COALESCE(string_to_array(NULLIF(current_setting('app.install_read'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.install_write'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        current_setting('app.content_hold'::text, true) = 'true'::text
    )::public.standing;
END
$function$

"""

#: ``current_standing()`` without it.
CURRENT_STANDING_AFTER = """\
CREATE OR REPLACE FUNCTION current_standing()
 RETURNS standing
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN ROW(
        EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname = session_user AND r.rolbypassrls),
        NULLIF(current_setting('app.standing_guild_id'::text, true), ''::text) IS NOT DISTINCT FROM COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)),
        (NULLIF(current_setting('app.standing_guild_id'::text, true), ''::text) IS NOT DISTINCT FROM COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)) AND current_setting('app.guild_admin'::text, true) = 'true'::text),
        current_setting('app.guild_auth_ok'::text, true) = 'true'::text,
        NULLIF(current_setting('app.scope_initiative_id'::text, true), ''::text)::integer,
        current_setting('app.pam_read'::text, true) = 'true'::text,
        current_setting('app.pam_write'::text, true) = 'true'::text,
        COALESCE(string_to_array(NULLIF(current_setting('app.member_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.manager_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.override_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.member_role_ids'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.role_grants'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.role_denies'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.enabled_tools'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer,
        COALESCE(string_to_array(NULLIF(current_setting('app.install_read'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.install_write'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        current_setting('app.content_hold'::text, true) = 'true'::text
    )::public.standing;
END
$function$

"""


def _write_unforced(statement: str) -> None:
    """Run one DML statement on a table that already has FORCE row security,
    lifting it for the statement and restoring it either way."""
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(statement)
    finally:
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")


def _unique_grantee(columns: str) -> None:
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT resource_grants_unique_grantee "
        f"UNIQUE NULLS NOT DISTINCT (resource_type, resource_id, {columns})"
    )


#: The row-level policies that read ``resource_grants.dashboard_id``, found by
#: the catalog's own dependency record rather than by name, so a policy any
#: past render wrote is found too.
_POLICIES_ON_THE_COLUMN = sa.text(
    """
    SELECT DISTINCT c.relname, pol.polname
      FROM pg_depend d
      JOIN pg_policy pol ON d.classid = 'pg_policy'::regclass AND d.objid = pol.oid
      JOIN pg_class c ON c.oid = pol.polrelid
     WHERE d.refclassid = 'pg_class'::regclass
       AND d.refobjid = to_regclass('resource_grants')
       AND d.refobjsubid = (
           SELECT attnum FROM pg_attribute
            WHERE attrelid = to_regclass('resource_grants')
              AND attname = 'dashboard_id'
       )
    """
)


def _drop_policies_on_the_column() -> None:
    """Drop the policies that read the column, so it can go.

    Every policy here is rendered from the application at boot, and the
    render no longer names the column, so the next start writes them back
    without it."""
    for table, policy in op.get_bind().execute(_POLICIES_ON_THE_COLUMN).all():
        op.execute(f'DROP POLICY IF EXISTS "{policy}" ON "{table}"')


def _upgrade_schema() -> None:
    _write_unforced(f"DELETE FROM {_TABLE} WHERE dashboard_id IS NOT NULL")
    _drop_policies_on_the_column()
    op.execute("DROP INDEX IF EXISTS ix_resource_grants_dashboard")
    for name in (
        "resource_grants_dashboard_reads",
        "resource_grants_one_grantee",
        "resource_grants_unique_grantee",
        "resource_grants_dashboard_id_fkey",
    ):
        op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {name}")
    op.drop_column(_TABLE, "dashboard_id")
    op.create_check_constraint(
        "resource_grants_one_grantee", _TABLE, _ONE_GRANTEE_AFTER
    )
    _unique_grantee("user_id, role_id, app_install_id")


def _downgrade_schema() -> None:
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT resource_grants_one_grantee")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT resource_grants_unique_grantee")
    op.add_column(_TABLE, sa.Column("dashboard_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "resource_grants_dashboard_id_fkey",
        _TABLE,
        "dashboards",
        ["dashboard_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "resource_grants_one_grantee", _TABLE, _ONE_GRANTEE_BEFORE
    )
    op.create_check_constraint(
        "resource_grants_dashboard_reads",
        _TABLE,
        "dashboard_id IS NULL OR level = 'read'",
    )
    _unique_grantee("user_id, role_id, dashboard_id, app_install_id")
    op.create_index(
        "ix_resource_grants_dashboard",
        _TABLE,
        ["dashboard_id"],
        postgresql_where=sa.text("dashboard_id IS NOT NULL"),
    )


def _schemas_with_standing(bind) -> list[str]:
    """The guild schemas that carry ``current_standing()``. The template holds
    structure only, and a schema the back-fill has not rendered yet is given the
    current body when it is."""
    return [
        schema
        for schema in guild_schema_names(bind)
        if bind.execute(
            sa.text("SELECT to_regprocedure(CAST(:sig AS text)) IS NOT NULL"),
            {"sig": f"{schema}.current_standing()"},
        ).scalar()
    ]


def _restate(bind, body: str) -> None:
    for schema in _schemas_with_standing(bind):
        bind.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        op.execute(body)
    bind.execute(sa.text("SELECT set_config('search_path', 'public', true)"))


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, _upgrade_schema)
    op.execute("ALTER TYPE public.standing DROP ATTRIBUTE via_dashboard_id")
    _restate(bind, CURRENT_STANDING_AFTER)
    # The per-schema helper that read the field is no longer rendered at boot,
    # so the copy an existing schema carries goes here; a fresh one never has it.
    for schema in guild_schema_names(bind):
        op.execute(f'DROP FUNCTION IF EXISTS "{schema}".standing_via_dashboard_id()')


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(
        "ALTER TYPE public.standing "
        + ", ".join(
            f"DROP ATTRIBUTE {name}" for name, _type in reversed(_AFTER_VIA_DASHBOARD)
        )
    )
    op.execute(
        "ALTER TYPE public.standing "
        + ", ".join(
            f"ADD ATTRIBUTE {name} {sqltype}"
            for name, sqltype in (
                ("via_dashboard_id", "integer"),
                *_AFTER_VIA_DASHBOARD,
            )
        )
    )
    _restate(bind, CURRENT_STANDING_BEFORE)
    run_for_each_guild_schema(bind, _downgrade_schema)
