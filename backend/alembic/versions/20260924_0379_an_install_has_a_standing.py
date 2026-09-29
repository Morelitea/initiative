"""an install has a standing

An installed app acting in its community is routed like a person: the routing
statement names the community and the install, and a second statement computes
what the install reaches from rows. Three values join the request's standing:

- ``install_id``: the install the request is for, unset on every request a
  person makes;
- ``install_read`` and ``install_write``: the resources its scopes let it read
  and write.

They are appended to ``public.standing``, whose attributes are positional, and
``current_standing()`` in every guild schema that has one is restated to build
the longer value. The bodies are stated here in full, as they were and as they
become, so this revision reads the same whatever the module says later.

The install floor, ``app_install_base``, gains what the install's standing
statement reads in ``public``: the routed community's status, and the
registration its token was issued to. Column grants, so nothing else on either
row is readable. The policies admitting those two rows are rendered from
``app.db.public_rls`` at boot, like every shared table's.

Revision ID: 20260924_0379
Revises: 20260924_0378
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20260924_0379"
down_revision = "20260924_0378"
branch_labels = None
depends_on = None

#: Appended to ``public.standing``, in this order.
_ATTRIBUTES = (
    ("install_id", "integer"),
    ("install_read", "text[]"),
    ("install_write", "text[]"),
)

#: What the install floor reads, column by column.
_INSTALL_BASE_READS = {
    "guilds": ("id", "status"),
    "app_service_registrations": ("public_id", "listing_uid", "enabled"),
}

#: ``current_standing()`` as revision 20260923_0356's standing type built it.
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
        NULLIF(current_setting('app.via_dashboard_id'::text, true), ''::text)::integer
    )::public.standing;
END
$function$

"""

#: ``current_standing()`` with the three install fields at the end.
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
        COALESCE(string_to_array(NULLIF(current_setting('app.install_write'::text, true), ''::text), ','::text), ARRAY[]::text[])
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
        op.execute(body)
    bind.execute(sa.text("SELECT set_config('search_path', 'public', true)"))


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(
        "ALTER TYPE public.standing "
        + ", ".join(f"ADD ATTRIBUTE {name} {sqltype}" for name, sqltype in _ATTRIBUTES)
    )
    _restate(bind, CURRENT_STANDING_AFTER)
    for table, columns in _INSTALL_BASE_READS.items():
        op.execute(
            f"GRANT SELECT ({', '.join(columns)}) ON public.{table} TO app_install_base"
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table, columns in _INSTALL_BASE_READS.items():
        op.execute(
            f"REVOKE SELECT ({', '.join(columns)}) ON public.{table} "
            "FROM app_install_base"
        )
    op.execute(
        "ALTER TYPE public.standing "
        + ", ".join(
            f"DROP ATTRIBUTE {name}" for name, _sqltype in reversed(_ATTRIBUTES)
        )
    )
    _restate(bind, CURRENT_STANDING_BEFORE)
