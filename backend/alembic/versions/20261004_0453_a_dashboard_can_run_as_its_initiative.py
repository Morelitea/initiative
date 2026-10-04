"""a dashboard can run as its initiative

``dashboards.view_mode`` says whose access a dashboard's query widgets answer
from: ``individual`` (each viewer's own, the default) or ``initiative`` (full
read access to the dashboard's initiative, the same for everyone who can open
it).

``dashboards_run_as_initiative`` is the initiative role permission that lets a
role choose ``initiative``. Off for an ordinary role, on for the built-in
manager roles, backfilled onto every role that predates it.

Revision ID: 20261004_0453
Revises: 20261003_0452
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261004_0453"
down_revision = "20261003_0452"
branch_labels = None
depends_on = None

_ROLE_TABLE = "initiative_role_permissions"

_PERMISSION_KEYS_BEFORE = (
    "calendars_enabled",
    "counter_groups_enabled",
    "create_calendars",
    "create_counter_groups",
    "create_dashboards",
    "create_documents",
    "create_galleries",
    "create_posts",
    "create_projects",
    "create_queues",
    "create_wikis",
    "dashboards_enabled",
    "documents_enabled",
    "galleries_enabled",
    "posts_enabled",
    "projects_enabled",
    "queues_enabled",
    "wikis_enabled",
)
_PERMISSION_KEYS_AFTER = tuple(
    sorted((*_PERMISSION_KEYS_BEFORE, "dashboards_run_as_initiative"))
)

# Permission key -> the value a role created at this revision stores. Mirrors
# ``DEFAULT_PERMISSION_VALUES`` as it stands here — every key, so a role
# missing any of them is made whole by one pass.
_ROLE_PERMISSION_DEFAULTS: dict[str, bool] = {
    "projects_enabled": True,
    "documents_enabled": True,
    "queues_enabled": False,
    "counter_groups_enabled": False,
    "calendars_enabled": False,
    "dashboards_enabled": False,
    "posts_enabled": False,
    "galleries_enabled": False,
    "wikis_enabled": False,
    "create_projects": False,
    "create_documents": False,
    "create_queues": False,
    "create_counter_groups": False,
    "create_calendars": False,
    "create_dashboards": False,
    "create_posts": False,
    "create_galleries": False,
    "create_wikis": False,
    "dashboards_run_as_initiative": False,
}


def _quoted(values) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _swap_permission_key_check(keys) -> None:
    op.execute(
        f"ALTER TABLE {_ROLE_TABLE} "
        "DROP CONSTRAINT IF EXISTS ck_initiative_role_permissions_permission_key"
    )
    op.execute(
        f"ALTER TABLE {_ROLE_TABLE} "
        "ADD CONSTRAINT ck_initiative_role_permissions_permission_key "
        f"CHECK (permission_key::text = ANY (ARRAY[{_quoted(keys)}]::text[]))"
    )


def backfill_sql(defaults: dict[str, bool]) -> str:
    """The INSERT this revision runs, unqualified so it applies in whichever
    guild schema the search_path names. A built-in manager role holds every
    key; everything else gets the default."""
    values = ", ".join(
        f"('{key}', {'true' if enabled else 'false'})"
        for key, enabled in sorted(defaults.items())
    )
    return f"""
        INSERT INTO {_ROLE_TABLE} (initiative_role_id, permission_key, enabled)
        SELECT r.id,
               k.permission_key,
               CASE
                   WHEN r.is_builtin AND r.is_manager THEN true
                   ELSE k.enabled
               END
        FROM initiative_roles AS r
        CROSS JOIN (VALUES {values}) AS k(permission_key, enabled)
        ON CONFLICT (initiative_role_id, permission_key) DO NOTHING
    """


def _write_unforced(table: str, statement: str) -> None:
    """Run one DML statement on a table that already has FORCE row security,
    lifting it for the statement and restoring it either way."""
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(statement)
    finally:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _upgrade() -> None:
    op.add_column(
        "dashboards",
        sa.Column(
            "view_mode",
            sa.String(length=20),
            nullable=False,
            server_default="individual",
        ),
    )
    op.create_check_constraint(
        "ck_dashboards_view_mode",
        "dashboards",
        "view_mode IN ('individual', 'initiative')",
    )
    _swap_permission_key_check(_PERMISSION_KEYS_AFTER)
    _write_unforced(_ROLE_TABLE, backfill_sql(_ROLE_PERMISSION_DEFAULTS))


def _downgrade() -> None:
    _write_unforced(
        _ROLE_TABLE,
        f"DELETE FROM {_ROLE_TABLE} "
        "WHERE permission_key = 'dashboards_run_as_initiative'",
    )
    _swap_permission_key_check(_PERMISSION_KEYS_BEFORE)
    op.drop_constraint("ck_dashboards_view_mode", "dashboards", type_="check")
    op.drop_column("dashboards", "view_mode")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade)
