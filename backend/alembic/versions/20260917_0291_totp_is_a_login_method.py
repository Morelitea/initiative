"""The vocabulary of ways in gains the authenticator app.

``login_method`` is the enum behind two things: the checklist of what a
deployment permits (``app_settings.login_methods``) and what a community may
require of a sign-in (``guild_auth_policies.require_methods``). A second factor
belongs in it — it is presented while signing in, and both of those questions
can sensibly be asked about it.

The label only. Nothing uses it yet: the revision after this one puts it into
the deployment's own set, and it cannot do both, because a label added inside a
transaction cannot be used until that transaction has committed. Alembic runs
each revision in its own (``transaction_per_migration``), so two revisions is
what two transactions looks like here.

Revision ID: 20260917_0291
Revises: 20260916_0290
Create Date: 2026-09-17
"""

from alembic import op

revision = "20260917_0291"
down_revision = "20260916_0290"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Adding a label is allowed inside the migration's transaction; using it in
    # the same one is not, and nothing here does.
    op.execute("ALTER TYPE public.login_method ADD VALUE IF NOT EXISTS 'totp'")


def downgrade() -> None:
    # Postgres cannot drop a label from an enum. Leaving it is inert: the
    # upgrade is idempotent, and the revision that follows takes the value back
    # out of every row that holds it before this one is reached.
    pass
