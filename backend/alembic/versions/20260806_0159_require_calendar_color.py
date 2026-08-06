"""require calendar color

A calendar always has a color: existing colorless rows get the app default,
then the column goes NOT NULL with a server default. Rendering reads the
stored value everywhere, so grid and picker can never disagree again.

The backfill UPDATE runs as the table owner with FORCE RLS toggled off around
it (FORCE would leave the owner policy-bound and silently skip rows) and
asserts no colorless rows remain per schema.
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema
from app.models.tenant.calendar import DEFAULT_CALENDAR_COLOR

revision = "20260806_0159"
down_revision = "20260806_0158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.execute("ALTER TABLE calendars NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            sa.text(
                "UPDATE calendars SET color = :color WHERE color IS NULL"
            ).bindparams(color=DEFAULT_CALENDAR_COLOR)
        )
        remaining = (
            op.get_bind()
            .execute(sa.text("SELECT count(*) FROM calendars WHERE color IS NULL"))
            .scalar()
        )
        if remaining:
            raise RuntimeError(f"{remaining} calendars still have no color")
    finally:
        op.execute("ALTER TABLE calendars FORCE ROW LEVEL SECURITY")
    op.execute(
        f"ALTER TABLE calendars ALTER COLUMN color SET DEFAULT '{DEFAULT_CALENDAR_COLOR}'"
    )
    op.execute("ALTER TABLE calendars ALTER COLUMN color SET NOT NULL")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.execute("ALTER TABLE calendars ALTER COLUMN color DROP NOT NULL")
    op.execute("ALTER TABLE calendars ALTER COLUMN color DROP DEFAULT")
