"""the bell is row-secured, and a write names who it is for

Turns on row security for ``public.notifications``. The policies come from the
registry in ``app/db/public_rls.py`` and are applied at boot, as every other
shared table's do — a migration would freeze what the registry said today.

The bell needed its own design rather than the own-row rule the other per-user
tables use, because a notification is written by somebody other than the person
it belongs to: a mention is caused by one account and delivered to another, from
the request that caused it, inside the community it happened in. The reader's
rule and the writer's rule are therefore different rules.

* The reader is the platform floor, which serves the bell: it lists, marks read
  and dismisses rows whose ``user_id`` is its own.
* The writer is the guild floor, which a routed request runs as: it works on the
  account named in ``app.notify_target_user_id`` and on rows tagged with the
  community it is routed into. ``user_notifications.name_recipient`` sets that
  value, transaction-locally, ahead of each lookup, insert, rollup and
  withdrawal — a value the write already holds, so nothing had to be threaded
  through the callers to supply it.

No grant moves here. ``app_guild_base`` already holds the DML the write path
uses, and ``app_guild_base_ro`` derives its SELECT from it.
"""

from alembic import op

revision = "20260922_0349"
down_revision = "20260922_0348"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The policies arrive from the registry on the next boot.
    op.execute("ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE public.notifications DISABLE ROW LEVEL SECURITY")
    for name in (
        "notifications_self_read",
        "notifications_self_update",
        "notifications_self_delete",
        "notifications_write_named_recipient",
        "notifications_insert_named_recipient",
        "notifications_update_named_recipient",
        "notifications_delete_named_recipient",
    ):
        op.execute(f"DROP POLICY IF EXISTS {name} ON public.notifications")
