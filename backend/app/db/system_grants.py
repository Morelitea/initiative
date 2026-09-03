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
# ``storage_backfill_state`` is created lazily at runtime (see
# app.services.storage_backfill), not by a migration; its entry below is what
# the service's own GRANT renders from.
NON_MODEL_SHARED_TABLES: frozenset[str] = frozenset(
    {"alembic_version", "storage_backfill_state"}
)

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
    # The operator-set caps / plan label / sign-in entitlement. The system engine
    # is the only writer on the request path: the platform Guilds dashboard runs
    # on AdminSessionDep, and provisioning creates the row with the guild. (The
    # verified billing path writes its three columns under its own role, which is
    # granted per column in migration 0178 and so is not listed here.) DELETE
    # rides the FK cascade off ``guilds``, but the guild-deletion path removes it
    # explicitly too.
    "guild_administration": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "guild_memberships": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # invite redemption reads/creates/updates; row removal rides the FK cascade
    "guild_invites": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "access_grants": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # singleton config: seeded + updated, never deleted
    "app_settings": frozenset({"SELECT", "INSERT", "UPDATE"}),
    # Marketplace catalog: the system engine is the only writer — boot seeding of
    # the shipped listings, and later the registry refresh job. DELETE is there
    # for versions a re-seed supersedes; a withdrawn *listing* is flipped to
    # available=false rather than removed, so installs keep their provenance.
    "marketplace_listings": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "marketplace_listing_versions": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # App service registrations: full DML on the system engine, which is the
    # only writer — the owner-gated CRUD endpoints run on AdminSessionDep (as
    # access_grants and auth_providers do), boot reconciliation upserts from
    # APP_SERVICES_CONFIG, and the verify path stamps status/manifest_hash.
    # The row holds the shared-secret ciphertext, so it stays off the bare
    # login role entirely (below).
    "app_service_registrations": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # Replay guard for the app-service channel: the verifier reads and inserts,
    # and the shared jti janitor prunes rows whose freshness window has passed
    # (a request that old is refused before the guard is consulted, so pruning
    # constrains nothing). Never updated — a spent nonce has one state.
    "app_service_nonces": frozenset({"SELECT", "INSERT", "DELETE"}),
    # Registry client state: read and written by the refresh job alone. One row
    # per registry URL, recycled in place, so nothing is ever deleted.
    "marketplace_registry_state": frozenset({"SELECT", "INSERT", "UPDATE"}),
    # Mirrored listing artwork: written by the refresh job; DELETE prunes bytes
    # no listing references any more.
    "marketplace_media": frozenset({"SELECT", "INSERT", "DELETE"}),
    # Guild icons and banners: the whole table is the system engine's, because
    # the one thing it has to answer — may this caller see this guild's icon or
    # card rendition — depends on a listing the caller may hold no role to read.
    # Serving reads; a guild admin replacing a picture inserts (after the
    # endpoint has checked their role) and deletes the one it replaces.
    "guild_images": frozenset({"SELECT", "INSERT", "DELETE"}),
    # Profile pictures. The system engine reads them to serve the bytes before a
    # session exists, writes them on the backfill, and DELETEs on the moderation
    # and anonymization paths — both of which act on someone else's row and so
    # cannot run under the own-row request-path policies.
    "user_avatars": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # A person's decoration library. Grants are issued, never self-served: a
    # pack install writes the rows and an uninstall removes them, both on the
    # system engine. The request path only reads its own (SELECT), so every
    # write verb lives here.
    "user_decorations": frozenset({"SELECT", "INSERT", "DELETE"}),
    # My Contacts stars. The request path owns every write under its own-row
    # policies; the system engine reads and deletes only for erasure, which has
    # to clear an anonymized account off other people's lists too — the row
    # survives the husk, so the FK cascade never fires for it.
    "profile_favorites": frozenset({"SELECT", "DELETE"}),
    # An account is created on the system engine (registration, invite
    # redemption, provisioning from an identity provider), and its policy row is
    # seeded there from the operator default — hence INSERT. The other three are
    # written on the request path by the account holder; the system engine only
    # reads them for the guild-lifecycle sweeps and clears them on erasure.
    "user_dm_settings": frozenset({"SELECT", "INSERT", "DELETE"}),
    "user_dm_guild_optouts": frozenset({"SELECT", "DELETE"}),
    "contact_grants": frozenset({"SELECT", "DELETE"}),
    # SELECT also carries the notification fan-out: who, of a set of
    # recipients, ignores the actor (see app.services.platform.accounts).
    "user_ignores": frozenset({"SELECT", "DELETE"}),
    # The transport. The system engine clears an erased account off all five
    # and sweeps devices that have stopped syncing; it writes none of them.
    # Nothing about a direct message is ever created by anything but the
    # account's own session.
    "dm_devices": frozenset({"SELECT", "DELETE"}),
    "dm_one_time_keys": frozenset({"SELECT", "DELETE"}),
    "dm_conversations": frozenset({"SELECT", "DELETE"}),
    "dm_conversation_members": frozenset({"SELECT", "DELETE"}),
    "dm_queue": frozenset({"SELECT", "DELETE"}),
    # operator AI connections: the request path never queries this directly —
    # the resolve step reads it via an in-process cache loaded on the system
    # engine (SELECT), and the secret-key rotation re-encrypts its key column on
    # the system engine (UPDATE). CRUD writes run owner-scoped as platform_owner
    # via RLS, not the system engine.
    "platform_ai_connections": frozenset({"SELECT", "UPDATE"}),
    # OIDC sync reads mappings; the settings endpoints manage them
    "oidc_claim_mappings": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # login provider registry (successor to app_settings.oidc_*): fully managed
    # on the system engine — login reads + provider CRUD via AdminSessionDep with
    # capability/ownership checks (as access_grants). Like oidc_claim_mappings, it
    # carries NO permissive RLS policy; the request path does not read provider
    # config.
    "auth_providers": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # provider client secret — read/written only by the system engine (provider
    # CRUD via AdminSessionDep + config.manage); no request-path grant
    "auth_provider_secrets": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # identity linking — resolved/created at login (pre-auth, by subject);
    # link/unlink go through the system engine only
    "federated_identities": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # IdP refresh token per identity link — read/rotated only by the system
    # engine (login + background group re-sync)
    "federated_identity_secrets": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # per-guild sign-in requirement — written via the guild-admin endpoint
    # (provider validation happens on the system engine)
    "guild_auth_policies": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # session/refresh store — validated pre-auth by refresh-token hash (user
    # unknown), so all session ops run on the system engine; request path revoked
    "auth_sessions": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # personal UI state — the system engine has no business here
    "user_view_preferences": None,
    "notifications": frozenset({"SELECT", "INSERT", "DELETE"}),
    # Authoring runs on the system engine because a draft is invisible to the
    # request path by policy — which is the point of the policy.
    "announcements": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # Receipts are written by the reader under their own role. The system
    # engine only ever removes them, when the announcement they name goes.
    "announcement_reads": frozenset({"SELECT", "DELETE"}),
    # The system engine stores, touches and prunes the pictures; the request
    # path reads them under its own role (a signed-in account may fetch any of
    # them). UPDATE is the dedupe touch — the same bytes uploaded twice keep
    # one row, and the second upload restarts the orphan clock on it.
    "announcement_images": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "user_tokens": frozenset({"SELECT", "INSERT", "DELETE"}),
    # Append-only. The system engine writes the record and the board reads it;
    # UPDATE and DELETE are granted to nobody at all, here included, because a
    # record that could be rewritten afterwards would not be one.
    "audit_events": frozenset({"SELECT", "INSERT"}),
    # the system engine delivers push itself (background digests, PAM notices),
    # and delivery bookkeeping is part of that: UPDATE stamps last_used_at,
    # DELETE prunes tokens FCM reports as unregistered
    "push_tokens": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # pre-auth credential store — validated by token_hash before the user is
    # known, so the lookup + create + deactivate all run on the system engine
    # (no request-path grant, no own-row policy), like auth_sessions
    "user_api_keys": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # SELECT/INSERT for the redemption path; DELETE for the shared jti janitor
    # (app.services.platform.jti_purge) that prunes expired rows — expired
    # jtis are inert (the JWT's own exp refuses replay before the blocklist is
    # read), so pruning never re-opens a replay window.
    "auto_delegation_jti_blocklist": frozenset({"SELECT", "INSERT", "DELETE"}),
    # billing boundary: writes happen ONLY under the dedicated (SET ROLE)
    # initiative_billing role, never the system engine. app_admin keeps
    # read-only visibility into the append-only evidence, and may prune
    # expired jtis (janitor); neither may mutate the event log.
    "billing_event_log": frozenset({"SELECT"}),
    "billing_jti_blocklist": frozenset({"SELECT", "DELETE"}),
    # migrations-only bookkeeping (the provisioning role owns it)
    "alembic_version": None,
    # lazily-created UNLOGGED backfill status singleton: read, seeded idle, and
    # claimed/updated on the system engine; rows are never deleted (the claim
    # UPDATE recycles the singleton). The service grants exactly this set at
    # table creation (app.services.storage_backfill._ensure_table).
    "storage_backfill_state": frozenset({"SELECT", "INSERT", "UPDATE"}),
}


