"""A key you sign in with

``user_passkeys`` — one WebAuthn credential an account may sign in with.

``app_admin``-only, the shape the second-factor tables use: RLS enabled and
forced with no policies at all, which is the strictest state a table has. A
policy opens access; with none, every role that is not BYPASSRLS is denied,
and the schema's default grants to ``platform_base``/``app_guild_base`` come
straight back off.

Nothing reads this yet. The routes arrive with enrolment, and the
``login_method`` value arrives with the checkbox that offers it — the ordering
the second factor used, so a box never appears for something nothing can do.

Revision ID: 20260917_0298
Revises: 20260917_0297
Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.core.config import settings

revision = "20260917_0298"
down_revision = "20260917_0297"
branch_labels = None
depends_on = None

TABLE = "user_passkeys"


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("rp_id", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "transports",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("aaguid", sa.Text(), nullable=True),
        sa.Column(
            "user_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("backed_up", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    # An assertion arrives naming the credential before any account is known,
    # so this is the lookup key and it is unique across the deployment.
    op.create_index(
        "ix_user_passkeys_credential_id", TABLE, ["credential_id"], unique=True
    )
    op.create_index("ix_user_passkeys_user_id", TABLE, ["user_id"])

    if not _is_postgres():
        return

    base = _platform("base")
    for statement in (
        f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
        # The public schema default-grants platform_base + app_guild_base full
        # DML on every new table; both come straight back off.
        f'REVOKE ALL ON TABLE public.{TABLE} FROM app_guild_base, "{base}"',
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{TABLE} TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    if _is_postgres():
        op.execute(f"ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_user_passkeys_user_id", table_name=TABLE)
    op.drop_index("ix_user_passkeys_credential_id", table_name=TABLE)
    op.drop_table(TABLE)
