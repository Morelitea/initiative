"""Single source of truth for the audited per-table GRANTs the two directly-
granted login roles hold on the shared (``public``) tables.

Two Postgres login roles carry *enumerated* per-table privileges on the shared
schema; the routed ``guild_<id>`` / ``platform_<tier>`` roles instead inherit
public access from ``app_guild_base`` / ``platform_base`` defaults, so they are
not listed here:

* **``app_admin``** — the system engine (BYPASSRLS trusted-batch actor). Its
  security boundary *is* exactly this grant set: a new shared table gives the
  system engine nothing until a decision here says otherwise.
  ``SHARED_TABLE_SYSTEM_GRANTS``.
* **``app_user``** — the bare login role serving the pre-routing /
  unauthenticated surface (RLS-enforced, no ``SET ROLE`` yet).
  ``SHARED_TABLE_APP_USER_GRANTS``.

Historically these matrices were the audited product of migrations
20260702_0129 (``app_admin``) and _0130 (``app_user``), folded into the
post-squash reconciler 20260702_0126. **Migrations remain the immutable record
of when a grant changed** (they still run the actual ``GRANT``/``REVOKE``);
this registry is the *current truth*, enforced two ways:

* against the live catalog — ``security_invariants_test`` fails on any drift in
  either direction (a hotfix ``GRANT`` the registry doesn't know about, or a
  registry verb the catalog lacks);
* against ``SHARED_TABLES`` for completeness — ``system_grants_test`` fails when
  a shared table has no grant decision, so "give a new table nothing until
  decided" is a real edit here rather than a comment in CLAUDE.md.

This is the same registry-vs-rendered split as ``INITIATIVE_PATHS`` (in
``app.db.initiative_rls``) vs the guild RLS DDL. See issue #782.
"""

from __future__ import annotations

from app.db.tenancy import SHARED_TABLES

__all__ = [
    "SHARED_TABLE_SYSTEM_GRANTS",
    "SHARED_TABLE_APP_USER_GRANTS",
    "NON_MODEL_SHARED_TABLES",
    "GRANTABLE_SHARED_TABLES",
    "VALID_GRANT_VERBS",
    "grant_sql",
]

# Public tables that carry no SQLModel (so they're absent from ``SHARED_TABLES``,
# which derives from model metadata) yet still exist in ``public`` and so still
# need an explicit "grant it nothing" decision for the login roles.
NON_MODEL_SHARED_TABLES: frozenset[str] = frozenset({"alembic_version"})

# Every ``public`` table that requires a per-role grant decision.
GRANTABLE_SHARED_TABLES: frozenset[str] = SHARED_TABLES | NON_MODEL_SHARED_TABLES

# Canonical DML verb order for rendered ``GRANT`` statements. Grant order is
# semantically irrelevant, so the registry stores verb *sets* (compared directly
# against the catalog) and only imposes an order when rendering SQL — this keeps
# a re-grant written in a different order from reading as spurious "drift".
_VERB_ORDER: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE", "DELETE")
VALID_GRANT_VERBS: frozenset[str] = frozenset(_VERB_ORDER)


# table -> the verbs the SYSTEM ENGINE (``app_admin``) call sites actually use,
# or ``None`` for "no system-engine access". Audited in migration 20260702_0129.
SHARED_TABLE_SYSTEM_GRANTS: dict[str, frozenset[str] | None] = {
    "users": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "guilds": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "guild_memberships": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # invite redemption reads/creates/updates; row removal rides the FK cascade
    "guild_invites": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "access_grants": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # singleton config: seeded + updated, never deleted
    "app_settings": frozenset({"SELECT", "INSERT", "UPDATE"}),
    # OIDC sync reads mappings; the settings endpoints manage them
    "oidc_claim_mappings": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # login provider registry (successor to app_settings.oidc_*): fully managed
    # on the system engine — login reads + provider CRUD via AdminSessionDep with
    # capability/ownership checks (as access_grants). Like oidc_claim_mappings, it
    # carries NO permissive RLS policy, so the request path can't read guild-scoped
    # provider config (no cross-tenant metadata leak).
    "auth_providers": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # provider client secret — read/written only by the system engine (provider
    # CRUD via AdminSessionDep + config.manage); the request path has no grant, so
    # a secret can't be exfiltrated by an over-broad authenticated-path query
    "auth_provider_secrets": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # identity linking — resolved/created at login (pre-auth, by subject); link/
    # unlink go through the system engine (linking is an account-takeover surface)
    "federated_identities": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # session/refresh store — validated pre-auth by refresh-token hash (user
    # unknown), so all session ops run on the system engine; request path revoked
    "auth_sessions": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # personal UI state — the system engine has no business here
    "user_view_preferences": None,
    "notifications": frozenset({"SELECT", "INSERT", "DELETE"}),
    "user_tokens": frozenset({"SELECT", "INSERT", "DELETE"}),
    "push_tokens": frozenset({"SELECT", "INSERT", "DELETE"}),
    "user_api_keys": frozenset({"SELECT", "DELETE"}),
    "auto_delegation_jti_blocklist": frozenset({"SELECT", "INSERT"}),
    # migrations-only bookkeeping (the provisioning role owns it)
    "alembic_version": None,
}


# table -> the verbs the BARE LOGIN role (``app_user``) call sites use, or
# ``None``. The pre-routing / unauthenticated surface. Audited in migration
# 20260702_0130.
SHARED_TABLE_APP_USER_GRANTS: dict[str, frozenset[str] | None] = {
    "users": frozenset({"SELECT", "UPDATE"}),
    "user_tokens": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "user_api_keys": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "auto_delegation_jti_blocklist": frozenset({"SELECT", "INSERT"}),
    "app_settings": frozenset({"SELECT"}),
    "guilds": frozenset({"SELECT"}),
    "guild_invites": frozenset({"SELECT"}),
    "guild_memberships": frozenset({"SELECT"}),
    "access_grants": frozenset({"SELECT"}),
    # provider reads for the login page go via the system engine (AdminSessionDep),
    # not the bare login role — so guild-scoped provider config never leaks here
    "auth_providers": None,
    # client secrets are system-engine-only; no request role ever reads them
    "auth_provider_secrets": None,
    # own-row identity links are read on the authenticated (platform_<tier>)
    # path, not the bare pre-routing role
    "federated_identities": None,
    # sessions are system-engine-only; the bare login role never touches them
    "auth_sessions": None,
    "notifications": None,
    "oidc_claim_mappings": None,
    "push_tokens": None,
    "user_view_preferences": None,
    "alembic_version": None,
}


def grant_sql(verbs: frozenset[str] | None) -> str | None:
    """Render a registry verb set as a canonical ``GRANT`` verb list (fixed
    order), or ``None`` when the role gets no access — lets a future migration
    emit the grant straight from the registry instead of re-typing verbs."""
    if not verbs:
        return None
    return ", ".join(v for v in _VERB_ORDER if v in verbs)
