"""Single source of truth for the audited per-table GRANTs the request-path
Postgres roles hold on the shared (``public``) tables.

Six roles are recorded here, one matrix each:

* **``app_admin``** — the system engine (BYPASSRLS trusted-batch actor). Its
  security boundary *is* exactly this grant set: a new shared table gives the
  system engine nothing until a decision here says otherwise.
  ``SHARED_TABLE_SYSTEM_GRANTS``.
* **``app_user``** — the bare login role serving the pre-routing /
  unauthenticated surface (RLS-enforced, no ``SET ROLE`` yet).
  ``SHARED_TABLE_APP_USER_GRANTS``.
* **``app_guild_base``** — the floor every ``guild_<id>`` role inherits, so
  the reach of a routed community session into ``public``. It is granted the
  other way round: the schema default gives it full DML on a new table, and the
  migration that adds the table takes back what it does not want.
  ``SHARED_TABLE_APP_GUILD_BASE_GRANTS`` records where that has landed, table
  by table, so a new table's reach is a decision here rather than a default.

* **``platform_base``** — the floor every ``platform_<tier>`` role inherits,
  granted the same way as the guild floor and recorded the same way.
  ``SHARED_TABLE_PLATFORM_BASE_GRANTS``.
* **``app_superadmin``** — the seat floor, which only the per-guild
  ``guild_<id>_superadmin`` role inherits. It takes no default privileges at
  all, so its matrix is a short list of yeses among a long list of ``None``.
  ``SHARED_TABLE_APP_SUPERADMIN_GRANTS``.
* **``app_install_base``** — the install floor, which only the per-guild
  ``guild_<id>_app`` role inherits: an installed app's reach into ``public``.
  Like the seat floor it takes no default privileges.
  ``SHARED_TABLE_APP_INSTALL_BASE_GRANTS``.

The read-only guild floor, ``app_guild_base_ro``, is derived from
``app_guild_base`` (``guild_base_ro_parity_test``) rather than listed.

Beside the six floors, a few tables are granted to the platform tiers
directly — to ``platform_<tier>`` itself rather than the ``platform_base``
floor every tier inherits. ``SHARED_TABLE_TIER_GRANTS`` records those by the
capability that earns them, as a policy in ``app.db.public_rls`` names its
capability rather than its tiers; ``tier_table_grants`` spells the tiers
holding each capability, and that render is what the catalog is held to.

Historically the first two matrices were the audited product of migrations
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

from app.core.capabilities import Capability, roles_with_capability
from app.db.public_rls import PLATFORM_TIER_ROLES, platform_tier
from app.db.tenancy import SHARED_TABLES

__all__ = [
    "SHARED_TABLE_SYSTEM_GRANTS",
    "SHARED_TABLE_APP_USER_GRANTS",
    "SHARED_TABLE_APP_GUILD_BASE_GRANTS",
    "SHARED_TABLE_PLATFORM_BASE_GRANTS",
    "SHARED_TABLE_APP_SUPERADMIN_GRANTS",
    "SHARED_TABLE_APP_INSTALL_BASE_GRANTS",
    "SHARED_TABLE_TIER_GRANTS",
    "NON_MODEL_SHARED_TABLES",
    "GRANTABLE_SHARED_TABLES",
    "VALID_GRANT_VERBS",
    "grant_sql",
    "tier_table_grants",
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
    # on SystemSessionDep, and provisioning creates the row with the guild. (The
    # verified billing path writes its three columns under its own role, which is
    # granted per column in migration 0178 and so is not listed here.) DELETE
    # rides the FK cascade off ``guilds``, but the guild-deletion path removes it
    # explicitly too.
    "guild_administration": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "guild_memberships": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # invite redemption reads/creates/updates; row removal rides the FK cascade
    "guild_invites": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "access_grants": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # Minted on first use, replaced by a re-issue, swept once the replaced
    # value stops resolving, and removed when the entity is erased.
    "identity_refs": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # singleton config: seeded + updated, never deleted
    "app_settings": frozenset({"SELECT", "INSERT", "UPDATE"}),
    # The settings singleton's stored credentials (migration 0362): seeded at
    # boot, written by the owner's email/storage routes, read by the mailer and
    # the storage client, and re-keyed by the secret-key rotation — all on the
    # system engine. A singleton like the row it belongs to, never deleted.
    "app_setting_secrets": frozenset({"SELECT", "INSERT", "UPDATE"}),
    # Marketplace catalog: the system engine is the only writer — boot seeding of
    # the shipped listings, and later the registry refresh job. DELETE is there
    # for versions a re-seed supersedes; a withdrawn *listing* is flipped to
    # available=false rather than removed, so installs keep their provenance.
    "marketplace_listings": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "marketplace_listing_versions": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # App service registrations: full DML on the system engine, which is the
    # only reader and writer — the owner-gated CRUD endpoints run on
    # SystemSessionDep (as access_grants and auth_providers do), boot
    # reconciliation upserts from APP_SERVICES_CONFIG, the verify path stamps
    # status/manifest_hash, and the signed-caller and delegation-key lookups
    # read it. No request-path role holds anything on it.
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
    # Consent to the deployment's terms. Registration runs on the system
    # engine, so the acceptance it records is written here; SELECT is for the
    # same path asking whether an account already has one. Nothing updates a
    # consent record, and the FK cascade off ``users`` is what removes it, so
    # neither UPDATE nor DELETE is granted.
    "legal_acceptances": frozenset({"SELECT", "INSERT"}),
    # An account is created on the system engine (registration, invite
    # redemption, provisioning from an identity provider), and its policy row is
    # seeded there from the operator default — hence INSERT. The other three are
    # written on the request path by the account holder; the system engine only
    # reads them for the guild-lifecycle sweeps and clears them on erasure.
    "user_dm_settings": frozenset({"SELECT", "INSERT", "DELETE"}),
    # An account's own payload is built on the system engine during
    # registration, which is the SELECT. DELETE is for erasure sweeps; the FK
    # cascade off ``users`` covers the ordinary case. The answer itself is
    # written on the request path by the account holder, so no INSERT or
    # UPDATE.
    "user_cookie_consent": frozenset({"SELECT", "DELETE"}),
    # Seeded when an account is created, read on every fan-out to decide who
    # wants what, and updated by the settings endpoint.
    "user_notification_prefs": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # Notification email waiting to go out. The worker owns this table: it
    # reads what is due, claims it, settles it and sweeps it, and the settings
    # endpoint rewrites the due times when somebody changes when they read.
    # The request path only ever appends (see SHARED_TABLE_APP_USER_GRANTS and
    # the base-role REVOKE in the migration).
    "email_outbox": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
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
    # the system engine (UPDATE). CRUD writes run under the tiers holding
    # config.manage (SHARED_TABLE_TIER_GRANTS), not the system engine.
    "platform_ai_connections": frozenset({"SELECT", "UPDATE"}),
    # OIDC sync reads mappings; the settings endpoints manage them
    "oidc_claim_mappings": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # login provider registry (successor to app_settings.oidc_*): fully managed
    # on the system engine — login reads + provider CRUD via SystemSessionDep with
    # capability/ownership checks (as access_grants). Like oidc_claim_mappings, it
    # carries NO permissive RLS policy; the request path does not read provider
    # config.
    "auth_providers": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # provider client secret — read/written only by the system engine (provider
    # CRUD via SystemSessionDep + config.manage); no request-path grant
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
    # which of the platform's providers a community signs in through — read at
    # login and written by the connection CRUD, both on the system engine
    "guild_provider_connections": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "platform_provider_defaults": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # session/refresh store — validated pre-auth by refresh-token hash (user
    # unknown), so all session ops run on the system engine; request path revoked
    "auth_sessions": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # resolving an address to an account is a pre-auth lookup, like a session
    "user_emails": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "user_email_assertions": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # counted while signing in, before anybody is authenticated
    "sign_in_locks": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # the second factor and what it is made of — enrolled, presented and
    # removed on the system engine, like the session store beside it
    # Registered, renamed, used and removed on the system engine — the request
    # path reaches a passkey only through a route running there, the same as
    # the second-factor tables below.
    "user_passkeys": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "user_totp": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "user_totp_secrets": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "mfa_recovery_codes": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # resolved by digest before the account is known, as a refresh token is
    "auth_challenges": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # personal UI state — the system engine has no business here
    "user_view_preferences": None,
    # UPDATE joined the set for the rolled-up direct-message line: the system
    # engine already creates and reaps these rows, and a rollup rewrites one
    # it wrote itself rather than reaching a row it could not otherwise touch.
    "notifications": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # Authoring runs under the tier holding announcements.manage (0365); the
    # system engine only reads every row's sections, for the orphan-picture
    # janitor (0366).
    "announcements": frozenset({"SELECT"}),
    # Receipts are written by the reader under their own role. The system
    # engine only ever removes them, when the announcement they name goes.
    "announcement_reads": frozenset({"SELECT", "DELETE"}),
    # The authoring tier stores and touches the pictures (0365); the system
    # engine's janitor reads their age and prunes the ones no announcement
    # names (0366). The request path reads them under its own role (a
    # signed-in account may fetch any of them).
    "announcement_images": frozenset({"SELECT", "DELETE"}),
    # Email-verification, password-reset and device tokens, matched by hash
    # before the account is known: minted, redeemed, slid, revoked and swept on
    # the system engine alone (0358), like auth_sessions and user_api_keys.
    "user_tokens": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # Every push is delivered through the system engine: it reads the
    # recipient's rows, UPDATE stamps last_used_at, DELETE prunes tokens FCM
    # reports as unregistered (0358).
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
    # 0358: every token path runs on the system engine, pre-routing included.
    "user_tokens": None,
    # Minted on the system engine, behind the surfaces that hand a reference to
    # an outside party. SELECT covers the table and one policy admits the rows:
    # ``purpose = 'client'``, the sector an account's own access token names it
    # by and every authenticated request resolves (migration 0267).
    "identity_refs": frozenset({"SELECT"}),
    # system-engine-only credential store; the request path never touches it
    # (auth lookup + management endpoints run on app_admin), like auth_sessions
    "user_api_keys": None,
    # Redemption reads and records a jti while authenticating the request,
    # before any routing.
    "auto_delegation_jti_blocklist": frozenset({"SELECT", "INSERT"}),
    "app_settings": frozenset({"SELECT"}),
    # The settings' stored credentials are the system engine's alone.
    "app_setting_secrets": None,
    # The catalog is read under a platform tier or a guild role, never by the
    # bare pre-routing login role — browsing the marketplace requires a session.
    "marketplace_listings": None,
    "marketplace_listing_versions": None,
    # Deployment wiring, holding the app's shared-secret ciphertext: read and
    # written on the system engine alone.
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
    # avatar. The bare login role reads because the serve endpoint answers
    # before routing; a picture is changed under a platform tier or on the
    # system engine.
    "user_avatars": frozenset({"SELECT"}),
    # A library belongs to a signed-in account, and the bare pre-routing login
    # role serves nobody in particular.
    "user_decorations": None,
    # A contacts list belongs to a signed-in account, and the bare pre-routing
    # login role serves nobody in particular.
    "profile_favorites": None,
    # Read and written by an account about itself, after its session is
    # routed. Nobody asks what somebody agreed to before then.
    "legal_acceptances": None,
    # Read and written on the authenticated platform-tier path, never before a
    # session is routed.
    "user_dm_settings": None,
    # Read and written by an account about itself, after its session is routed.
    # A visitor who has not signed in keeps their answer in their own browser
    # and asks the server for nothing.
    "user_cookie_consent": None,
    # Read under the account's own role after routing, never before it.
    "user_notification_prefs": None,
    # Written by a routed request for its recipient, never before routing and
    # never read back on the request path at all.
    "email_outbox": None,
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
    # Previewed and redeemed by code on the system engine; listed, issued and
    # withdrawn on a routed request (SHARED_TABLE_APP_GUILD_BASE_GRANTS).
    "guild_invites": None,
    "guild_memberships": frozenset({"SELECT"}),
    "access_grants": frozenset({"SELECT"}),
    # provider reads for the login page go via the system engine (SystemSessionDep),
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
    # the gate reads the narrowing here on every request, so the rule it
    # applies is the one in force now; a policy scopes a row to its own guild
    "guild_provider_connections": frozenset({"SELECT"}),
    "platform_provider_defaults": frozenset({"SELECT"}),
    # sessions are system-engine-only; the bare login role never touches them
    "auth_sessions": None,
    "user_emails": None,
    "user_email_assertions": None,
    "sign_in_locks": None,
    # the factor tables are system-engine-only; the bare login role never
    # touches them, and neither does any request-path role
    "user_passkeys": None,
    "user_totp": None,
    "user_totp_secrets": None,
    "mfa_recovery_codes": None,
    "auth_challenges": None,
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


# table -> the verbs the GUILD FLOOR (``app_guild_base``) holds, or ``None``.
# Every ``guild_<id>`` role inherits this set, so it is the reach of a routed
# community session into ``public``. Unlike the two above it was never granted
# table by table: the schema default gives a new table full DML, and the
# migration that adds a table takes back what it does not want (or the
# security tests catch one that forgot). Each entry below says which it is.
# Column-scoped grants live in the column ACL, not the table ACL, and are
# asserted separately in security_invariants_test.
SHARED_TABLE_APP_GUILD_BASE_GRANTS: dict[str, frozenset[str] | None] = {
    # 0144 and 0202 revoked every table-level verb from the guild floor: an
    # account's own record is read and written under a platform tier, and the
    # guild-routed path names a member through the guild_member_profiles view
    # (0220). Asserted by test_the_guild_path_holds_nothing_on_the_users_table.
    "users": None,
    # 0138 revoked INSERT and UPDATE at the table level. UPDATE survives as
    # column grants on the identity columns a community's admin edits (name,
    # description, banner, categories, is_community, has_adult_content,
    # show_member_names, updated_at — 0138, 0196, 0200, 0203).
    # guild_select_routed narrows SELECT to the routed community (0360). 0357
    # took DELETE back: creating, deleting and purging a community run on the
    # system engine.
    "guilds": frozenset({"SELECT"}),
    # 0179: read-only for every request-path role; a community reads its own
    # caps and plan label (guild_administration_select_routed).
    "guild_administration": frozenset({"SELECT"}),
    # 0145 revoked UPDATE — ``role`` is the system engine's column — and 0266
    # re-granted it on ``position`` alone, as a column grant. 0354 took INSERT
    # back: joining is the system engine's (invite redemption, a community
    # join, sign-in sync). What remains at the table level is leaving (DELETE
    # of the reader's own row) and reading the routed community's roster
    # (guild_memberships_select_routed).
    "guild_memberships": frozenset({"SELECT", "DELETE"}),
    # Listed, issued and withdrawn on a routed request. The three guild_*
    # policies admit an administrator of the invite's community — by the
    # membership row, or by a live settings grant at either rung. 0357 took
    # UPDATE back: an invite is changed only by redemption and erasure, on the
    # system engine.
    "guild_invites": frozenset({"SELECT", "INSERT", "DELETE"}),
    # 0146 moved every write to the system engine for all request-path roles
    # (test_access_grants_are_writable_only_by_the_system_engine). SELECT is
    # narrowed to the reader's own grants by access_grants_self.
    "access_grants": frozenset({"SELECT"}),
    # 0338: the credential is the system engine's from creation to deletion.
    # 0249: minted and resolved on the system engine and the bare login role.
    "identity_refs": None,
    # Deployment settings are read from inside a community as from anywhere
    # (app_settings_read, TO public); writes are the owner's, under RLS.
    "app_settings": frozenset({"SELECT"}),
    # 0362 took the schema default back: the system engine's alone.
    "app_setting_secrets": None,
    # 0164: the catalog is browsed under a guild role or a platform tier.
    "marketplace_listings": frozenset({"SELECT"}),
    "marketplace_listing_versions": frozenset({"SELECT"}),
    "app_service_registrations": None,
    "app_service_nonces": None,
    "marketplace_registry_state": None,
    # 0360: served on the bare login role alone.
    "marketplace_media": None,
    # 0200: no table grant; the routed path holds a column-scoped SELECT on
    # (guild_id, variant, sha256), asserted in security_invariants_test, over
    # the routed community's rows (guild_image_member_read_routed).
    "guild_images": None,
    # 0360: served on the bare login role and changed under a platform tier; a
    # routed payload names the picture by its serving URL.
    "user_avatars": None,
    # 0360: a library is listed, installed and worn under a platform tier.
    "user_decorations": None,
    # Platform-tier path only: every policy on these is TO platform_base, and
    # the migration that added each took the schema default back.
    "profile_favorites": None,
    "legal_acceptances": None,
    "user_dm_settings": None,
    # 0360: an account's answer is read and recorded under a platform tier.
    "user_cookie_consent": None,
    # 0360: read and changed under a platform tier; delivery reads a
    # recipient's settings on the system engine.
    "user_notification_prefs": None,
    # 0320: a routed request appends the notification email for its recipient;
    # reading, claiming and settling are the worker's, on the system engine.
    "email_outbox": frozenset({"INSERT"}),
    # 0225: the direct-message transport and its reach tables grant the guild
    # floor nothing; every policy on them is TO platform_base.
    "user_dm_guild_optouts": None,
    "contact_grants": None,
    "user_ignores": None,
    "dm_devices": None,
    "dm_one_time_keys": None,
    "dm_conversations": None,
    "dm_conversation_members": None,
    "dm_queue": None,
    # Owner-managed under RLS on the platform path; read by the system engine.
    "platform_ai_connections": None,
    # Read at sign-in and written by the seat's claim-rule routes, both on the
    # system engine; 0354 took the schema default back from both floors.
    "oidc_claim_mappings": None,
    # 0131, 0133, 0142: the login provider registry, its secrets and the
    # identity links are the system engine's; each migration took the schema
    # default back from both floors.
    "auth_providers": None,
    "auth_provider_secrets": None,
    "federated_identities": None,
    "federated_identity_secrets": None,
    # 0147 granted SELECT: the routed community's gate reads its requirement
    # (guild_auth_policies_routed_read, 0360). 0297 added the three writes and
    # 0349 moved them to app_superadmin, the floor only a seat route inherits.
    "guild_auth_policies": frozenset({"SELECT"}),
    # 0308: the routed community's gate reads its connections
    # (guild_provider_connections_routed_read, 0360); the writes are the
    # system engine's.
    "guild_provider_connections": frozenset({"SELECT"}),
    "platform_provider_defaults": frozenset({"SELECT"}),
    # 0132, 0261, 0262, 0290, 0307: sessions, addresses, factors and
    # challenges are resolved on the system engine before an account is
    # known; each migration took the schema default back from both floors.
    "auth_sessions": None,
    "user_emails": None,
    "user_email_assertions": None,
    "sign_in_locks": None,
    "user_passkeys": None,
    "user_totp": None,
    "user_totp_secrets": None,
    "mfa_recovery_codes": None,
    "auth_challenges": None,
    # 0360: personal UI state, read and written under a platform tier.
    "user_view_preferences": None,
    # 0245 records the decision: a notification is written by the actor for
    # its recipient on the routed session, in the same transaction as the
    # content that caused it, and the table carries no policy for the request
    # path. Reading and dismissing run under a platform tier.
    "notifications": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # 0360: announcements, their receipts and their pictures are read under a
    # platform tier.
    "announcements": None,
    "announcement_reads": None,
    "announcement_images": None,
    # 0156: system-engine-only, no request-path grant.
    "user_api_keys": None,
    # 0358: tokens are the system engine's, and a push is delivered on it; the
    # guild floor reaches neither table.
    "user_tokens": None,
    "push_tokens": None,
    # 0357: redemption runs on the bare login role and its janitor on the
    # system engine; neither floor reaches the table.
    "auto_delegation_jti_blocklist": None,
    # 0134: the billing boundary took both floors back; only the SET ROLE
    # initiative_billing role reaches these.
    "billing_event_log": None,
    "billing_jti_blocklist": None,
    "alembic_version": None,
    # _ensure_table takes both floors back at creation
    # (app.services.storage_backfill).
    "storage_backfill_state": None,
}


# table -> the verbs the PLATFORM FLOOR (``platform_base``) holds, or ``None``.
# Every ``platform_<tier>`` role inherits this set, so it is the reach of an
# unrouted, authenticated request into ``public``. Granted the same way as the
# guild floor above — the schema default gives a new table full DML and the
# migration that adds it takes back what it should not have — and recorded here
# for the same reason: so a table's reach is a decision rather than a default.
# Read off the live catalog when it was first written, table by table.
SHARED_TABLE_PLATFORM_BASE_GRANTS: dict[str, frozenset[str] | None] = {
    "users": frozenset({"SELECT"}),
    "guilds": frozenset({"SELECT"}),
    "guild_administration": frozenset({"SELECT"}),
    # 0357 took DELETE back: leaving routes into the community first, so the
    # row goes on the guild floor.
    "guild_memberships": frozenset({"SELECT"}),
    # 0357: an invite is the community's, reached on a routed request or the
    # system engine.
    "guild_invites": None,
    "access_grants": frozenset({"SELECT"}),
    "identity_refs": None,
    "app_settings": frozenset({"SELECT"}),
    "app_setting_secrets": None,
    "marketplace_listings": frozenset({"SELECT"}),
    "marketplace_listing_versions": frozenset({"SELECT"}),
    "app_service_registrations": None,
    "app_service_nonces": None,
    "marketplace_registry_state": None,
    # 0360: served on the bare login role alone.
    "marketplace_media": None,
    "guild_images": None,
    "user_avatars": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "user_decorations": frozenset({"SELECT"}),
    "profile_favorites": frozenset({"SELECT", "INSERT", "DELETE"}),
    "legal_acceptances": frozenset({"SELECT", "INSERT"}),
    "user_dm_settings": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "user_cookie_consent": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "user_notification_prefs": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "email_outbox": frozenset({"INSERT"}),
    "user_dm_guild_optouts": frozenset({"SELECT", "INSERT", "DELETE"}),
    "contact_grants": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "user_ignores": frozenset({"SELECT", "INSERT", "DELETE"}),
    "dm_devices": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "dm_one_time_keys": frozenset({"SELECT", "INSERT", "DELETE"}),
    "dm_conversations": frozenset({"SELECT", "INSERT", "DELETE"}),
    "dm_conversation_members": frozenset({"SELECT", "INSERT", "DELETE"}),
    "dm_queue": frozenset({"SELECT", "INSERT", "DELETE"}),
    "platform_ai_connections": None,
    "oidc_claim_mappings": None,
    "auth_providers": None,
    "auth_provider_secrets": None,
    "federated_identities": frozenset({"SELECT"}),
    "federated_identity_secrets": None,
    "guild_auth_policies": frozenset({"SELECT"}),
    "guild_provider_connections": frozenset({"SELECT"}),
    "platform_provider_defaults": frozenset({"SELECT"}),
    "auth_sessions": None,
    "user_emails": None,
    "user_email_assertions": None,
    "sign_in_locks": None,
    "user_passkeys": None,
    "user_totp": None,
    "user_totp_secrets": None,
    "mfa_recovery_codes": None,
    "auth_challenges": None,
    "user_view_preferences": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # The reader's own bell: listed, marked read and dismissed. 0357 took
    # INSERT back; a notification is written on a routed request or the system
    # engine.
    "notifications": frozenset({"SELECT", "UPDATE", "DELETE"}),
    "announcements": frozenset({"SELECT"}),
    "announcement_reads": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "announcement_images": frozenset({"SELECT"}),
    "user_api_keys": None,
    # 0358: tokens are the system engine's alone.
    "user_tokens": None,
    # A device's own registration: the upsert reads and writes the row it
    # conflicts on and returns it, and unregistering deletes it. The policies
    # admit the account's own rows (0358).
    "push_tokens": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "auto_delegation_jti_blocklist": None,
    "billing_event_log": None,
    "billing_jti_blocklist": None,
    "alembic_version": None,
    "storage_backfill_state": None,
}


# table -> the verbs the SEAT FLOOR (``app_superadmin``) holds, or ``None``.
# Only ``guild_<id>_superadmin`` inherits it, and a request assumes that role
# by asking for the seat and holding it. Unlike the three floors above it takes
# no default privileges, so every entry here is an explicit grant in a
# migration and everything else is ``None`` by construction.
SHARED_TABLE_APP_SUPERADMIN_GRANTS: dict[str, frozenset[str] | None] = {
    "users": None,
    # No TABLE grant: a community's name, its icon and its lifecycle status are
    # not the seat's. It holds a column-scoped UPDATE on the six switches its
    # own routes set — what may be used to reach the community, and what its
    # notifications may leave carrying (migration 20260923_0355). Column grants
    # live in pg_attribute, not relacl, so they are asserted separately
    # (security_invariants_test). SELECT comes from app_guild_base_ro, which
    # guild_<id>_superadmin also inherits.
    "guilds": None,
    "guild_administration": None,
    "guild_memberships": None,
    "guild_invites": None,
    "access_grants": None,
    "identity_refs": None,
    "app_settings": None,
    "app_setting_secrets": None,
    "marketplace_listings": None,
    "marketplace_listing_versions": None,
    "app_service_registrations": None,
    "app_service_nonces": None,
    "marketplace_registry_state": None,
    "marketplace_media": None,
    "guild_images": None,
    "user_avatars": None,
    "user_decorations": None,
    "profile_favorites": None,
    "legal_acceptances": None,
    "user_dm_settings": None,
    "user_cookie_consent": None,
    "user_notification_prefs": None,
    "email_outbox": None,
    "user_dm_guild_optouts": None,
    "contact_grants": None,
    "user_ignores": None,
    "dm_devices": None,
    "dm_one_time_keys": None,
    "dm_conversations": None,
    "dm_conversation_members": None,
    "dm_queue": None,
    "platform_ai_connections": None,
    "oidc_claim_mappings": None,
    "auth_providers": None,
    "auth_provider_secrets": None,
    "federated_identities": None,
    "federated_identity_secrets": None,
    "guild_auth_policies": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "guild_provider_connections": None,
    "platform_provider_defaults": None,
    "auth_sessions": None,
    "user_emails": None,
    "user_email_assertions": None,
    "sign_in_locks": None,
    "user_passkeys": None,
    "user_totp": None,
    "user_totp_secrets": None,
    "mfa_recovery_codes": None,
    "auth_challenges": None,
    "user_view_preferences": None,
    "notifications": None,
    "announcements": None,
    "announcement_reads": None,
    "announcement_images": None,
    "user_api_keys": None,
    "user_tokens": None,
    "push_tokens": None,
    "auto_delegation_jti_blocklist": None,
    "billing_event_log": None,
    "billing_jti_blocklist": None,
    "alembic_version": None,
    "storage_backfill_state": None,
}


# table -> the verbs the INSTALL FLOOR (``app_install_base``) holds, or
# ``None``. Only ``guild_<id>_app`` inherits it, the role an installed app's
# request assumes. Like the seat floor it takes no default privileges, so every
# entry here is an explicit grant in a migration and everything else is
# ``None`` by construction.
SHARED_TABLE_APP_INSTALL_BASE_GRANTS: dict[str, frozenset[str] | None] = {
    "users": None,
    # No TABLE grant: a column-scoped SELECT on (id, status), which the
    # install standing statement reads for the routed community alone
    # (install_reads_its_guild; migration 20260924_0379). Column grants live in
    # pg_attribute, not relacl, so they are asserted separately
    # (install_standing_test).
    "guilds": None,
    "guild_administration": None,
    "guild_memberships": None,
    "guild_invites": None,
    "access_grants": None,
    "identity_refs": None,
    "app_settings": None,
    "app_setting_secrets": None,
    "marketplace_listings": None,
    "marketplace_listing_versions": None,
    # No TABLE grant: a column-scoped SELECT on (public_id, listing_uid,
    # enabled, status), for the registration the install's token names
    # (install_reads_its_registration; migration 20260924_0379). Asserted in
    # install_standing_test beside the one on guilds.
    "app_service_registrations": None,
    "app_service_nonces": None,
    "marketplace_registry_state": None,
    "marketplace_media": None,
    "guild_images": None,
    "user_avatars": None,
    "user_decorations": None,
    "profile_favorites": None,
    "legal_acceptances": None,
    "user_dm_settings": None,
    "user_cookie_consent": None,
    "user_notification_prefs": None,
    "email_outbox": None,
    "user_dm_guild_optouts": None,
    "contact_grants": None,
    "user_ignores": None,
    "dm_devices": None,
    "dm_one_time_keys": None,
    "dm_conversations": None,
    "dm_conversation_members": None,
    "dm_queue": None,
    "platform_ai_connections": None,
    "oidc_claim_mappings": None,
    "auth_providers": None,
    "auth_provider_secrets": None,
    "federated_identities": None,
    "federated_identity_secrets": None,
    "guild_auth_policies": None,
    "guild_provider_connections": None,
    "platform_provider_defaults": None,
    "auth_sessions": None,
    "user_emails": None,
    "user_email_assertions": None,
    "user_passkeys": None,
    "user_totp": None,
    "user_totp_secrets": None,
    "mfa_recovery_codes": None,
    "auth_challenges": None,
    "user_view_preferences": None,
    "notifications": None,
    "announcements": None,
    "announcement_reads": None,
    "announcement_images": None,
    "user_api_keys": None,
    "user_tokens": None,
    "push_tokens": None,
    "auto_delegation_jti_blocklist": None,
    "billing_event_log": None,
    "billing_jti_blocklist": None,
    "alembic_version": None,
    "storage_backfill_state": None,
}


# table -> {capability: verbs} granted to the ``platform_<tier>`` roles holding
# that capability, directly rather than through ``platform_base``. A table not
# named here grants no tier anything of its own; what a tier reads beyond this
# comes from the platform floor above.
SHARED_TABLE_TIER_GRANTS: dict[str, dict[Capability, frozenset[str]]] = {
    # Deployment configuration is written under the tier that manages it
    # (app_settings_owner); every request role reads it through its floor.
    "app_settings": {
        Capability.CONFIG_MANAGE: frozenset({"INSERT", "UPDATE", "DELETE"}),
    },
    # The operator's AI connections, managed under the same tier
    # (platform_ai_connections_owner, migration 0155).
    "platform_ai_connections": {
        Capability.CONFIG_MANAGE: frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    },
    # Announcements and their pictures are written under the tier that manages
    # them (announcements_manage, announcement_images_manage; migration 0365).
    # Every tier reads them through its floor.
    "announcements": {
        Capability.ANNOUNCEMENTS_MANAGE: frozenset({"INSERT", "UPDATE", "DELETE"}),
    },
    "announcement_images": {
        Capability.ANNOUNCEMENTS_MANAGE: frozenset({"INSERT", "UPDATE", "DELETE"}),
    },
}


def tier_table_grants() -> dict[str, dict[str, frozenset[str]]]:
    """``SHARED_TABLE_TIER_GRANTS`` spelled as tiers: every ``platform_<tier>``
    role, unprefixed, with the verbs it holds per table. A tier holding no
    capability named there maps to an empty dict."""
    rendered: dict[str, dict[str, frozenset[str]]] = {
        role: {} for role in PLATFORM_TIER_ROLES
    }
    for table, by_capability in SHARED_TABLE_TIER_GRANTS.items():
        for capability, verbs in by_capability.items():
            for role in roles_with_capability(capability):
                tables = rendered[platform_tier(role)]
                tables[table] = tables.get(table, frozenset()) | verbs
    return rendered


def grant_sql(verbs: frozenset[str] | None) -> str | None:
    """Render a registry verb set as a canonical ``GRANT`` verb list (fixed
    order), or ``None`` when the role gets no access — lets a future migration
    emit the grant straight from the registry instead of re-typing verbs."""
    if not verbs:
        return None
    return ", ".join(v for v in _VERB_ORDER if v in verbs)
