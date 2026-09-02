"""The age confirmation a listed guild's members give, and the switch behind it.

Two columns, no new table and nothing to carry into one.

* ``users.age_confirmed_at`` — when an account said it belongs to somebody at
  least 13 years old, NULL where it never has. Nullable with no default, so
  every account that already exists starts out having said nothing, which is
  the truth about them: the confirmation is theirs to give and cannot be
  inferred from a row that predates the question.
* ``app_settings.community_age_gate_enabled`` — whether the question is asked
  on this deployment at all. Defaults true so a deployment that upgrades into
  a running community directory starts out asking; a platform owner turns it
  off to assert that every account here already belongs to an adult.

``app_settings`` is granted table-wide to the owner tier, so its new column
arrives writable. ``public.users`` is not: the request path holds its UPDATE
per column (0144), so a new column there is named for each request-path floor
or it is unwritable. Every column but ``role`` is writable by all three, and
this one is no exception — ``security_invariants_test`` holds that line.

Neither column is referenced by a policy, so there is no RLS to lift: an
``ADD COLUMN`` is not a policy-bound write.

Revision ID: 20260904_0219
Revises: 20260904_0218
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260904_0219"
down_revision = "20260904_0218"
branch_labels = None
depends_on = None


#: The request-path floors, which hold their UPDATE on ``users`` per column.
def _write_roles() -> tuple[str, ...]:
    return (
        "app_guild_base",
        f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"',
        "app_user",
    )


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("age_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "community_age_gate_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
    for role in _write_roles():
        op.execute(f"GRANT UPDATE (age_confirmed_at) ON TABLE public.users TO {role}")


def downgrade() -> None:
    op.drop_column("app_settings", "community_age_gate_enabled")
    # The grant goes with the column it names.
    op.drop_column("users", "age_confirmed_at")
