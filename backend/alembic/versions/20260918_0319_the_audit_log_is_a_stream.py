"""the audit log is a stream

The record of what was done is one JSON line per event on the process's
standard output, written after the action commits, and kept, queried and
retained by whatever ships the deployment's logs. The application holds no
copy: the ``audit_events`` table (migration 0204) and the board that read it
are removed.

Revision ID: 20260918_0319
Revises: 20260918_0318
Create Date: 2026-09-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20260918_0319"
down_revision = "20260918_0318"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.audit_events")


def downgrade() -> None:
    # The table as migrations 0204 and 0259 left it, empty: the rows it held
    # were never the only copy of anything after this revision.
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "event_uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("guild_id", sa.Integer(), nullable=True),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("tier", sa.SmallInteger(), nullable=False),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index(
        "ix_audit_events_actor", "audit_events", ["actor_user_id", "occurred_at"]
    )
    op.create_index(
        "ix_audit_events_target_user",
        "audit_events",
        ["target_user_id", "occurred_at"],
    )
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for statement in (
        f'REVOKE ALL ON TABLE public.audit_events FROM "{base}"',
        "REVOKE ALL ON TABLE public.audit_events FROM app_guild_base",
        "REVOKE ALL ON TABLE public.audit_events FROM app_user",
        f'REVOKE ALL ON SEQUENCE public.audit_events_id_seq FROM "{base}"',
        "REVOKE ALL ON SEQUENCE public.audit_events_id_seq FROM app_guild_base",
        "REVOKE ALL ON SEQUENCE public.audit_events_id_seq FROM app_user",
        "GRANT SELECT, INSERT ON TABLE public.audit_events TO app_admin",
        "GRANT USAGE ON SEQUENCE public.audit_events_id_seq TO app_admin",
        "ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.audit_events FORCE ROW LEVEL SECURITY",
    ):
        op.execute(statement)
