"""create auth_provider_secrets (app_admin-only client-secret store)

Splits the provider client secret out of ``auth_providers`` into an
**app_admin-only** companion (history/auth-detailed-design.md §6.2): the
request-path (``platform_<tier>``) roles hold *no* grant on secret material, so
even an over-broad query or an injection on the authenticated path cannot
exfiltrate a client secret. Metadata (issuer, client_id — public in OIDC) stays
on ``auth_providers``; only the secret is here.

1:1 with the provider (``provider_id`` PK, FK ``ON DELETE CASCADE``). The public
schema default-grants platform_base + app_guild_base full DML on every new
table, so we REVOKE both. Additive only — nothing reads or writes it yet; the
OidcProvider phase backfills it (verbatim ciphertext, same Fernet salt) + reads
it on the system engine.
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260706_0133"
down_revision = "20260706_0132"
branch_labels = None
depends_on = None


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        "auth_provider_secrets",
        sa.Column("provider_id", sa.Integer(), primary_key=True),
        sa.Column("client_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["auth_providers.id"], ondelete="CASCADE"
        ),
    )

    base = _platform("base")
    _run(
        [
            "ALTER TABLE public.auth_provider_secrets ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.auth_provider_secrets FORCE ROW LEVEL SECURITY",
            # Strip the schema-default DML: the client secret is read/written only
            # by the system engine (provider CRUD via AdminSessionDep + config.manage),
            # never on the request path — so a request-role query can't reach it.
            f'REVOKE ALL ON TABLE public.auth_provider_secrets FROM app_guild_base, "{base}"',
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.auth_provider_secrets TO app_admin",
        ]
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.auth_provider_secrets CASCADE")
