"""The vocabulary of ways in gains the emailed code.

``login_method`` is the enum behind two things: the checklist of what a
deployment permits (``app_settings.login_methods``) and what a community may
require of a sign-in (``guild_auth_policies.require_methods``).

The label only. The revision after this one widens the constraints that use it,
because a label added inside a transaction cannot be used until that
transaction has committed; Alembic runs each revision in its own
(``transaction_per_migration``), so two revisions is what two transactions
looks like here.

Unlike 0314/0315, which added the passkey, nothing here puts the value into any
deployment's set. It is permitted by an operator ticking it, never by an
upgrade — see ``DEFAULT_LOGIN_METHODS``.

Revision ID: 20260920_0329
Revises: 20260920_0328
Create Date: 2026-09-20
"""

from alembic import op

revision = "20260920_0329"
down_revision = "20260920_0328"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Adding a label is allowed inside the migration's transaction; using it in
    # the same one is not, and nothing here does.
    op.execute("ALTER TYPE public.login_method ADD VALUE IF NOT EXISTS 'email_otp'")


def downgrade() -> None:
    # Postgres cannot drop a label from an enum. Leaving it is inert: the
    # upgrade is idempotent, and the revision that follows takes the value back
    # out of every row that holds it before this one is reached.
    pass