# table -> the verbs the BARE LOGIN role (``app_user``) call sites use, or
# ``None``. The pre-routing / unauthenticated surface. Audited in migration
# 20260702_0130.
SHARED_TABLE_APP_USER_GRANTS: dict[str, frozenset[str] | None] = {
    # SELECT at the table level; UPDATE is column-scoped to every column except
    # ``role`` (migration 0144) so it does not appear here (a column grant lives
    # in the column ACL, not the table ACL). ``role`` is writable only by the
    # system engine — see security_invariants_test.
    "users": frozenset({"SELECT"}),
    "user_tokens": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # Written and read on the system engine only — the request path never
    # touches the log, in either direction.
    "audit_events": None,
    # system-engine-only credential store; the request path never touches it
    # (auth lookup + management endpoints run on app_admin), like auth_sessions
    "user_api_keys": None,
    "auto_delegation_jti_blocklist": frozenset({"SELECT", "INSERT"}),
    "app_settings": frozenset({"SELECT"}),
    # The catalog is read under a platform tier or a guild role, never by the
    # bare pre-routing login role — browsing the marketplace requires a session.
    "marketplace_listings": None,
    "marketplace_listing_versions": None,
    # Deployment wiring, holding the app's shared-secret ciphertext: managed on
    # the system engine and readable by the platform owner under RLS. The bare
    # pre-routing login role has no reason to see it, so it holds nothing.
    "app_service_registrations": None,
    # The app-service replay guard is spent entirely on the system engine, like
    # the billing blocklist; no request-path role reads or writes it.
    "app_service_nonces": None,
    # Refresh bookkeeping — system engine only, surfaced to an operator through
    # a capability-gated endpoint rather than read on the request path.
    "marketplace_registry_state": None,
    # Mirrored listing artwork stands in for the static image files this build
    # ships, so it is served exactly as they are: to anyone holding the digest,
    # before a session is routed. Bytes only, addressed by their own hash.
    "marketplace_media": frozenset({"SELECT"}),
    # A name and a face are public information here: any role may read any
    # avatar, and the row policies narrow writes to the caller's own. The bare
    # login role reads because the serve endpoint answers before routing.
    "user_avatars": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # A library belongs to a signed-in account, and the bare pre-routing login
    # role serves nobody in particular.
    "user_decorations": None,
    # A contacts list belongs to a signed-in account, and the bare pre-routing
    # login role serves nobody in particular.
    "profile_favorites": None,
    # Read and written on the authenticated platform-tier path, never before a
    # session is routed.
    "user_dm_settings": None,
    "user_dm_guild_optouts": None,
    "contact_grants": None,
    "user_ignores": None,
    # Same: the transport is reached on the authenticated platform-tier
    # path, never before a session is routed.
    "dm_devices": None,
    "dm_one_time_keys": None,
    "dm_conversations": None,
    "dm_conversation_members": None,
    "dm_queue": None,
    # operator AI connections are owner-managed + system-engine-read only; the
    # bare pre-routing login role never touches them
    "platform_ai_connections": None,
    "guilds": frozenset({"SELECT"}),
    # No TABLE grant: the bytes are the system engine's, and the endpoint that
    # serves them decides who may see which variant. The request path holds a
    # column-scoped SELECT on (guild_id, variant, sha256) instead — enough to
    # name a member's own guild images in their guild list, never enough to
    # read one. Column grants live in pg_attribute, not relacl, so they are
    # asserted separately (security_invariants_test).
    "guild_images": None,
    # Read-only for every request-path role, this one included — no login role
    # writes a guild's caps or its sign-in entitlement. RLS narrows the rows to
    # the caller's own guilds (plus a live PAM grant).
    "guild_administration": frozenset({"SELECT"}),
    "guild_invites": frozenset({"SELECT"}),
    "guild_memberships": frozenset({"SELECT"}),
    "access_grants": frozenset({"SELECT"}),
    # provider reads for the login page go via the system engine (AdminSessionDep),
    # not the bare login role
    "auth_providers": None,
    # client secrets are system-engine-only; no request role ever reads them
    "auth_provider_secrets": None,
    # own-row identity links are read on the authenticated (platform_<tier>)
    # path, not the bare pre-routing role
    "federated_identities": None,
    # IdP refresh tokens are system-engine-only; no request role ever reads them
    "federated_identity_secrets": None,
    # the guild-access gate reads the policy on the bare login role, pre-routing
    "guild_auth_policies": frozenset({"SELECT"}),
    # sessions are system-engine-only; the bare login role never touches them
    "auth_sessions": None,
    "notifications": None,
    # An announcement is shown to a signed-in account, so nothing about it is
    # read before routing.
    "announcements": None,
    "announcement_reads": None,
    "announcement_images": None,
    "oidc_claim_mappings": None,
    "push_tokens": None,
    "user_view_preferences": None,
    # billing tables are reached only via SET ROLE initiative_billing — the
    # bare login role holds nothing (fail-closed, like the guild schemas)
    "billing_event_log": None,
    "billing_jti_blocklist": None,
    "alembic_version": None,
    # system-engine-only status singleton; no request role reads it
    "storage_backfill_state": None,
}


def grant_sql(verbs: frozenset[str] | None) -> str | None:
    """Render a registry verb set as a canonical ``GRANT`` verb list (fixed
    order), or ``None`` when the role gets no access — lets a future migration
    emit the grant straight from the registry instead of re-typing verbs."""
    if not verbs:
        return None
    return ", ".join(v for v in _VERB_ORDER if v in verbs)
