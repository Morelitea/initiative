"""what the idp said about a sign-in

A session records which providers it satisfied, but not what any of them said
about the authentication it performed. This adds that account, keyed by
provider id: ``auth_time``, ``amr`` and ``acr`` from each provider's verified
id_token.

Per provider rather than per session, because one session can satisfy several
guilds' identity sources and each guild's requirement is about its own.

Empty for every existing session, and for every password sign-in — it fills in
as those sessions renew through their providers. ``auth_sessions`` grants are
table-level, so the new column carries the table's existing ones.

Revision ID: 20260911_0260
Revises: 20260911_0259
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260911_0260"
down_revision = "20260911_0259"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column(
            "provider_auth",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("auth_sessions", "provider_auth")
