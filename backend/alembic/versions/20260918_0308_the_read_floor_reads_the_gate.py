"""the read floor reads what the gate reads

``app_guild_base_ro`` is the read half of ``app_guild_base``, and it takes no
schema-wide default privileges — a shared table added later reaches the
writable floor and not this one until a migration says so. Two did not:
``guild_provider_connections`` (0303) and ``platform_provider_defaults`` (0305).

Both are read by ``public.guild_connection_admits``, which every guild content
policy reaches through ``initiative_access`` → ``guild_auth_satisfied()``. A
session routed into ``guild_<id>_ro`` therefore faults with *permission denied*
the moment that gate has a sign-in requirement to evaluate, instead of
answering the question.

Two paths route into that role. A PAM read grant does not carry
``current_guild_id`` — a grant records its guild in its own field — so the gate
matches no policy row and stops before reaching either table. A community in
``read_only`` lifecycle status does: it routes a **real member** into the
SELECT-only role while keeping the membership GUCs, so the gate runs in full
and every content read in such a community fails while a sign-in requirement
stands.

Grants only. No table, no policy, no data: the read floor gets the SELECT the
writable floor already had, and nothing else changes.

Revision ID: 20260918_0308
Revises: 20260918_0307
Create Date: 2026-09-18
"""

from alembic import op

revision = "20260918_0308"
down_revision = "20260918_0307"
branch_labels = None
depends_on = None

ROLE = "app_guild_base_ro"

#: The two the gate reads. Both already grant SELECT to ``app_guild_base``;
#: this gives the read half the same reach.
TABLES = ("guild_provider_connections", "platform_provider_defaults")


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"GRANT SELECT ON TABLE public.{table} TO {ROLE}")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"REVOKE SELECT ON TABLE public.{table} FROM {ROLE}")
