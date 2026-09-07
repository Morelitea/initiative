"""backfill role tool permissions

Every tool that shipped after a role was created left that role without its two
permission rows. A ``project_manager`` role created before Posts has 12 rows
where one created today has 14; the same is true of queues, counters,
calendars and dashboards for any initiative older than each of them.

Nothing was mis-authorized — an absent row reads as
``DEFAULT_PERMISSION_VALUES`` — but the stored role and the role the code
describes had drifted, which is what the settings screens read. This writes the
rows that were never written, at the values a role created today would get:
the built-in ``project_manager`` gets everything, every other role gets the
documented default (view on for the core always-on tools, off for the opt-in
ones, create off).

Existing rows are left exactly as they are, so a permission an operator turned
off stays off.

The key list is written out literally rather than derived from the ``Tool``
enum: a migration records what was true at this revision, and the next tool
must call the same helper from its own migration.

Revision ID: 20260907_0233
Revises: 20260906_0232
Create Date: 2026-09-07
"""

from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema
from app.db.role_permission_backfill import backfill_role_permissions

revision = "20260907_0233"
down_revision = "20260906_0232"
branch_labels = None
depends_on = None


# Permission key → the value a role created at this revision stores. Mirrors
# ``DEFAULT_PERMISSION_VALUES``: viewing a core (always-on) tool is on, viewing
# an opt-in tool is off, creating anything is off.
_DEFAULTS: dict[str, bool] = {
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


def upgrade() -> None:
    run_for_each_guild_schema(
        op.get_bind(), lambda: backfill_role_permissions(_DEFAULTS)
    )


def downgrade() -> None:
    # Nothing to undo: the rows written here hold the values the absent rows
    # already resolved to, so removing them would change no decision — and
    # there is no record of which rows this migration added versus which the
    # role has carried since it was created.
    pass
