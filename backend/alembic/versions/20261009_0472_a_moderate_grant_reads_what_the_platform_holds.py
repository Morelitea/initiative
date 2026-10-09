"""a moderate grant reads what the platform holds

Two changes for holds (``app.db.holds``), which the provisioning run renders
the rest of once they are in place:

- ``public.standing`` gains ``pam_moderate``: a live content grant at
  ``moderate`` covers the request, so held content reads. ``current_standing()``
  in every guild schema that has one is restated to build the longer value.
- ``access_grants.access_level`` admits ``moderate`` for a content grant.

The bodies are stated here in full, as they were and as they become, so this
revision reads the same whatever the modules say later.

Revision ID: 20261009_0472
Revises: 20261008_0471
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20261009_0472"
down_revision = "20261008_0471"
branch_labels = None
depends_on = None

#: ``current_standing()`` as revision 20261004_0454 built it.
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
        NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer,
        COALESCE(string_to_array(NULLIF(current_setting('app.install_read'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.install_write'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        current_setting('app.content_hold'::text, true) = 'true'::text
    )::public.standing;
END
$function$

"""

#: ``current_standing()`` with ``pam_moderate`` last.
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
        current_setting('app.content_hold'::text, true) = 'true'::text,
        current_setting('app.pam_moderate'::text, true) = 'true'::text
    )::public.standing;
END
$function$

"""

_LEVEL_CK = "ck_access_grants_access_level"
_SETTINGS_LEVELS = "'admin', 'superadmin'"


def _rule(content_levels: str) -> str:
    return (
        f"(purpose = 'settings' AND access_level IN ({_SETTINGS_LEVELS}))"
        " OR (purpose = 'billing' AND access_level = 'read')"
        f" OR (purpose NOT IN ('settings', 'billing')"
        f" AND access_level IN ({content_levels}))"
    )


_LEVEL_RULE = _rule("'read', 'read_write', 'moderate'")
_PRIOR_LEVEL_RULE = _rule("'read', 'read_write'")


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
    op.execute("ALTER TYPE public.standing ADD ATTRIBUTE pam_moderate boolean")
    _restate(bind, CURRENT_STANDING_AFTER)
    op.drop_constraint(_LEVEL_CK, "access_grants", type_="check")
    op.create_check_constraint(_LEVEL_CK, "access_grants", _LEVEL_RULE)


def downgrade() -> None:
    bind = op.get_bind()
    # A moderate grant has no reading once the level is gone.
    op.execute("ALTER TABLE access_grants NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("DELETE FROM access_grants WHERE access_level = 'moderate'")
    finally:
        op.execute("ALTER TABLE access_grants FORCE ROW LEVEL SECURITY")
    op.drop_constraint(_LEVEL_CK, "access_grants", type_="check")
    op.create_check_constraint(_LEVEL_CK, "access_grants", _PRIOR_LEVEL_RULE)
    # The per-schema reader of the field is rendered at boot; the copy each
    # schema carries goes with the attribute.
    for schema in guild_schema_names(bind):
        op.execute(f'DROP FUNCTION IF EXISTS "{schema}".standing_pam_moderate()')
    op.execute("ALTER TYPE public.standing DROP ATTRIBUTE pam_moderate")
    _restate(bind, CURRENT_STANDING_BEFORE)
