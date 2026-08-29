"""What was done, by whom, to what — kept after everyone involved is gone.

The first slice of ``history/pam-audit-sink-design.md``: the table and its
grants, built to that design's shape so the privileged-access family, the
immutable-storage sink and the shipper land on top of it later without
reworking what is written now.

Append-only in the grants, not by convention: nobody holds UPDATE or DELETE,
the system engine included. The request-path floors hold nothing at all — the
log is written and read on the system engine, behind the ``audit.read``
capability — so the schema default privileges that grant every new public
table to the base roles are revoked first.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20260829_0204"
down_revision = "20260829_0203"
branch_labels = None
depends_on = None


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "event_uuid",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        # Plain integers throughout: an audit row is a point-in-time fact that
        # has to outlive the account and the guild it names, so there is no
        # foreign key to cascade or null it out on erasure.
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
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

    base = _platform_base()
    statements = [
        # Schema default privileges hand every new public table to the base
        # roles; this table belongs to neither.
        f'REVOKE ALL ON TABLE public.audit_events FROM "{base}"',
        "REVOKE ALL ON TABLE public.audit_events FROM app_guild_base",
        "REVOKE ALL ON TABLE public.audit_events FROM app_user",
        f'REVOKE ALL ON SEQUENCE public.audit_events_id_seq FROM "{base}"',
        "REVOKE ALL ON SEQUENCE public.audit_events_id_seq FROM app_guild_base",
        "REVOKE ALL ON SEQUENCE public.audit_events_id_seq FROM app_user",
        # The system engine writes the record and the board reads it. No
        # UPDATE, no DELETE, to anyone.
        "GRANT SELECT, INSERT ON TABLE public.audit_events TO app_admin",
        "GRANT USAGE ON SEQUENCE public.audit_events_id_seq TO app_admin",
        "ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.audit_events FORCE ROW LEVEL SECURITY",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    op.drop_index("ix_audit_events_target_user", table_name="audit_events")
    op.drop_index("ix_audit_events_actor", table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
