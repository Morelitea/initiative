"""app service registrations

The ``public`` table behind deployment-level app wiring: one row per external
app service this deployment has approved, holding its base URL, the shared HMAC
secret (Fernet ciphertext), the last verification result, and the two things
only an operator may assert about an app — the powers conferred on it
(``grants``) and whether every guild gets it (``mandatory``).

Access shape (owner + system engine only):

* **write** on the system engine alone. The CRUD endpoints run on
  ``AdminSessionDep`` behind the ``apps.manage`` capability, and boot
  reconciliation upserts from a mounted config file.
* **read** additionally by the platform owner, under a SELECT-only policy, so
  the admin surface can be served role-scoped.
* every other role holds nothing. The schema default-grants the base/login
  roles full DML on each new ``public`` table, so those are revoked here — the
  row carries secret ciphertext, and denying it at the grant layer as well as
  the policy layer keeps a single mistake from being enough.
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260812_0169"
down_revision = "20260812_0168"
branch_labels = None
depends_on = None

TABLE = "app_service_registrations"


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=120), nullable=False),
        sa.Column("listing_uid", sa.String(length=14), nullable=True),
        sa.Column("base_url", sa.String(length=1000), nullable=False),
        sa.Column(
            "allowed_origins",
            sa.dialects.postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column("manifest_hash", sa.String(length=64), nullable=True),
        sa.Column("protocol_version", sa.Integer(), nullable=True),
        # Operator-conferred powers; a manifest can never claim one. Validated
        # against a closed vocabulary in the service layer on every write.
        sa.Column(
            "grants",
            sa.dialects.postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("mandatory", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="unverified", nullable=False
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        f"ix_{TABLE}_listing_uid",
        TABLE,
        ["listing_uid"],
        unique=False,
    )

    base = _platform("base")
    owner = _platform("owner")
    _run(
        [
            f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
            f"REVOKE ALL ON TABLE public.{TABLE} "
            f'FROM app_guild_base, "{base}", app_user',
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
            f"public.{TABLE} TO app_admin",
            f'GRANT SELECT ON TABLE public.{TABLE} TO "{owner}"',
            # The system engine is the only INSERTer, so it is the only role
            # that needs the id sequence.
            f"REVOKE ALL ON SEQUENCE public.{TABLE}_id_seq "
            f'FROM app_guild_base, "{base}", app_user',
            f"GRANT USAGE, SELECT ON SEQUENCE public.{TABLE}_id_seq TO app_admin",
            f"DROP POLICY IF EXISTS {TABLE}_owner_read ON public.{TABLE}",
            # Read-only for the platform owner (not a BYPASSRLS role, so it
            # needs the policy); writes have no policy at all and run on the
            # system engine.
            f"CREATE POLICY {TABLE}_owner_read ON public.{TABLE} "
            f'AS PERMISSIVE FOR SELECT TO "{owner}" USING (true)',
        ]
    )


def downgrade() -> None:
    _run(
        [
            f"DROP POLICY IF EXISTS {TABLE}_owner_read ON public.{TABLE}",
            f"ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY",
        ]
    )
    op.drop_index(f"ix_{TABLE}_listing_uid", table_name=TABLE)
    op.drop_table(TABLE)
