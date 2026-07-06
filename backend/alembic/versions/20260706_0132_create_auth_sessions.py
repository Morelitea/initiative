"""create auth_sessions (session / rotating-refresh store)

Phase-0 foundation for the login rewrite (history/auth-detailed-design.md §2.3,
§3): the server-side session that backs the stateless access JWT and makes the
refresh side revocable. Additive only — nothing reads or writes it yet.

uuid PK (the JWT ``sid``): non-enumerable, no hot sequence, and one row per login
so a monotonic int would leak the login count. Because it is a uuid, there is no
``_id_seq`` to grant.

app_admin-only. Session validation is a pre-auth lookup by refresh-token hash (the
user is unknown until it resolves), so it can't run under own-row RLS — it runs on
the system engine, like access_grants. The public schema default-grants
platform_base + app_guild_base full DML on every new table, so we REVOKE both:
the request path can't touch sessions (esp. the refresh-token hash) at all.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20260706_0132"
down_revision = "20260705_0131"
branch_labels = None
depends_on = None


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("refresh_token_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "satisfied_providers",
            sa.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "amr", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("device_name", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "refresh_token_hash", name="uq_auth_sessions_refresh_token_hash"
        ),
        # A session can't be its own rotation parent (a self-loop would hang the
        # theft-detection chain walk); longer cycles can't form as the chain is
        # strictly backward in time.
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name="ck_auth_sessions_parent_not_self",
        ),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    base = _platform("base")
    _run(
        [
            "ALTER TABLE public.auth_sessions ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.auth_sessions FORCE ROW LEVEL SECURITY",
            # Strip the schema-default DML: all session ops (validate/rotate/revoke,
            # and "list my sessions") run on the system engine; the request path
            # never touches sessions, so the refresh-token hash can't leak.
            f'REVOKE ALL ON TABLE public.auth_sessions FROM app_guild_base, "{base}"',
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.auth_sessions TO app_admin",
        ]
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.auth_sessions CASCADE")
