"""A community's sign-in requirement can name a method, not only a provider.

``guild_auth_policies.require_methods``: an array of the same ``login_method``
enum the platform checklist uses (migration 0284), so an operator choosing
which ways in a deployment permits and a community choosing which it accepts
are picking from one vocabulary rather than two that drift.

Empty says nothing about methods, which is every row that exists, so an upgrade
changes nobody. Non-empty means the session's methods must intersect it.

The CHECK is the one asymmetry, and it is deliberate: whether passwords exist
at all is the deployment's question and stays there, so a community may ask for
single sign-on and may not ask for a password. Held in the database rather than
only in the write path, so it holds for every writer.

``required`` also stops meaning "names a provider": its constraint becomes
"names a provider, or a method, or both", because those are now two ways of
saying the same kind of thing.

``ADD COLUMN`` with a server default, which Postgres applies as metadata — no
row rewrite, and no policy-bound DML to route around ``FORCE ROW LEVEL
SECURITY``. The downgrade's DELETE is the one write, set up the way the other
``public`` writes in this directory are.

Revision ID: 20260916_0286
Revises: 20260916_0285
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_0286"
down_revision = "20260916_0285"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guild_auth_policies",
        sa.Column(
            "require_methods",
            postgresql.ARRAY(
                postgresql.ENUM(
                    "password", "sso", name="login_method", create_type=False
                )
            ),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_check_constraint(
        "ck_guild_auth_policies_require_methods_no_password",
        "guild_auth_policies",
        "NOT ('password' = ANY(require_methods))",
    )
    # ``required`` used to mean "names a provider", which is no longer the only
    # thing a requirement can name. It still has to require *something*.
    op.drop_constraint(
        "ck_guild_auth_policies_required_provider",
        "guild_auth_policies",
        type_="check",
    )
    op.create_check_constraint(
        "ck_guild_auth_policies_required_names_something",
        "guild_auth_policies",
        "policy = 'open'"
        " OR (provider_id IS NOT NULL AND provider_slug IS NOT NULL)"
        " OR cardinality(require_methods) > 0",
    )


def downgrade() -> None:
    # A methods-only rule cannot survive a column that no longer exists, and
    # the constraint coming back would refuse it. Give those guilds back the
    # shape the old constraint describes: no requirement at all, which is what
    # "required, naming nothing this version understands" amounts to.
    # Set up the way every other ``public`` write in this directory is
    # (see 0279, which reverses the same kind of addition).
    conn = op.get_bind()
    op.execute("ALTER TABLE public.guild_auth_policies NO FORCE ROW LEVEL SECURITY")
    try:
        conn.execute(
            sa.text(
                "DELETE FROM public.guild_auth_policies "
                "WHERE provider_id IS NULL AND cardinality(require_methods) > 0"
            )
        )
    finally:
        op.execute("ALTER TABLE public.guild_auth_policies FORCE ROW LEVEL SECURITY")
    op.drop_constraint(
        "ck_guild_auth_policies_required_names_something",
        "guild_auth_policies",
        type_="check",
    )
    op.create_check_constraint(
        "ck_guild_auth_policies_required_provider",
        "guild_auth_policies",
        "policy = 'open' OR (provider_id IS NOT NULL AND provider_slug IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_guild_auth_policies_require_methods_no_password",
        "guild_auth_policies",
        type_="check",
    )
    op.drop_column("guild_auth_policies", "require_methods")
