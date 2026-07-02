"""Bound the system engine by enumerated table GRANTs (industry-standard model).

``app_admin`` (the ``DATABASE_URL_ADMIN`` login for background jobs, startup
seeding, and platform lifecycle endpoints) is the textbook PostgreSQL
"trusted batch/system" actor: it keeps ``BYPASSRLS`` — the mechanism the RLS
documentation designates for administrative sweeps — and its boundary is
**which tables it is GRANTed**, spelled out per table below instead of the old
chain's blanket ``GRANT ALL`` everywhere:

1. **Enumerated per-table grants** — each shared table gets exactly the verb
   set its audited call sites use (e.g. the system engine never touches
   ``user_view_preferences``, and never UPDATEs ``notifications``).
2. **Narrowed default privileges** — the blanket ``ALTER DEFAULT PRIVILEGES …
   GRANT ALL ON TABLES/SEQUENCES TO app_admin`` is revoked: a new shared table
   is born with NO system-engine access until a migration grants it.

Guild schemas are unaffected: the system engine holds no standing access there
and must ``SET ROLE guild_<id>`` (which drops BYPASSRLS), running under the
guild's own grants and policies — with ``guild_role='admin'`` for
full-authority maintenance (trash purge, admin endpoints).

Sequence grants are left as-is: sequence access carries no row data, and
INSERT-granted tables need their serial sequences anyway.

Derived from the 2026-07-02 call-site audit (AdminSessionDep endpoints,
AdminSessionLocal workers, startup seeding, maintenance jobs). A future
feature that needs a new verb adds a migration widening exactly that grant.

Revision ID: 20260702_0129
Revises: 20260701_0128
Create Date: 2026-07-02
"""

from alembic import op
from sqlalchemy import text

revision = "20260702_0129"
down_revision = "20260701_0128"
branch_labels = None
depends_on = None

# table -> verbs the system engine's call sites use (audited).
_SYSTEM_TABLE_GRANTS: dict[str, str | None] = {
    "users": "SELECT, INSERT, UPDATE, DELETE",
    "guilds": "SELECT, INSERT, UPDATE, DELETE",
    "guild_memberships": "SELECT, INSERT, UPDATE, DELETE",
    # invite redemption reads/creates/updates; row removal rides the FK cascade
    "guild_invites": "SELECT, INSERT, UPDATE",
    "access_grants": "SELECT, INSERT, UPDATE, DELETE",
    # singleton config: seeded + updated, never deleted
    "app_settings": "SELECT, INSERT, UPDATE",
    # OIDC sync reads mappings; the settings endpoints manage them (system engine)
    "oidc_claim_mappings": "SELECT, INSERT, UPDATE, DELETE",
    # personal UI state — the system engine has no business here
    "user_view_preferences": None,
    "notifications": "SELECT, INSERT, DELETE",
    "user_tokens": "SELECT, INSERT, DELETE",
    "push_tokens": "SELECT, INSERT, DELETE",
    "user_api_keys": "SELECT, DELETE",
    "auto_delegation_jti_blocklist": "SELECT, INSERT",
    # migrations-only bookkeeping (the provisioning role owns it)
    "alembic_version": None,
}


def upgrade() -> None:
    conn = op.get_bind()
    for table, verbs in _SYSTEM_TABLE_GRANTS.items():
        conn.execute(text(f'REVOKE ALL ON TABLE public."{table}" FROM app_admin'))
        if verbs:
            conn.execute(text(f'GRANT {verbs} ON TABLE public."{table}" TO app_admin'))
    # Future tables get no implicit system-engine access. (Default-privilege
    # entries are per-grantor; migrations always run as the provisioning role,
    # the same role that created the original entry.)
    conn.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "REVOKE ALL ON TABLES FROM app_admin"
        )
    )
    conn.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "REVOKE ALL ON SEQUENCES FROM app_admin"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_admin"
        )
    )
    conn.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT ALL ON SEQUENCES TO app_admin"
        )
    )
    for table in _SYSTEM_TABLE_GRANTS:
        conn.execute(text(f'GRANT ALL ON TABLE public."{table}" TO app_admin'))
