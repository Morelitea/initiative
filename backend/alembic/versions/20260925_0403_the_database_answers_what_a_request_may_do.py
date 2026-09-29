"""the database answers what a request may do

Two changes the gates in each guild schema need, which the provisioning run
renders from ``app.db.authorization`` once these are in place:

- ``public.standing`` gains ``content_hold``: the community's content is on
  hold (``read_only``) for this reader. ``current_standing()`` in every guild
  schema that has one is restated to build the longer value.
- ``public.fn_install_owns_what_it_creates()`` writes the owner row for a
  person's create as well as an installed app's, so the row is written by the
  database whoever makes the resource. A row outside any initiative gets none:
  it is community level, owned by the app install that mounts it.
- Grants naming someone who is no longer in the grant's initiative are
  removed, owner rows included. Leaving an initiative takes them with it from
  now on (``tr_initiative_members_departure``, rendered by provisioning); these
  are the ones earlier departures left, and what they owned becomes unowned.
  Not restored by the downgrade.

The bodies are stated here in full, as they were and as they become, so this
revision reads the same whatever the modules say later.

Revision ID: 20260925_0403
Revises: 20260925_0402
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20260925_0403"
down_revision = "20260925_0402"
branch_labels = None
depends_on = None

#: ``current_standing()`` as revision 20260924_0379 built it.
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
        COALESCE(string_to_array(NULLIF(current_setting('app.install_write'::text, true), ''::text), ','::text), ARRAY[]::text[])
    )::public.standing;
END
$function$

"""

#: ``current_standing()`` with ``content_hold`` at the end.
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
        NULLIF(current_setting('app.via_dashboard_id'::text, true), ''::text)::integer,
        NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer,
        COALESCE(string_to_array(NULLIF(current_setting('app.install_read'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        COALESCE(string_to_array(NULLIF(current_setting('app.install_write'::text, true), ''::text), ','::text), ARRAY[]::text[]),
        current_setting('app.content_hold'::text, true) = 'true'::text
    )::public.standing;
END
$function$

"""

#: As revision 20260924_0385 wrote it.
OWNS_FUNCTION_BEFORE = """
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := NULLIF(
        current_setting('app.current_install_id', true), ''
    )::integer;
    v_member integer := NULLIF(
        current_setting('app.current_user_id', true), ''
    )::integer;
BEGIN
    IF v_install IS NULL THEN
        RETURN NULL;
    END IF;
    IF v_member IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, app_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    ELSE
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, user_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_member;
    END IF;
    RETURN NULL;
END;
$owns$;
"""

#: Writing a person's owner row too, and none for a community-level row.
OWNS_FUNCTION_AFTER = """
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := NULLIF(
        current_setting('app.current_install_id', true), ''
    )::integer;
    v_member integer := NULLIF(
        current_setting('app.current_user_id', true), ''
    )::integer;
BEGIN
    IF NEW.initiative_id IS NULL OR (v_install IS NULL AND v_member IS NULL) THEN
        RETURN NULL;
    END IF;
    IF v_member IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, app_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    ELSE
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, user_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_member;
    END IF;
    RETURN NULL;
END;
$owns$;
"""


def _schemas_with_standing(bind) -> list[str]:
    """The guild schemas that carry ``current_standing()``."""
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


#: Grants naming a person who is not a member of the grant's initiative.
_STALE = """
    FROM {schema}.resource_grants g
    WHERE g.user_id IS NOT NULL
      AND g.initiative_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM {schema}.initiative_members m
        WHERE m.user_id = g.user_id AND m.initiative_id = g.initiative_id
      )
"""


def _drop_stale_grants(bind, schema: str) -> None:
    """Remove ``schema``'s stale grants. ``resource_grants`` is FORCE RLS and a
    migration carries no request context, so the owner's policies are lifted
    before anything reads it and restored after; its triggers (the freeze, the
    change capture) are about requests and are held while rows are removed."""
    table = f"{schema}.resource_grants"
    count = sa.text(f"SELECT count(*) {_STALE.format(schema=schema)}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        stale = bind.execute(count).scalar()
        if stale:
            op.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
            op.execute(f"DELETE {_STALE.format(schema=schema)}")
            op.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
            left = bind.execute(count).scalar()
            assert left == 0, f"{schema}: {left} of {stale} stale grants remain"
    finally:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TYPE public.standing ADD ATTRIBUTE content_hold boolean")
    _restate(bind, CURRENT_STANDING_AFTER)
    op.execute(OWNS_FUNCTION_AFTER)
    for schema in guild_schema_names(bind):
        _drop_stale_grants(bind, schema)


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(OWNS_FUNCTION_BEFORE)
    op.execute("ALTER TYPE public.standing DROP ATTRIBUTE content_hold")
    _restate(bind, CURRENT_STANDING_BEFORE)
