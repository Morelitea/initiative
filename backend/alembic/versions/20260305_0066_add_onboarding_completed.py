"""Add onboarding_completed and pm_tour_completed columns to users table.

New users default to false (will see the tours).
Existing users are set to true so they don't see them unexpectedly.

Revision ID: 20260305_0066
Revises: 20260301_0065
Create Date: 2026-03-05
"""

from alembic import op
import sqlalchemy as sa

revision = "20260305_0066"
down_revision = "20260301_0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use raw SQL with IF NOT EXISTS so re-running after a partial apply is safe.
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN NOT NULL DEFAULT false
    """)
    # Mark existing users as having completed onboarding so only
    # newly registered users see the tour.
    op.execute("UPDATE users SET onboarding_completed = true WHERE onboarding_completed = false")

    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS pm_tour_completed BOOLEAN NOT NULL DEFAULT false
    """)
    # Mark existing users as having completed the PM tour so only
    # newly promoted PMs see it.
    op.execute("UPDATE users SET pm_tour_completed = true WHERE pm_tour_completed = false")

    op.execute("""
        ALTER TABLE app_settings
        ADD COLUMN IF NOT EXISTS onboarding_tour_enabled BOOLEAN NOT NULL DEFAULT true
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE app_settings DROP COLUMN IF EXISTS onboarding_tour_enabled")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS pm_tour_completed")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS onboarding_completed")
