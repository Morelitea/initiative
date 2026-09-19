"""notification email waits its turn

Three changes, one subject: when a notification email goes out.

``email_outbox`` is where every notification email is written instead of being
sent inside the request that caused it. The request appends and never reads;
the worker owns the rest. Grants say exactly that, and there is no row policy —
the request path holds INSERT and nothing else, so there is nothing for a
policy to narrow.

``users.last_active_at`` records that somebody was at their keyboard recently,
which is what lets delivery hold off rather than telling them something they
are already reading in the app. One mutable stamp, written on the system
engine, never serialized to any response.

``users.overdue_notification_time`` moves into the settings document as
``email.at``, where it is one clock for the scheduled mail and the overdue
reminder together instead of a second source of truth for the same question.

Revision ID: 20260919_0320
Revises: 20260918_0319
Create Date: 2026-09-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260919_0320"
down_revision = "20260918_0319"
branch_labels = None
depends_on = None


#: The base roles every request-path role inherits public access from. Schema
#: default privileges hand a new table full DML to both, so the narrowing below
#: is an explicit REVOKE rather than an omission.
_BASE_ROLES = ("app_guild_base", "platform_base")


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "notification_id",
            sa.Integer(),
            sa.ForeignKey("notifications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column(
            "guild_id",
            sa.Integer(),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("link_label", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deliver_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_email_outbox_due",
        "email_outbox",
        ["deliver_after"],
        postgresql_where=sa.text("sent_at IS NULL AND failed_at IS NULL"),
    )
    op.create_index("ix_email_outbox_user", "email_outbox", ["user_id"])

    # The request path appends a row for its recipient and never looks at one
    # again, so INSERT is the whole of what it holds.
    for role in _BASE_ROLES:
        op.execute(f'REVOKE ALL ON TABLE public.email_outbox FROM "{role}"')
        op.execute(f'GRANT INSERT ON TABLE public.email_outbox TO "{role}"')
        op.execute(
            f'GRANT USAGE, SELECT ON SEQUENCE public.email_outbox_id_seq TO "{role}"'
        )
    op.execute("REVOKE ALL ON TABLE public.email_outbox FROM app_user")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.email_outbox TO app_admin"
    )
    op.execute(
        "GRANT USAGE, SELECT ON SEQUENCE public.email_outbox_id_seq TO app_admin"
    )

    # --- where somebody was last seen ---------------------------------------
    op.add_column(
        "users",
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The request-path floors hold a column-scoped UPDATE covering every
    # ``users`` column but ``role`` (migration 0144), and a column-scoped grant
    # names its columns — so a new one joins it explicitly or the floors drift
    # from the rule. This stamp is written on the system engine either way.
    for role in (f"{settings.PLATFORM_ROLE_PREFIX}platform_base", "app_user"):
        op.execute(f'GRANT UPDATE (last_active_at) ON TABLE public.users TO "{role}"')

    # --- one clock ----------------------------------------------------------
    # The daily reminder time becomes ``email.at`` in the settings document,
    # which is also the clock the scheduled mail goes out on. Only accounts
    # that had chosen something other than the default carry anything over:
    # the default is the default at both ends, so writing it would be storing
    # an exception that is not one.
    #
    # The settings table binds its owner to its policies, and those read
    # request values a migration does not have — so the write is lifted for the
    # duration and restored in the same transaction, with the row count
    # asserted against what was counted beforehand.
    conn = op.get_bind()
    expected = conn.execute(
        sa.text(
            "SELECT count(*) FROM public.users "
            "WHERE overdue_notification_time IS NOT NULL "
            "  AND overdue_notification_time <> '21:00'"
        )
    ).scalar_one()
    op.execute("ALTER TABLE public.user_notification_prefs NO FORCE ROW LEVEL SECURITY")
    try:
        moved = conn.execute(
            sa.text(
                "INSERT INTO public.user_notification_prefs "
                "    (user_id, prefs, created_at, updated_at) "
                "SELECT u.id, "
                "       jsonb_build_object('email', jsonb_build_object("
                "           'at', u.overdue_notification_time)), "
                "       now(), now() "
                "  FROM public.users u "
                " WHERE u.overdue_notification_time IS NOT NULL "
                "   AND u.overdue_notification_time <> '21:00' "
                "ON CONFLICT (user_id) DO UPDATE "
                "   SET prefs = public.user_notification_prefs.prefs "
                "       || jsonb_build_object('email', "
                "            coalesce(public.user_notification_prefs.prefs->'email', "
                "                     '{}'::jsonb) "
                "            || excluded.prefs->'email'), "
                "       updated_at = now()"
            )
        ).rowcount
    finally:
        op.execute(
            "ALTER TABLE public.user_notification_prefs FORCE ROW LEVEL SECURITY"
        )
    assert moved == expected, (
        f"carried {moved} reminder time(s) over, expected {expected}"
    )

    op.drop_column("users", "overdue_notification_time")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "overdue_notification_time",
            sa.String(5),
            nullable=False,
            server_default="21:00",
        ),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE public.users u "
            "   SET overdue_notification_time = p.prefs->'email'->>'at' "
            "  FROM public.user_notification_prefs p "
            " WHERE p.user_id = u.id "
            "   AND p.prefs->'email'->>'at' IS NOT NULL"
        )
    )
    op.drop_column("users", "last_active_at")
    op.drop_index("ix_email_outbox_user", table_name="email_outbox")
    op.drop_index("ix_email_outbox_due", table_name="email_outbox")
    op.drop_table("email_outbox")
