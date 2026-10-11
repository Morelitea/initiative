"""a community caps its guests

- ``guild_administration.max_guests``: how many guests a community may have
  at once. NULL is no cap and 0 takes no new guests; never negative, as for
  ``max_users``.
- The billing role reads and writes it beside the other caps.

This shipped as a second ``20261010_0498`` beside the engagement levels index.
Alembic resolves that revision to the index, so a database migrated after both
merged has the index and no column, and one migrated between the two merges
has the column and no index. Each step here is written to run on either: the
column and its check are added where they are missing, and the index of
``20261010_0498`` is created in every guild schema where it is missing.

Revision ID: 20261010_0499
Revises: 20261010_0498
Create Date: 2026-10-10
"""

from alembic import op

from app.core.config import settings
from app.db.guild_migrations import apply_to_all_guild_schemas

revision = "20261010_0499"
down_revision = "20261010_0498"
branch_labels = None
depends_on = None

_CHECK = "ck_guild_administration_max_guests_nonnegative"
_LEVELS_INDEX = "ix_engagement_levels_level"


def _billing_role() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.guild_administration "
        "ADD COLUMN IF NOT EXISTS max_guests integer"
    )
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = '{_CHECK}'
                  AND conrelid = 'public.guild_administration'::regclass
            ) THEN
                ALTER TABLE public.guild_administration ADD CONSTRAINT {_CHECK}
                    CHECK (max_guests IS NULL OR max_guests >= 0);
            END IF;
        END $$;
        """
    )
    op.execute(
        "GRANT SELECT (max_guests), UPDATE (max_guests) "
        f'ON public.guild_administration TO "{_billing_role()}"'
    )
    apply_to_all_guild_schemas(
        op.get_bind(),
        f"CREATE INDEX IF NOT EXISTS {_LEVELS_INDEX} "
        "ON engagement_levels (level, entity_type, entity_id)",
    )


def downgrade() -> None:
    # The index is 20261010_0498's, and stays for its downgrade to remove.
    op.execute(
        "REVOKE SELECT (max_guests), UPDATE (max_guests) "
        f'ON public.guild_administration FROM "{_billing_role()}"'
    )
    op.execute(f"ALTER TABLE public.guild_administration DROP CONSTRAINT {_CHECK}")
    op.execute("ALTER TABLE public.guild_administration DROP COLUMN max_guests")
