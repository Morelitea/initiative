"""Bound the bare login role (`app_user`) by enumerated table GRANTs.

Companion to 20260702_0129 (which did the same for the system engine). Every
request starts as the ``app_user`` login role before ``SET ROLE`` assumes a
platform tier or guild role — and the unauthenticated surface (login, password
reset, email verification, OIDC callback, public config, invite lookup) plus
per-request auth resolution run entirely on it. The old chain granted it
blanket per-table DML everywhere; this reduces it to the audited verb set of
those bare-login call sites:

* auth resolution + self-service credential lifecycle: ``users`` (read/update
  only — creation is the system engine's, deletion is nobody's),
  ``user_tokens`` and ``user_api_keys`` (full self-service lifecycle),
  ``auto_delegation_jti_blocklist`` (append-only replay guard);
* pre-routing/unauthenticated reads: ``app_settings``, ``guilds``,
  ``guild_invites``, ``guild_memberships``, and ``access_grants`` (deps
  validate a live PAM/break-glass grant before routing) — SELECT only;
* everything else — ``notifications``, ``push_tokens``,
  ``oidc_claim_mappings``, ``user_view_preferences`` — is reached only through
  ``platform_<tier>``/guild roles after routing, so the bare login role gets
  nothing.

Routed access is unaffected: ``platform_base`` / ``app_guild_base`` grants are
their own (unchanged) layers. Sequence grants stay (INSERT-granted tables need
their serials; sequences carry no row data). Default privileges for future
tables are revoked, like the system engine's: a new shared table grants the
bare login role nothing until a migration decides.

Revision ID: 20260702_0130
Revises: 20260702_0129
Create Date: 2026-07-02
"""

from alembic import op
from sqlalchemy import text

revision = "20260702_0130"
down_revision = "20260702_0129"
branch_labels = None
depends_on = None

# table -> verbs the bare login role's audited call sites use.
_APP_USER_TABLE_GRANTS: dict[str, str | None] = {
    "users": "SELECT, UPDATE",
    "user_tokens": "SELECT, INSERT, UPDATE, DELETE",
    "user_api_keys": "SELECT, INSERT, UPDATE, DELETE",
    "auto_delegation_jti_blocklist": "SELECT, INSERT",
    "app_settings": "SELECT",
    "guilds": "SELECT",
    "guild_invites": "SELECT",
    "guild_memberships": "SELECT",
    "access_grants": "SELECT",
    "notifications": None,
    "oidc_claim_mappings": None,
    "push_tokens": None,
    "user_view_preferences": None,
    "alembic_version": None,
}


def upgrade() -> None:
    conn = op.get_bind()
    for table, verbs in _APP_USER_TABLE_GRANTS.items():
        conn.execute(text(f'REVOKE ALL ON TABLE public."{table}" FROM app_user'))
        if verbs:
            conn.execute(text(f'GRANT {verbs} ON TABLE public."{table}" TO app_user'))
    conn.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "REVOKE ALL ON TABLES FROM app_user"
        )
    )
    conn.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "REVOKE ALL ON SEQUENCES FROM app_user"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_user"
        )
    )
    conn.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT ALL ON SEQUENCES TO app_user"
        )
    )
    for table in _APP_USER_TABLE_GRANTS:
        conn.execute(text(f'GRANT ALL ON TABLE public."{table}" TO app_user'))
