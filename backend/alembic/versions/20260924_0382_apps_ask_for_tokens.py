"""apps ask for tokens

An app authenticates at ``POST /api/v1/app-platform/oauth/token`` with a JWT
it signs (RFC 7523 client authentication). Two changes back that.

- ``app_service_registrations.delegation_jwks`` becomes ``jwks``. The key set
  is the app's client credential now: the token endpoint verifies assertions
  against it, and the delegation path keeps reading it under the new name.
- ``public.app_assertion_jtis`` records the ``jti`` of every assertion
  presented, keyed by (registration, jti) until the assertion's ``exp``. It is
  the system engine's alone: ``app_admin`` reads, inserts and deletes; the
  login role and the guild and platform floors, which the schema default
  grants full DML on a new table, are revoked; the seat and install floors
  take no default privileges and are granted nothing. RLS is enabled and
  forced with no policies (``FORCED_NO_POLICY`` in ``app.db.public_rls``).

The table is new and has nothing to carry, so it is created and then locked.

Revision ID: 20260924_0382
Revises: 20260924_0381
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260924_0382"
down_revision = "20260924_0381"
branch_labels = None
depends_on = None

REGISTRATIONS = "app_service_registrations"
TABLE = "app_assertion_jtis"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.alter_column(REGISTRATIONS, "delegation_jwks", new_column_name="jwks")

    op.create_table(
        TABLE,
        sa.Column("registration_id", sa.Integer(), nullable=False),
        sa.Column("jti", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["registration_id"],
            [f"{REGISTRATIONS}.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("registration_id", "jti"),
    )
    # The janitor sweeps by expiry, so that is the column it reads.
    op.create_index(f"ix_{TABLE}_expires_at", TABLE, ["expires_at"], unique=False)

    base = _platform_base()
    _run(
        [
            f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
            f"REVOKE ALL ON TABLE public.{TABLE} "
            f'FROM app_user, app_guild_base, "{base}"',
            f"GRANT SELECT, INSERT, DELETE ON TABLE public.{TABLE} TO app_admin",
        ]
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.{TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_index(f"ix_{TABLE}_expires_at", table_name=TABLE)
    op.drop_table(TABLE)

    op.alter_column(REGISTRATIONS, "jwks", new_column_name="delegation_jwks")
