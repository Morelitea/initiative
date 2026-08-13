"""app service nonces

The ``public`` table backing the replay guard on the app-service request-signing
channel: one row per signed request an app has already spent, keyed by
(registration, nonce) so each app has its own namespace.

Access shape (system engine only):

* the verifier inserts and reads on ``app_admin``; the shared jti janitor
  deletes rows whose freshness window has passed.
* every other role holds nothing. The schema default-grants the base/login
  roles full DML on each new ``public`` table, so those are revoked here — no
  request-path role has any business in the guard that protects a
  machine-to-machine channel.
* RLS is enabled and FORCEd with no policies, matching the registrations table
  it hangs off: the grant layer and the policy layer both say no.
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260812_0173"
down_revision = "20260812_0172"
branch_labels = None
depends_on = None

TABLE = "app_service_nonces"


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("registration_id", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["registration_id"],
            ["app_service_registrations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("registration_id", "nonce"),
    )
    # The janitor sweeps by expiry, so that is the column it reads.
    op.create_index(f"ix_{TABLE}_expires_at", TABLE, ["expires_at"], unique=False)

    base = _platform("base")
    _run(
        [
            f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
            f"REVOKE ALL ON TABLE public.{TABLE} "
            f'FROM app_guild_base, "{base}", app_user',
            f"GRANT SELECT, INSERT, DELETE ON TABLE public.{TABLE} TO app_admin",
        ]
    )


def downgrade() -> None:
    _run(
        [
            f"ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY",
        ]
    )
    op.drop_index(f"ix_{TABLE}_expires_at", table_name=TABLE)
    op.drop_table(TABLE)
