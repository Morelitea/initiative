"""Per-user view preferences table.

Backs the server-side migration of filter sets, sort orders, view modes,
and similar layout state that previously lived in client-side
``localStorage``. One row per ``(user_id, scope_key)``; ``value`` is an
opaque JSON blob the frontend owns.

Revision ID: 20260524_0089
Revises: 20260523_0088
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20260524_0089"
down_revision = "20260523_0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_view_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "scope_key", name="uq_user_view_preferences_user_scope"
        ),
    )
    op.create_index(
        "ix_user_view_preferences_user_id", "user_view_preferences", ["user_id"]
    )

    connection = op.get_bind()

    USER_ID = "NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer"
    IS_SUPER = "current_setting('app.is_superadmin'::text, true) = 'true'::text"

    connection.execute(text("ALTER TABLE user_view_preferences ENABLE ROW LEVEL SECURITY"))
    connection.execute(
        text("ALTER TABLE ONLY user_view_preferences FORCE ROW LEVEL SECURITY")
    )

    # Self-scope: a user only ever sees / touches their own rows. No
    # guild dimension — preferences belong to the account, not a guild.
    # Permissive (the default) because there's no other policy to be
    # narrowed; a lone RESTRICTIVE would deny everything since RLS denies
    # by default until at least one permissive policy allows the row.
    connection.execute(text(f"""
        CREATE POLICY user_view_preferences_self_scope ON user_view_preferences
            FOR ALL
            USING ((user_id = ({USER_ID})) OR ({IS_SUPER}))
            WITH CHECK ((user_id = ({USER_ID})) OR ({IS_SUPER}))
    """))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        text("DROP POLICY IF EXISTS user_view_preferences_self_scope ON user_view_preferences")
    )
    connection.execute(text("ALTER TABLE user_view_preferences DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_user_view_preferences_user_id", table_name="user_view_preferences")
    op.drop_table("user_view_preferences")
