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

Two things stand between a migration and that one UPDATE, and both are lifted
for the statement and put back after it:

* ``FORCE ROW LEVEL SECURITY`` binds the owning role too, and the policies key
  on request GUCs a migration has no value for — left on, the UPDATE would match
  no rows and report success.
* The lifecycle freeze (``app.db.frozen``) refuses an edit to a grant whose
  resource is archived, in the trash, or gone — and a grant on a calendar that
  was later purged is still a grant. The first deployment to run this held one
  such row and the whole upgrade failed on it. The freeze triggers on this one
  table are switched off by name for the statement, exactly as 20260911_0255
  does; the capture and authorship triggers keep running.

There is deliberately no ``try``/``finally`` around the work: every step is
transactional, so a failure rolls all of it back — and a ``finally`` that ran
DDL inside an aborted transaction would raise its own error in place of the one
worth reading, which is how this migration's first failure was reported.

Downgrade does not put them back: a ``write`` grant to a role is an ordinary
share, and nothing distinguishes the ones that were owner rows this morning.

Revision ID: 20260921_0344
Revises: 20260921_0343
Create Date: 2026-09-21
"""

from sqlalchemy import text
from sqlalchemy.engine import Connection

from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260921_0344"
down_revision = "20260921_0343"
branch_labels = None
depends_on = None


#: The freeze triggers on ``resource_grants`` in the routed schema, switched
#: off and back on around the statement. By name, from the catalog: a fresh
#: install reaches this line before provisioning has rendered any trigger at
#: all, and finds nothing to switch. Never ``DISABLE TRIGGER USER`` — the same
#: table carries the capture and authorship triggers, and those must keep
#: running.
_SET_FREEZE_TRIGGERS = """
DO $$
DECLARE row record;
BEGIN
    FOR row IN
        SELECT tg.tgname AS trg
          FROM pg_trigger tg
          JOIN pg_class c ON c.oid = tg.tgrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = current_schema()
           AND c.relname = 'resource_grants'
           AND NOT tg.tgisinternal
           AND tg.tgname LIKE '%\\_frozen\\_%'
    LOOP
        EXECUTE format('ALTER TABLE resource_grants {action} TRIGGER %I', row.trg);
    END LOOP;
END $$;
"""

_DEMOTE = """
UPDATE resource_grants
   SET level = 'write'
 WHERE level = 'owner'
   AND user_id IS NULL
"""

_REMAINING = """
SELECT count(*) FROM resource_grants WHERE level = 'owner' AND user_id IS NULL
"""


def demote_grantee_owner_grants(connection: Connection) -> int:
    """Demote every owner grant naming no user, in the schema ``search_path``
    is routed to. Returns how many rows changed.

    Public so the test that drives it against real rows runs the statements
    this revision actually carries, rather than a copy of them.
    """
    connection.execute(text("ALTER TABLE resource_grants NO FORCE ROW LEVEL SECURITY"))
    connection.execute(text(_SET_FREEZE_TRIGGERS.format(action="DISABLE")))

    demoted = connection.execute(text(_DEMOTE)).rowcount

    connection.execute(text(_SET_FREEZE_TRIGGERS.format(action="ENABLE")))
    connection.execute(text("ALTER TABLE resource_grants FORCE ROW LEVEL SECURITY"))

    remaining = connection.execute(text(_REMAINING)).scalar()
    if remaining:
        raise RuntimeError(
            f"{remaining} owner grants still name no user after the demotion"
        )
    return demoted


def upgrade() -> None:
    connection = op.get_bind()
    run_for_each_guild_schema(
        connection, lambda: demote_grantee_owner_grants(connection)
    )


def downgrade() -> None:
    # Nothing to restore: which write grants used to be owner rows is not
    # recorded anywhere, and a role holding one is the state this repairs.
    pass
