"""Drop the initiative/role FKs on oidc_claim_mappings.

Under schema-per-guild, ``initiatives`` and ``initiative_roles`` move into
per-guild schemas, so a cross-schema foreign key from the shared (public)
``oidc_claim_mappings`` table can no longer hold. Demote ``initiative_id`` and
``initiative_role_id`` to plain columns; integrity is enforced in app (the
create endpoint validates the initiative/role and guild, and oidc_sync skips
references that no longer resolve). The ``guild_id`` FK stays (public -> public).

Revision ID: 20260609_0099
Revises: 20260608_0098
Create Date: 2026-06-09
"""

from alembic import op

revision = "20260609_0099"
down_revision = "20260608_0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "oidc_claim_mappings_initiative_id_fkey", "oidc_claim_mappings", type_="foreignkey"
    )
    op.drop_constraint(
        "oidc_claim_mappings_initiative_role_id_fkey",
        "oidc_claim_mappings",
        type_="foreignkey",
    )


def downgrade() -> None:
    op.create_foreign_key(
        "oidc_claim_mappings_initiative_id_fkey",
        "oidc_claim_mappings",
        "initiatives",
        ["initiative_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "oidc_claim_mappings_initiative_role_id_fkey",
        "oidc_claim_mappings",
        "initiative_roles",
        ["initiative_role_id"],
        ["id"],
        ondelete="SET NULL",
    )
