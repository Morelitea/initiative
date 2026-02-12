"""Add RLS policies to oidc_claim_mappings

Revision ID: 20260211_0049
Revises: 20260211_0048
Create Date: 2026-02-11

Adds guild-scoped RLS policies to oidc_claim_mappings for
defense-in-depth, even though all current endpoints use
AdminSessionDep which bypasses RLS.
"""

from alembic import op

revision = "20260211_0049"
down_revision = "20260211_0048"
branch_labels = None
depends_on = None

CURRENT_GUILD_ID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"
IS_SUPERADMIN = "current_setting('app.is_superadmin', true) = 'true'"
TABLE = "oidc_claim_mappings"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY guild_isolation ON {TABLE}
        FOR ALL
        USING (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
        WITH CHECK (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS guild_isolation ON {TABLE}")
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
