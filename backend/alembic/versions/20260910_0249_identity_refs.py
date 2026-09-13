"""What an outside party calls a user or a guild.

The first slice of ``history/opaque-identity-design.md``: the table and its
grants. The billing handoffs and the app-platform consolidation land on top of
it without reworking what is written here.

Written and read on the system engine only, so the schema default privileges
that hand every new public table to the base roles are revoked first.
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260910_0249"
down_revision = "20260909_0248"
branch_labels = None
depends_on = None


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    op.create_table(
        "identity_refs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ref", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(16), nullable=False),
        # Plain integer, no foreign key: erasure husks the row it names rather
        # than removing it, and these rows are dropped by that same path.
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("ref", name="identity_refs_unique_ref"),
    )
    # One live reference per entity per purpose; retired rows sit beside the
    # value that replaced them until their grace window closes.
    op.create_index(
        "ix_identity_refs_live",
        "identity_refs",
        ["entity_type", "entity_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )
    op.create_index("ix_identity_refs_retired_at", "identity_refs", ["retired_at"])

    # Nothing to backfill: references are minted on first use, so every
    # existing user and guild acquires one when a purpose first asks.
    base = _platform_base()
    statements = [
        f'REVOKE ALL ON TABLE public.identity_refs FROM "{base}"',
        "REVOKE ALL ON TABLE public.identity_refs FROM app_guild_base",
        "REVOKE ALL ON TABLE public.identity_refs FROM app_user",
        f'REVOKE ALL ON SEQUENCE public.identity_refs_id_seq FROM "{base}"',
        "REVOKE ALL ON SEQUENCE public.identity_refs_id_seq FROM app_guild_base",
        "REVOKE ALL ON SEQUENCE public.identity_refs_id_seq FROM app_user",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.identity_refs TO app_admin",
        "GRANT USAGE ON SEQUENCE public.identity_refs_id_seq TO app_admin",
        "ALTER TABLE public.identity_refs ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.identity_refs FORCE ROW LEVEL SECURITY",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    op.drop_index("ix_identity_refs_retired_at", table_name="identity_refs")
    op.drop_index("ix_identity_refs_live", table_name="identity_refs")
    op.drop_table("identity_refs")
