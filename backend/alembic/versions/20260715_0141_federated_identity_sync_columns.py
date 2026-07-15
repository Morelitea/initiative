"""federated identity sync columns + refresh-token companion

The identity link table takes over the two remaining jobs of the legacy
``users.oidc_*`` columns: ``federated_identities.last_synced_at`` is the
due-date the background group re-sync sweeps on, and the IdP refresh token
moves into ``federated_identity_secrets`` — a 1:1 companion read and written
only by the system engine (the ``auth_provider_secrets`` pattern), since the
main table is own-row readable on the request path.

Additive only. Data is copied from ``users.oidc_*`` by the boot backfill
(``app.services.auth.oidc_backfill``), which runs on the system engine; the
legacy columns stay in place until the final cutover phase.
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260715_0141"
down_revision = "20260712_0140"
branch_labels = None
depends_on = None


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.add_column(
        "federated_identities",
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "federated_identity_secrets",
        sa.Column("identity_id", sa.Integer(), primary_key=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["identity_id"], ["federated_identities.id"], ondelete="CASCADE"
        ),
    )

    base = _platform("base")
    _run(
        [
            "ALTER TABLE public.federated_identity_secrets ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.federated_identity_secrets FORCE ROW LEVEL SECURITY",
            # Strip the schema-default DML; the token is read and rotated only by
            # the system engine (login + background group re-sync).
            f'REVOKE ALL ON TABLE public.federated_identity_secrets FROM app_guild_base, "{base}"',
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.federated_identity_secrets TO app_admin",
        ]
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.federated_identity_secrets CASCADE")
    op.drop_column("federated_identities", "last_synced_at")
