"""Create webhook_subscriptions for outbound dispatch to initiative-auto.

When a workflow is created on the auto side, auto registers a
subscription here naming a target URL and the events it cares about
(``task.created``, ``comment.created``, etc). On every relevant write
in this service, the dispatcher looks up matching active subscriptions
and POSTs an HMAC-signed envelope.

Tenant isolation: standard guild_isolation RLS policy mirroring the
other guild-scoped tables. ``hmac_secret`` is opaque-random per
subscription — the receiving service stores it independently and
verifies against it on every inbound delivery.

Revision ID: 20260501_0082
Revises: 20260501_0081
Create Date: 2026-05-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260501_0082"
down_revision: Union[str, None] = "20260501_0081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IS_SUPER = "current_setting('app.is_superadmin', true) = 'true'"


def upgrade() -> None:
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "guild_id",
            sa.Integer(),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Optional initiative scope. When set, only events within that
        # initiative trigger this subscription. NULL = guild-wide.
        sa.Column(
            "initiative_id",
            sa.Integer(),
            sa.ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # The auto-side workflow this subscription is for. Stored as a
        # plain int because there's no FK across services. Used by the
        # dispatcher's payload so the receiver can route the event back
        # to the right workflow without a second lookup round-trip.
        sa.Column("workflow_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_url", sa.String(length=2048), nullable=False),
        # Random per-subscription secret. Initialized at creation time
        # and never returned to clients on subsequent reads — only the
        # one-time create response carries it.
        sa.Column("hmac_secret", sa.String(length=128), nullable=False),
        # Postgres array — simple, queryable, no extra table for the
        # 1-to-many event_types relation.
        sa.Column(
            "event_types",
            sa.dialects.postgresql.ARRAY(sa.String(length=100)),
            nullable=False,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_webhook_subscriptions_guild_id",
        "webhook_subscriptions",
        ["guild_id"],
    )
    # Hot path for the dispatcher: "find all active subscriptions for
    # guild X (and optionally initiative Y) that include event type Z".
    # The partial index narrows to active rows only.
    op.create_index(
        "ix_webhook_subscriptions_dispatch",
        "webhook_subscriptions",
        ["guild_id", "initiative_id"],
        postgresql_where=sa.text("active = true"),
    )

    # ── RLS: guild isolation ──────────────────────────────────────────
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE webhook_subscriptions ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE webhook_subscriptions FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text(f"""
        CREATE POLICY guild_isolation ON webhook_subscriptions
        FOR ALL
        USING (
            guild_id = current_setting('app.current_guild_id', true)::int
            OR {IS_SUPER}
        )
        WITH CHECK (
            guild_id = current_setting('app.current_guild_id', true)::int
            OR {IS_SUPER}
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP POLICY IF EXISTS guild_isolation ON webhook_subscriptions"))
    conn.execute(sa.text("ALTER TABLE webhook_subscriptions DISABLE ROW LEVEL SECURITY"))
    op.drop_index(
        "ix_webhook_subscriptions_dispatch", table_name="webhook_subscriptions"
    )
    op.drop_index(
        "ix_webhook_subscriptions_guild_id", table_name="webhook_subscriptions"
    )
    op.drop_table("webhook_subscriptions")
