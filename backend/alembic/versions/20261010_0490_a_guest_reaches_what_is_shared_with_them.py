"""a guest reaches what is shared with them

- ``guest_base``: the floor in ``public`` the community's guest roles
  inherit. It reads what a guest's standing and the community's sign-in check
  read (a guest's own membership row, the routed community, its sign-in rule,
  connections and options, the platform's provider defaults, the guest's own
  access grants and the deployment's settings), reads people's profiles as
  the community shows them (``guild_member_profiles``, as its members do) and
  appends notices. The row
  policies on those tables are rendered at boot (``app.db.public_rls``), as
  are the guest roles and their policies in each community's schema
  (``app.db.guest_access``).
- ``public.standing`` gains ``guest`` and ``guest_item_initiatives``.
  ``current_standing()`` in every guild schema that has one is restated to
  build the longer value.

The bodies are stated here in full, as they were and as they become, so this
revision reads the same whatever the modules say later.

Revision ID: 20261010_0490
Revises: 20261010_0489
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings
from app.db.guild_migrations import guild_schema_names

revision = "20261010_0490"
down_revision = "20261010_0489"
branch_labels = None
depends_on = None

FLOOR = "guest_base"

#: What the floor reads, and the one table it appends to.
_READS = (
    "access_grants",
    "app_settings",
    "guild_administration",
    "guild_auth_policies",
    "guild_memberships",
    "guild_provider_connections",
    "guilds",
    "platform_provider_defaults",
)
_APPENDS = ("notice_outbox",)
#: People as the community shows them, read as its members read them.
_PROFILES = "public.guild_member_profiles"

#: The two guest roles of each community, by suffix.
_GUEST_ROLE_SUFFIXES = ("_guest", "_guest_ro")

#: ``current_standing()`` as revision 20261009_0472 built it.
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
        current_setting('app.content_hold'::text, true) = 'true'::text,
        current_setting('app.pam_moderate'::text, true) = 'true'::text
    )::public.standing;
END
$function$

"""

#: ``current_standing()`` with ``guest`` and ``guest_item_initiatives`` last.
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
        current_setting('app.pam_moderate'::text, true) = 'true'::text,
        current_setting('app.guest'::text, true) = 'true'::text,
        COALESCE(string_to_array(NULLIF(current_setting('app.guest_item_initiatives'::text, true), ''::text), ','::text)::integer[], ARRAY[]::integer[])
    )::public.standing;
END
$function$

"""


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
        bind.exec_driver_sql(body)
    bind.execute(sa.text("SELECT set_config('search_path', 'public', true)"))


def upgrade() -> None:
    bind = op.get_bind()
    # One role for the whole cluster, which every database shares.
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{FLOOR}') THEN
                CREATE ROLE "{FLOOR}" NOLOGIN;
            END IF;
        END $$;
        """
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{FLOOR}"')
    op.execute(f'GRANT SELECT ON {", ".join(_READS)} TO "{FLOOR}"')
    op.execute(f'GRANT INSERT ON {", ".join(_APPENDS)} TO "{FLOOR}"')
    op.execute(f'GRANT SELECT ON {_PROFILES} TO "{FLOOR}"')
    op.execute(
        "ALTER TYPE public.standing ADD ATTRIBUTE guest boolean,"
        " ADD ATTRIBUTE guest_item_initiatives integer[]"
    )
    _restate(bind, CURRENT_STANDING_AFTER)


def downgrade() -> None:
    bind = op.get_bind()
    provisioner = bind.execute(sa.text("SELECT current_user")).scalar()
    # The community guest roles, and the policies and readers each schema
    # carries for them, go with the floor.
    for schema in guild_schema_names(bind):
        for name in ("standing_guest", "standing_guest_item_initiatives"):
            op.execute(f'DROP FUNCTION IF EXISTS "{schema}".{name}()')
        if not schema.startswith("guild_") or schema == "guild_template":
            continue
        for suffix in _GUEST_ROLE_SUFFIXES:
            role = f"{settings.GUILD_ROLE_PREFIX}{schema}{suffix}"
            if bind.execute(
                sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
            ).scalar():
                op.execute(f'GRANT "{role}" TO "{provisioner}"')
                op.execute(f'DROP OWNED BY "{role}"')
                op.execute(f'DROP ROLE "{role}"')
    op.execute("ALTER TYPE public.standing DROP ATTRIBUTE guest_item_initiatives")
    op.execute("ALTER TYPE public.standing DROP ATTRIBUTE guest")
    _restate(bind, CURRENT_STANDING_BEFORE)
    op.execute(f'GRANT "{FLOOR}" TO "{provisioner}"')
    # This database's grants and policies naming the floor; the role itself
    # goes once no other database holds anything through it.
    op.execute(f'DROP OWNED BY "{FLOOR}"')
    op.execute(f'REVOKE "{FLOOR}" FROM "{provisioner}"')
    op.execute(
        f"""
        DO $$ BEGIN
            BEGIN
                DROP ROLE "{FLOOR}";
            EXCEPTION WHEN dependent_objects_still_exist THEN
                NULL;
            END;
        END $$;
        """
    )
