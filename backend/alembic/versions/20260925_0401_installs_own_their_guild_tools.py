"""installs own their guild tools

A guild-level tool row made inside a tool app is owned by the install: an owner
grant naming ``app_install_id``. That grant is now the record of what the
install produced, so:

- every calendar an install listed in ``guild_apps.artifacts`` gets the
  install's owner grant, and whoever owned it before keeps ``write`` on it;
- ``guild_apps.artifacts`` is dropped;
- ``tr_guild_apps_guard_granted_scopes`` and ``public.fn_guard_granted_scopes()``
  (20260924_0377) are dropped. ``guild_apps`` is written by the seat alone now,
  through its ``seat_*`` policies, which the provisioning run renders.

The downgrade restores the column from the install's owner grants and restores
the trigger. It leaves ownership with the install.

Revision ID: 20260925_0401
Revises: 20260925_0400
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260925_0401"
down_revision = "20260925_0400"
branch_labels = None
depends_on = None


_TABLES = ("guild_apps", "calendars", "resource_grants")

_GUARD_TRIGGER = "tr_guild_apps_guard_granted_scopes"

#: As 20260924_0377 wrote it.
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

#: Each guild-level calendar an install listed, once, with the install that
#: listed it first.
_LISTED_CALENDARS = """
SELECT DISTINCT ON (c.id) a.id AS install_id, c.id AS calendar_id
  FROM guild_apps a
 CROSS JOIN LATERAL jsonb_array_elements(
       CASE WHEN jsonb_typeof(a.artifacts) = 'array' THEN a.artifacts
            ELSE '[]'::jsonb END) e
  JOIN calendars c
    ON e->>'type' = 'calendar'
   AND jsonb_typeof(e->'id') = 'number'
   AND c.id = (e->>'id')::int
   AND c.initiative_id IS NULL
 ORDER BY c.id, a.id
"""


def _forced(bind) -> list[str]:
    """The tables of ``_TABLES`` that force RLS on their owner here."""
    return [
        table
        for table in _TABLES
        if bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    ]


def _unforced(bind, write) -> None:
    """Run ``write`` with the owner's RLS lifted on ``_TABLES``, restored after."""
    forced = _forced(bind)
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        write()
    finally:
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_upgrade(bind))
    op.execute("DROP FUNCTION IF EXISTS public.fn_guard_granted_scopes()")


def _give_to_installs(bind) -> None:
    for install_id, calendar_id in bind.execute(sa.text(_LISTED_CALENDARS)).all():
        params = {"i": install_id, "c": calendar_id}
        bind.execute(
            sa.text(
                "UPDATE resource_grants SET level = 'write' "
                "WHERE resource_type = 'calendar' AND resource_id = :c "
                "AND level = 'owner' AND app_install_id IS DISTINCT FROM :i"
            ),
            params,
        )
        promoted = bind.execute(
            sa.text(
                "UPDATE resource_grants SET level = 'owner' "
                "WHERE resource_type = 'calendar' AND resource_id = :c "
                "AND app_install_id = :i"
            ),
            params,
        ).rowcount
        if not promoted:
            bind.execute(
                sa.text(
                    "INSERT INTO resource_grants (resource_type, resource_id, "
                    "app_install_id, level, initiative_id, all_initiative_members, "
                    "created_at) VALUES ('calendar', :c, :i, 'owner', NULL, false, "
                    "now())"
                ),
                params,
            )


def _apply_upgrade(bind) -> None:
    _unforced(bind, lambda: _give_to_installs(bind))
    op.execute(f"DROP TRIGGER IF EXISTS {_GUARD_TRIGGER} ON guild_apps")
    op.drop_column("guild_apps", "artifacts")


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(_GUARD_FUNCTION)
    run_for_each_guild_schema(bind, lambda: _apply_downgrade(bind))


def _list_owned(bind) -> None:
    bind.execute(
        sa.text(
            """
            UPDATE guild_apps a SET artifacts = COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                           'type', g.resource_type, 'id', g.resource_id)
                       ORDER BY g.resource_id)
                  FROM resource_grants g
                 WHERE g.app_install_id = a.id
                   AND g.level = 'owner'
                   AND g.initiative_id IS NULL
                   AND g.resource_type = 'calendar'
            ), '[]'::jsonb)
            """
        )
    )


def _apply_downgrade(bind) -> None:
    op.add_column(
        "guild_apps",
        sa.Column(
            "artifacts",
            postgresql.JSONB(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    _unforced(bind, lambda: _list_owned(bind))
    op.execute(
        f"CREATE OR REPLACE TRIGGER {_GUARD_TRIGGER} "
        "BEFORE INSERT OR UPDATE ON guild_apps "
        "FOR EACH ROW EXECUTE FUNCTION public.fn_guard_granted_scopes()"
    )
