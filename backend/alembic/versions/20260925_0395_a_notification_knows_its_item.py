"""a notification knows its item

A notification line records where it sits all the way down, so unread activity
can be followed from the navigation to the item and opening the item marks it
read:

- ``notifications.resource_id`` — the tool row the item is in (the project of a
  task, the calendar of an event, the wiki of a page).
- ``notifications.subject_type`` / ``subject_id`` — the item itself.
- The unread-place index carries both, so the question stays one index-only
  scan.

Unread lines already written are given their item from the address they open
(``/go/{kind}/{id}``), which every content notification stores; a line about a
tool's own row is also its ``resource_id``.

``email_outbox.security`` marks an account-security letter: sent at once, on
its own, to every proven address, whatever the account's notification settings.

Revision ID: 20260925_0395
Revises: 20260925_0394
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0395"
down_revision = "20260925_0394"
branch_labels = None
depends_on = None

#: The tools' own kinds as of this revision.
_TOOL_KINDS = (
    "project",
    "document",
    "queue",
    "counter_group",
    "calendar",
    "dashboard",
    "post",
    "gallery",
    "wiki",
)

_BACKFILL = """
UPDATE public.notifications AS n
SET subject_type = CASE m.parts[1]
        WHEN 'event' THEN 'calendar_event'
        ELSE replace(m.parts[1], '-', '_')
    END,
    subject_id = m.parts[2]::integer
FROM (
    SELECT id,
           regexp_match(data->>'target_path', '^/go/([a-z-]+)/([0-9]+)$') AS parts
    FROM public.notifications
    WHERE read_at IS NULL
) AS m
WHERE n.id = m.id AND m.parts IS NOT NULL
"""


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("resource_id", sa.Integer(), nullable=True),
        schema="public",
    )
    op.add_column(
        "notifications",
        sa.Column("subject_type", sa.String(32), nullable=True),
        schema="public",
    )
    op.add_column(
        "notifications",
        sa.Column("subject_id", sa.Integer(), nullable=True),
        schema="public",
    )

    bind = op.get_bind()
    bind.execute(
        sa.text("ALTER TABLE public.notifications NO FORCE ROW LEVEL SECURITY")
    )
    try:
        bind.execute(sa.text(_BACKFILL))
        bind.execute(
            sa.text(
                "UPDATE public.notifications SET resource_id = subject_id "
                "WHERE read_at IS NULL AND subject_type = ANY(:kinds)"
            ).bindparams(kinds=list(_TOOL_KINDS))
        )
    finally:
        bind.execute(
            sa.text("ALTER TABLE public.notifications FORCE ROW LEVEL SECURITY")
        )

    op.drop_index(
        "ix_notifications_unread_place", table_name="notifications", schema="public"
    )
    op.create_index(
        "ix_notifications_unread_place",
        "notifications",
        [
            "user_id",
            "guild_id",
            "initiative_id",
            "tool",
            "resource_id",
            "subject_type",
            "subject_id",
        ],
        unique=False,
        schema="public",
        postgresql_where=sa.text("read_at IS NULL"),
    )

    op.add_column(
        "email_outbox",
        sa.Column(
            "security", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("email_outbox", "security", schema="public")
    op.drop_index(
        "ix_notifications_unread_place", table_name="notifications", schema="public"
    )
    op.create_index(
        "ix_notifications_unread_place",
        "notifications",
        ["user_id", "guild_id", "initiative_id", "tool"],
        unique=False,
        schema="public",
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.drop_column("notifications", "subject_id", schema="public")
    op.drop_column("notifications", "subject_type", schema="public")
    op.drop_column("notifications", "resource_id", schema="public")
