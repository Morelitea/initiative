"""Ownership lives in resource_grants, and names one person or nobody

Guild-content migration, two halves of one idea.

A project's owner was recorded twice: in ``projects.owner_id`` and in its
``resource_grants`` row at ``level='owner'``. Only the grant is consulted when
access is decided, so the column was a second copy that could drift from the
answer — it goes.

Dropping it also lets ownership be *absent*. A member leaving a guild now has
their owner grants released rather than handed to someone else, and "no owner"
is simply no owner row, which a NOT NULL column could not express.

The other tool tables never had an owner column; what they carry is
``created_by_id``, the author, which is a different fact and does not move.

The partial unique index then says the other half: a resource has one owner or
none. Nothing enforced that before, and the re-homing paths removed alongside
this could upgrade several initiative managers to owner at once, leaving rows
where "the owner" was three people. Those pile-ups are collapsed to the oldest
owner grant — the one that was there before anything was upgraded on top of it.

Revision ID: 20260820_0190
Revises: 20260820_0189
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260820_0190"
down_revision = "20260820_0189"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_resource_grants_single_owner"

_DEDUPE_OWNERS = """
DELETE FROM resource_grants g
 WHERE g.level = 'owner'
   AND g.id > (
        SELECT min(keep.id)
          FROM resource_grants keep
         WHERE keep.level = 'owner'
           AND keep.resource_type = g.resource_type
           AND keep.resource_id = g.resource_id
   )
"""

_REMAINING_DUPES = """
SELECT count(*) FROM (
    SELECT 1
      FROM resource_grants
     WHERE level = 'owner'
     GROUP BY resource_type, resource_id
    HAVING count(*) > 1
) dupes
"""

# Rebuild the dropped column from the grants, which are the record of ownership.
_RESTORE_FROM_GRANTS = """
UPDATE projects p
   SET owner_id = g.user_id
  FROM resource_grants g
 WHERE g.resource_type = 'project'
   AND g.resource_id = p.id
   AND g.level = 'owner'
   AND g.user_id IS NOT NULL
"""

# Anything still unowned has no owner to restore. Adopt it to the guild's
# longest-standing admin so the column can go back to NOT NULL.
_ADOPT_UNOWNED = """
UPDATE projects p
   SET owner_id = (
        SELECT gm.user_id
          FROM public.guild_memberships gm
         WHERE gm.guild_id = p.guild_id
           AND gm.role = 'admin'
         ORDER BY gm.created_at ASC, gm.user_id ASC
         LIMIT 1
   )
 WHERE p.owner_id IS NULL
"""

_REMAINING_UNOWNED = "SELECT count(*) FROM projects WHERE owner_id IS NULL"


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    # Deleting guild content is policy-bound even for the owning role under
    # FORCE ROW LEVEL SECURITY; left on, the dedupe would match no rows and the
    # index would then fail on the duplicates it was meant to remove.
    op.execute("ALTER TABLE resource_grants NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(sa.text(_DEDUPE_OWNERS))
        remaining = op.get_bind().execute(sa.text(_REMAINING_DUPES)).scalar()
        if remaining:
            raise RuntimeError(
                f"{remaining} resources still hold more than one owner grant"
            )
    finally:
        op.execute("ALTER TABLE resource_grants FORCE ROW LEVEL SECURITY")

    op.create_index(
        INDEX_NAME,
        "resource_grants",
        ["resource_type", "resource_id"],
        unique=True,
        postgresql_where=sa.text("level = 'owner'"),
    )

    op.drop_column("projects", "owner_id")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.add_column("projects", sa.Column("owner_id", sa.Integer(), nullable=True))

    # Same reason as the dedupe above: the backfill reads and writes guild
    # content, so FORCE would filter it to nothing and the NOT NULL would fail.
    op.execute("ALTER TABLE projects NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE resource_grants NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(sa.text(_RESTORE_FROM_GRANTS))
        op.execute(sa.text(_ADOPT_UNOWNED))
        remaining = op.get_bind().execute(sa.text(_REMAINING_UNOWNED)).scalar()
        if remaining:
            raise RuntimeError(
                f"{remaining} projects still have no owner_id after backfill"
            )
    finally:
        op.execute("ALTER TABLE resource_grants FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE projects FORCE ROW LEVEL SECURITY")

    op.alter_column("projects", "owner_id", existing_type=sa.Integer(), nullable=False)

    op.drop_index(INDEX_NAME, table_name="resource_grants")
