"""provider placement rules

A provider carries placement rules of its own, written by the platform, beside
the ones each community writes for itself.

* ``oidc_claim_mappings.author`` — ``community`` or ``provider``; every row
  written before this revision is a community's.
* ``oidc_claim_mappings.scope_claim`` / ``scope_value`` — on a provider rule,
  the verified claim and value that name the directory it is about, for a
  provider that signs in more than one. Both or neither, and only on a
  provider rule.
* ``oidc_claim_mappings.claim_value`` becomes nullable: a provider rule with a
  directory named and no group places everybody from that directory.
* ``guild_provider_connections.accepts_provider_placement`` — a community lets
  the platform's rules for that provider place people in it.
* ``app_settings.provider_placement_everywhere`` — the platform's rules apply
  to every community they name.

Revision ID: 20260923_0366
Revises: 20260923_0365
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260923_0366"
down_revision = "20260923_0365"
branch_labels = None
depends_on = None

_TABLE = "oidc_claim_mappings"
_AUTHOR_CK = "ck_oidc_claim_mappings_author"
_SCOPE_CK = "ck_oidc_claim_mappings_scope"
_MATCH_CK = "ck_oidc_claim_mappings_matches_something"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "author",
            sa.String(length=16),
            nullable=False,
            server_default="community",
        ),
    )
    op.add_column(_TABLE, sa.Column("scope_claim", sa.String(length=64), nullable=True))
    op.add_column(
        _TABLE, sa.Column("scope_value", sa.String(length=256), nullable=True)
    )
    op.alter_column(_TABLE, "claim_value", existing_type=sa.String(500), nullable=True)
    op.create_check_constraint(
        _AUTHOR_CK, _TABLE, "author IN ('community', 'provider')"
    )
    op.create_check_constraint(
        _SCOPE_CK,
        _TABLE,
        "(scope_claim IS NULL) = (scope_value IS NULL)"
        " AND (author = 'provider' OR scope_claim IS NULL)",
    )
    op.create_check_constraint(
        _MATCH_CK,
        _TABLE,
        "claim_value IS NOT NULL OR (author = 'provider' AND scope_claim IS NOT NULL)",
    )

    op.add_column(
        "guild_provider_connections",
        sa.Column(
            "accepts_provider_placement",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "provider_placement_everywhere",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "provider_placement_everywhere")
    op.drop_column("guild_provider_connections", "accepts_provider_placement")
    # Provider rules have no community to belong to, so they go with the
    # columns that describe them.
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(f"DELETE FROM {_TABLE} WHERE author = 'provider'")
    finally:
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.drop_constraint(_MATCH_CK, _TABLE, type_="check")
    op.drop_constraint(_SCOPE_CK, _TABLE, type_="check")
    op.drop_constraint(_AUTHOR_CK, _TABLE, type_="check")
    op.alter_column(_TABLE, "claim_value", existing_type=sa.String(500), nullable=False)
    op.drop_column(_TABLE, "scope_value")
    op.drop_column(_TABLE, "scope_claim")
    op.drop_column(_TABLE, "author")
