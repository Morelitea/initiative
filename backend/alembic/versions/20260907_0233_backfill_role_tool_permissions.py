"""backfill role tool permissions

Every tool that shipped after a role was created left that role without its two
permission rows. A ``project_manager`` role created before Posts has 12 rows
where one created today has 14; the same is true of queues, counters,
calendars and dashboards for any initiative older than each of them.

Nothing was mis-authorized — an absent row reads as the documented default —
but the stored role and the role the code describes had drifted, which is what
the settings screens read. This writes the rows that were never written, at the
values a role created today would get: the built-in ``project_manager`` gets
everything, every other role gets the documented default (view on for the core
always-on tools, off for the opt-in ones, create off).

Existing rows are left exactly as they are, so a permission an operator turned
off stays off.

Everything this revision writes is stated here — the key list, the defaults and
the statement itself — rather than read from a shared helper. A migration is a
historical record: a helper carrying table names, columns and the built-in role
rule could be edited later and would then change what this revision does to a
database upgrading through it. The next tool that ships copies this file.

Revision ID: 20260907_0233
Revises: 20260906_0232
Create Date: 2026-09-07
"""

from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260907_0233"
down_revision = "20260906_0232"
branch_labels = None
depends_on = None

_TABLE = "initiative_role_permissions"

# Permission key → the value a role created at this revision stores. Mirrors
# ``DEFAULT_PERMISSION_VALUES`` as it stood here: viewing a core (always-on)
# tool is on, viewing an opt-in tool is off, creating anything is off.
_ROLE_PERMISSION_DEFAULTS: dict[str, bool] = {
    "projects_enabled": True,
    "documents_enabled": True,
    "queues_enabled": False,
    "counter_groups_enabled": False,
    "calendars_enabled": False,
    "dashboards_enabled": False,
    "posts_enabled": False,
    "create_projects": False,
    "create_documents": False,
    "create_queues": False,
    "create_counter_groups": False,
    "create_calendars": False,
    "create_dashboards": False,
    "create_posts": False,
}


def backfill_sql(defaults: dict[str, bool]) -> str:
    """The INSERT this revision runs, unqualified so it applies in whichever
    guild schema the search_path names.

    A function rather than a literal so the statement can be exercised against
    a real schema from a test.
    """
    values = ", ".join(
        f"('{key}', {'true' if enabled else 'false'})"
        for key, enabled in sorted(defaults.items())
    )
    return f"""
        INSERT INTO {_TABLE} (initiative_role_id, permission_key, enabled)
        SELECT r.id,
               k.permission_key,
               CASE
                   WHEN r.is_builtin AND r.name = 'project_manager' THEN true
                   ELSE k.enabled
               END
        FROM initiative_roles AS r
        CROSS JOIN (VALUES {values}) AS k(permission_key, enabled)
        ON CONFLICT (initiative_role_id, permission_key) DO NOTHING
    """


def _backfill() -> None:
    # The table already exists, so it needs migration-time write access for
    # this insert; it is restored immediately afterwards either way.
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(backfill_sql(_ROLE_PERMISSION_DEFAULTS))
    finally:
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _backfill)


def downgrade() -> None:
    # Nothing to undo: the rows written here hold the values the absent rows
    # already resolved to, so removing them would change no decision — and
    # there is no record of which rows this migration added versus which the
    # role has carried since it was created.
    pass
