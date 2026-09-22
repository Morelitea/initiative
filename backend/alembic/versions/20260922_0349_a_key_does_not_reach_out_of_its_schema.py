"""a key does not reach out of its schema

Twenty-three foreign keys inside ``guild_template`` pointed at
``public.users``. No guild ever had one: provisioning renders a guild schema
from the live template and copies intra-schema keys only (``app.db.guild_ddl``
``render_guild_schema_ddl``), so ``guild_1``, ``guild_2`` and every schema
after them were built without them. The template was the only schema that
carried them, and nothing is stored there.

So the delete rules they declared have never run anywhere. Account erasure
already deletes the rows they name — a member's AI keys and connection
preference, their project order, their recents — and says in
``app.services.platform.users`` that it must, because the CASCADE never fires.
An ``ON DELETE SET NULL`` on ``created_by`` was the same shape of nothing: an
author id outlives the account it names, which is what keeps one departed
author distinguishable from another.

This is the treatment 20260921_0347 gave the eighteen keys to
``public.guilds``, applied to the ones that point at ``public.users``. After
it, no table below the guild boundary references anything above it, and the
template's shape is the shape a guild is actually provisioned with.

The columns stay, and so does ``foreign_key="users.id"`` on the models: that
is SQLAlchemy metadata the app reads to derive a column's control and to gate
search, never a constraint the database held here.

Guild content, so this walks ``guild_template`` and every ``guild_<id>``. The
drop is ``IF EXISTS`` because the guild schemas have nothing to drop, and the
downgrade restores the keys to ``guild_template`` alone, where they were.

Revision ID: 20260922_0349
Revises: 20260922_0348
Create Date: 2026-09-22
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20260922_0349"
down_revision = "20260922_0348"
branch_labels = None
depends_on = None


#: Foreign keys to ``public.users``. Template-only: provisioning never copied
#: them into a guild schema, so the downgrade restores them there alone.
_FKS: tuple[tuple[str, str, str], ...] = (
    (
        "calendars",
        "calendars_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "dashboards",
        "dashboards_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "export_jobs",
        "export_jobs_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "galleries",
        "galleries_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "gallery_image_versions",
        "gallery_image_versions_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "gallery_images",
        "gallery_images_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "guild_ai_connections",
        "guild_ai_connections_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL",
    ),
    (
        "guild_ai_member_keys",
        "guild_ai_member_keys_user_id_fkey",
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE",
    ),
    (
        "guild_ai_member_prefs",
        "guild_ai_member_prefs_user_id_fkey",
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE",
    ),
    (
        "guild_app_user_connections",
        "guild_app_user_connections_blocked_by_id_fkey",
        "FOREIGN KEY (blocked_by_id) REFERENCES users(id) ON DELETE SET NULL",
    ),
    (
        "guild_app_user_connections",
        "guild_app_user_connections_user_id_fkey",
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE",
    ),
    (
        "guild_app_user_delegations",
        "guild_app_user_delegations_revoked_by_id_fkey",
        "FOREIGN KEY (revoked_by_id) REFERENCES users(id) ON DELETE SET NULL",
    ),
    (
        "guild_app_user_delegations",
        "guild_app_user_delegations_user_id_fkey",
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE",
    ),
    (
        "guild_apps",
        "guild_apps_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "import_jobs",
        "import_jobs_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "initiative_join_requests",
        "initiative_join_requests_resolved_by_fkey",
        "FOREIGN KEY (resolved_by) REFERENCES users(id) ON DELETE SET NULL",
    ),
    (
        "initiative_join_requests",
        "initiative_join_requests_user_id_fkey",
        "FOREIGN KEY (user_id) REFERENCES users(id)",
    ),
    (
        "post_poll_options",
        "post_poll_options_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "post_polls",
        "post_polls_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "posts",
        "posts_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "project_filter_presets",
        "project_filter_presets_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "wiki_pages",
        "wiki_pages_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
    (
        "wikis",
        "wikis_created_by_fkey",
        "FOREIGN KEY (created_by) REFERENCES users(id)",
    ),
)


def upgrade() -> None:
    connection = op.get_bind()
    for schema in guild_schema_names(connection):
        connection.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        for table, name, _ in _FKS:
            connection.execute(
                sa.text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"')
            )
    connection.execute(sa.text("SELECT set_config('search_path', 'public', true)"))


def downgrade() -> None:
    connection = op.get_bind()
    for schema in guild_schema_names(connection):
        if schema != "guild_template":
            continue
        connection.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        for table, name, definition in _FKS:
            connection.execute(
                sa.text(
                    f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint"
                    f" WHERE conname = '{name}'"
                    f" AND connamespace = current_schema()::regnamespace)"
                    f' THEN ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition};'
                    f" END IF; END $$;"
                )
            )
    connection.execute(sa.text("SELECT set_config('search_path', 'public', true)"))
