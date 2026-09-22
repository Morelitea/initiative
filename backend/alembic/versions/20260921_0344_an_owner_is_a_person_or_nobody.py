"""An owner grant names a person, or there is no owner grant

Guild-content migration, one shape of row.

``resource_grants`` at ``level='owner'`` is the record of who administers a
tool, and everything that reads it — the owner check, the transfer dialog, the
unowned-content list — asks which *user* it names. The calendar backfill in
20260804_0157 wrote owner rows that name an initiative **role** instead: one per
``is_manager`` role on every default calendar it created. 20260820_0190 then
indexed "a resource has one owner", counting those rows like any other, and
kept the oldest of each pile — which on a backfilled calendar is the role row.

What that leaves is a calendar nobody owns and nobody can be given: the admin
page lists it as unowned (no user holds it, which is true), and claiming it
inserts an owner row that collides with the role's on the single-owner index,
so the claim ends in a 500 (issue #1858).

Those rows are demoted to ``write`` rather than deleted. The managers they name
keep every power the grant actually carried — a manager role reaches the
calendar through the initiative's own full-access override anyway — and the
sharing panel, which skips owner rows, now shows the role as an editor instead
of not at all. The resource is then honestly unowned and an admin can claim it.

Nothing can collide with a demoted row: ``resource_grants_unique_grantee``
predates the backfill, so each grantee already holds at most one grant per
resource.

Downgrade does not put them back: a ``write`` grant to a role is an ordinary
share, and nothing distinguishes the ones that were owner rows this morning.

Revision ID: 20260921_0344
Revises: 20260921_0343
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260921_0344"
down_revision = "20260921_0343"
branch_labels = None
depends_on = None


_DEMOTE = """
UPDATE resource_grants
   SET level = 'write'
 WHERE level = 'owner'
   AND user_id IS NULL
"""

_REMAINING = """
SELECT count(*) FROM resource_grants WHERE level = 'owner' AND user_id IS NULL
"""


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    # Writing guild content is policy-bound even for the owning role under
    # FORCE ROW LEVEL SECURITY, and the policies key on request GUCs a
    # migration has no value for; left on, this would match no rows at all.
    op.execute("ALTER TABLE resource_grants NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(sa.text(_DEMOTE))
        remaining = op.get_bind().execute(sa.text(_REMAINING)).scalar()
        if remaining:
            raise RuntimeError(
                f"{remaining} owner grants still name no user after the demotion"
            )
    finally:
        op.execute("ALTER TABLE resource_grants FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Nothing to restore: which write grants used to be owner rows is not
    # recorded anywhere, and a role holding one is the state this repairs.
    pass
