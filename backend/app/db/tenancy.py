"""Authoritative table classification for schema-per-guild multi-tenancy.

Single source of truth for *where each table lives* and *how it is access-scoped*
once each guild becomes its own PostgreSQL schema. Two orthogonal levels:

**Level 1 — schema placement:**

- **Shared tables** stay in the ``public`` schema — identity, the tenancy
  roster, platform config, and per-user / cross-guild concerns read *without* a
  guild context (login, "list my guilds", platform staff, SSO auto-join, the
  notification inbox). Listed explicitly in ``SHARED_TABLES``.
- **Guild-scoped tables** move into a per-guild schema (``guild_<id>``) — the
  actual tenant content. ``GUILD_SCOPED_TABLES`` is *derived* as
  ``INITIATIVE_SCOPED_TABLES | GUILD_LEVEL_TABLES`` (level 2), so a guild table
  is declared in exactly one of those — never copied here.

**Level 2 — initiative access boundary (within a guild schema):**

- **Initiative-scoped** tables carry the four ``initiative_member_*`` RLS
  policies deferring to ``initiative_access(...)``. They are declared once
  in ``app.db.initiative_rls.INITIATIVE_PATHS`` (table -> initiative path);
  ``INITIATIVE_SCOPED_TABLES`` is the keys of that registry, and
  the RLS DDL is rendered from it at provisioning time (``app.db.guild_ddl``).
  So adding an initiative-scoped table is a *single* edit (a path in
  ``initiative_rls``).
- **Guild-level** tables (``GUILD_LEVEL_TABLES``) are exempt — guild-wide,
  structural, or own-row — protected only by the schema boundary (the
  ``guild_<id>`` role). Adding one here is the explicit "not initiative-scoped"
  decision.

Every ``table=True`` model MUST land in ``SHARED_TABLES`` or (via level 2)
``GUILD_SCOPED_TABLES``. ``tenancy_test.py`` enforces this against
``SQLModel.metadata`` so a new table can't be added without a placement
decision — an unclassified guild-scoped table would silently leak across
tenants. See ``history/schema-per-guild-design.md`` (§2 Table classification).
"""

from __future__ import annotations

from app.db.initiative_rls import INITIATIVE_SCOPED_TABLES

__all__ = [
    "SHARED_TABLES",
    "GUILD_LEVEL_TABLES",
    "MANAGED_TABLES",
    "OWN_ROW_TABLES",
    "CREATED_BY_EXEMPT_TABLES",
    "INITIATIVE_SCOPED_TABLES",
    "GUILD_SCOPED_TABLES",
    "ALL_CLASSIFIED_TABLES",
    "is_guild_scoped",
    "is_shared",
    "is_initiative_scoped",
]

# --- Shared (stay in the ``public`` schema) ---------------------------------
# Read without a guild context, or inherently cross-guild. Must never be
# duplicated per schema.
SHARED_TABLES: frozenset[str] = frozenset(
    {
        # Identity & per-user auth/devices (one user spans many guilds)
        "users",
        "user_api_keys",
        "user_tokens",
        "push_tokens",
        "user_view_preferences",  # personal UI state (filters/sort/view-mode)
        # What one account wants to be told about. Off ``users`` on purpose:
        # that table is read whole by the platform tiers.
        "user_notification_prefs",
        # Notification email waiting to go out. Per-account and cross-guild
        # like the settings above: one message can gather rows from every
        # community somebody is in, so it belongs to none of them.
        "email_outbox",
        # The picture on a user's profile. Public-plane identity like the row
        # it hangs off: one user spans guilds, and the bytes are served to
        # anyone holding the URL.
        "user_avatars",
        # What one account may dress its profile in beyond what ships with the
        # app. Personal and cross-guild, like the row it hangs off.
        "user_decorations",
        # Who one account has starred on My Contacts. Personal, cross-guild
        # and one-directional: the list is the holder's, and it may name
        # people they share no guild with.
        "profile_favorites",
        # What an account agreed to when it was created. A deployment's terms
        # are the platform's, not any one community's, so the record of
        # accepting them belongs beside the account rather than in a schema.
        "legal_acceptances",
        # Who may ask to message an account, who it has agreed something with,
        # and who it has chosen not to hear from. All three are per-account and
        # cross-guild, like the starred list above, and none of them is any
        # guild's business.
        "user_dm_settings",
        # What an account allows to be kept in a browser. Per-account and
        # cross-guild like the rest here: the question is about the deployment,
        # not about any one community.
        "user_cookie_consent",
        "user_dm_guild_optouts",
        "contact_grants",
        "user_ignores",
        # The transport those four gate: a directory of public keys, a
        # roster of who is talking to whom, and ciphertext waiting to be
        # collected. Per-account and cross-guild like the rest, and not one
        # of them holds anything a reader could open.
        "dm_devices",
        "dm_one_time_keys",
        "dm_conversations",
        "dm_conversation_members",
        "dm_queue",
        # What a moderator did, and to whom. Cross-guild platform security
        # that has to outlive any guild — and every reference in it is a plain
        # integer, so it outlives the accounts it names too.
        # What outside parties — a payment processor, an installed app —
        # call a user or a guild. One per purpose, so no two parties hold
        # the same value for the same entity. Cross-guild and pre-routing,
        # like the accounts and guilds it names.
        "identity_refs",
        # Tenancy roster — must be readable *before* a request is routed
        "guilds",
        # The operator-set half of a guild (caps / plan label / sign-in
        # entitlement), split off ``guilds`` so identity and administration
        # carry different grants. Shared, like the guild row it hangs off.
        "guild_administration",
        # The pictures a guild is known by — its icon, and the two renditions
        # of its banner. Identity, like the name and description they sit
        # beside, and read by strangers browsing the directory, who hold no
        # role that could reach a guild schema.
        "guild_images",
        "guild_memberships",
        # Consumed pre-membership / pre-routing
        "guild_invites",  # looked up by token before the user is a member
        "oidc_claim_mappings",  # SSO auto-join rules, read across all guilds at login
        # Auth/login foundation — one user's identities span guilds; provider
        # registry is read pre-routing at login.
        "auth_providers",  # login provider registry; every row is the operator's
        "auth_provider_secrets",  # provider client secret; app_admin-only companion
        "federated_identities",  # (provider, subject) -> user links
        "federated_identity_secrets",  # IdP refresh token; app_admin-only companion
        "auth_sessions",  # session/refresh store (JWT sid = row id); app_admin-only
        "user_emails",  # the addresses an account signs in with; app_admin-only
        "user_email_assertions",  # which providers assert them; app_admin-only
        "sign_in_locks",  # recent wrong answers per account; app_admin-only
        # The account's own second factor, the seed behind it, and the codes
        # that stand in for it. All app_admin-only: presented while signing in.
        "user_totp",
        "user_totp_secrets",
        "mfa_recovery_codes",
        "auth_challenges",  # a sign-in between its password and its code
        # WebAuthn credentials. app_admin-only for the same reason as the rest
        # of this group: an assertion arrives before any account is known.
        "user_passkeys",
        "guild_auth_policies",  # per-guild sign-in requirement, read pre-routing by the gate
        # Which of the platform's providers a community signs in through, and
        # the tenant it narrows one to. Read at login on the system engine.
        "guild_provider_connections",
        # The same arrangement, answered once for a community that has not.
        # Read by the gate on the request path, like the connections it
        # stands in for.
        "platform_provider_defaults",
        # Platform-wide
        "app_settings",  # OIDC / SMTP / branding config
        "app_setting_secrets",  # the settings' stored credentials; app_admin-only
        # Deployment-wide notices and what each person has done with them. One
        # announcement is shown in every guild and read by an account, not by a
        # membership, so none of the three has a guild to live in.
        "announcements",
        "announcement_reads",
        "announcement_images",
        # Marketplace catalog: what is installable, platform-wide. Holds no
        # guild_id by design — the catalog never records who installed what.
        "marketplace_listings",
        "marketplace_listing_versions",
        # Deployment-level wiring for external app services (listing, URL,
        # public keys, operator-conferred grants). Platform-wide by definition —
        # one row per app, never per guild — and owner-managed.
        "app_service_registrations",
        # Who publishes those apps: one row per public_id prefix, with the
        # switch that stops every app under it. Deployment configuration.
        "publishers",
        # Spent client-assertion jtis from the app token endpoint. Hangs off a
        # registration, which is platform-wide.
        "app_assertion_jtis",
        # Registry client state: the TUF metadata this deployment last
        # verified, how the last refresh went, and the artwork its listings
        # named, kept locally so listing media is served from here.
        # Operator/system state, no guild.
        "marketplace_tuf_metadata",
        "marketplace_registry_status",
        "marketplace_media",
        "platform_ai_connections",  # operator AI connections (platform config mode)
        "access_grants",  # PAM — inherently cross-guild (request -> approve -> scoped)
        "notifications",  # per-user inbox spanning guilds; carries its own place
        # Billing write boundary (external billing service, initiative_billing role)
        "billing_event_log",  # idempotency claim + append-only audit; weak guild ref
        "billing_jti_blocklist",  # one-shot billing service-JWT redemption
    }
)

# --- Guild-scoped, NOT initiative-scoped (level 2 exemptions) ----------------
# Guild-wide, structural, or own-row tables protected only by the schema
# boundary. The complement of this set within a guild schema is
# ``INITIATIVE_SCOPED_TABLES`` (declared in ``app.db.initiative_rls``).
GUILD_LEVEL_TABLES: frozenset[str] = frozenset(
    {
        # NB: "guild-level" = not initiative-membership-gated. Two members here
        # (initiatives, tags) are soft-deletable and so DO carry RLS — but only to
        # host the admin-only purge guard (guild_level_open allow-all +
        # soft_delete_admin_purge), never a membership scope. See the rendered RLS DDL.
        # Guild-wide config / data (no initiative scope)
        "guild_settings",
        # Installed apps: guild-wide by definition, and readable by any member —
        # the sidebar has to know an app is there. Installing, configuring and
        # removing are gated at the endpoint (the seat); what a member may do
        # *inside* an app is decided by that instance's own grants, not by this
        # row. Not in SEAT_TABLES: a member adding a guild calendar locks the
        # install and appends to its ``artifacts``, and a member disconnecting
        # their own account locks it too.
        "guild_apps",
        # Where an install appears, one row per initiative, with the roles
        # allowed to open it there. A fact about the install rather than
        # initiative content: read within the schema, written by the seat
        # (SEAT_TABLES below).
        "app_placements",
        "guild_ai_connections",  # the seat's AI connections (guild config mode);
        # guild-wide config, no initiative scope, written by the seat (SEAT_TABLES
        # below). The api_key ciphertext is never returned by the API (reads
        # expose only has_key).
        "webhook_deliveries",  # per-subscription delivery ledger, no initiative of
        # its own; read through its subscription (LEDGER_TABLES below).
        "tags",  # tags are guild-level, shared across initiatives (purge-guarded)
        "uploads",  # guild blob store: no FK to any initiative entity (documents
        # reference blobs by file_url string, and a blob can be pinned by
        # documents across initiatives), so it can't use initiative_access;
        # blob *content* access is already gated at the document layer.
        # Structural initiative tables — guild-scoped for reading (a roster is
        # read by its co-members, and the standing statement reads it before
        # any standing exists), written by the initiative's managers: see
        # MANAGED_TABLES below and the rendered RLS DDL header.
        "initiatives",  # purge-guarded (admin-only DELETE) as well
        "initiative_members",
        "initiative_roles",
        "initiative_role_permissions",
        # Join requests: the requester is by definition NOT yet a member, so an
        # initiative-membership row gate would hide their own request from them
        # — the same reasoning that keeps initiative_members structural. Who may
        # read which rows is an app-layer contract (requester sees their own,
        # managers see their initiative's), pinned by tests.
        "initiative_join_requests",
        # Own-row tables (also listed in OWN_ROW_TABLES below): guild-level
        # placement, but rows belong to ONE user and carry own_row_* policies.
        "export_jobs",  # a job may span initiatives ("export all my tasks"), so
        # it can't use initiative_access; the row leaks selector text and gates
        # the artifact download, so it must not be guild-wide-readable either.
        "import_jobs",  # same shape as export_jobs: a backup import spans
        # initiatives, and the row's options/plan/report text plus the staged
        # payload it gates must not be guild-wide-readable.
        # Member-owned AI rows (also in OWN_ROW_TABLES): a member's own key /
        # connection preference. One member must not read another's key ciphertext
        # or pref, so these carry own_row_* policies (owner OR guild admin).
        "guild_ai_member_keys",
        "guild_ai_member_prefs",
        # A member's own connection to an installed app's vendor. No FK to any
        # initiative — an app is guild-wide — so it can't use initiative_access.
        # Rows belong to ONE member and hold that member's credential, so it
        # carries own_row_* policies: the owner manages their own, and a guild
        # admin manages every one in their guild (a personal connection is
        # guild-governed access, not private property). The ciphertext is never
        # returned by the API to anyone, admin included.
        "guild_app_user_connections",
        # A member's answer to an installed app asking to act as them, one per
        # purpose. The same shape as the connections beside it: no FK to any
        # initiative is required (a purpose may be app-wide), one owner per
        # row, and the community's administration reads and revokes, so
        # own_row_* policies. A member token's standing reads the member's own
        # row for its install.
        "app_member_consents",
    }
)

# --- Managed overlay on the structural initiative tables ----------------------
# Guild-level tables whose rows are an initiative's own structure: table -> the
# SQL expression a row's initiative is read from. Reading stays open within the
# schema; writing is the initiative's managers', the community's admin's, a
# settings rung's beside a read_write grant, or the system engine's — rendered
# as ``managed_*`` policies by ``app.db.guild_ddl.render_guild_rls_ddl`` from
# the standing (``app.manager_initiatives``), so the membership table is gated
# by a value the seam computed rather than by a read of itself. Every entry
# here MUST also be in ``GUILD_LEVEL_TABLES`` — enforced in ``tenancy_test.py``.
MANAGED_TABLES: dict[str, str] = {
    "initiatives": "id",
    "initiative_members": "initiative_id",
    "initiative_roles": "initiative_id",
    "initiative_role_permissions": (
        "(SELECT r.initiative_id FROM initiative_roles r WHERE r.id = initiative_role_id)"
    ),
}

# --- Own-row overlay on guild-level tables -----------------------------------
# Guild-level tables whose rows belong to ONE user: table -> owner FK column.
# These get per-command ``own_row_*`` RLS policies (owner OR routed guild
# admin) rendered by ``app.db.guild_ddl.render_guild_rls_ddl`` — unlike the
# allow-all ``guild_level_open`` tables, this IS a row gate. Every entry here
# MUST also be in ``GUILD_LEVEL_TABLES`` (that's the schema-placement decision;
# this is the policy overlay) — enforced in ``tenancy_test.py``.
OWN_ROW_TABLES: dict[str, str] = {
    "export_jobs": "created_by",
    "import_jobs": "created_by",
    "guild_ai_member_keys": "user_id",
    "guild_ai_member_prefs": "user_id",
    "guild_app_user_connections": "user_id",
    "app_member_consents": "user_id",
}

# --- Seat overlay on guild-level tables ---------------------------------------
# Guild-level configuration the community's seat holds. Read within the schema:
# a member's AI request reads the connection it runs on, and opening an app
# reads where it is placed. Written by the seat — the membership row's
# superadmin, or a superadmin settings grant beside a read_write content grant
# — or the system engine; the same answer the routes in front of it ask for.
# A table a trigger also writes names that in
# ``app.db.guild_ddl._SEAT_TRIGGER_WRITTEN_INSERT``. Rendered as ``seat_*`` policies by
# ``app.db.guild_ddl.render_guild_rls_ddl``. Every entry here MUST also be in
# ``GUILD_LEVEL_TABLES`` — enforced in ``tenancy_test.py``.
SEAT_TABLES: frozenset[str] = frozenset({"app_placements", "guild_ai_connections"})

# --- Ledger overlay on guild-level tables -------------------------------------
# Guild-level bookkeeping a system job keeps about a parent row: table ->
# (parent table, FK column). Read through the parent, so a row is visible to
# whoever the parent's own policy shows the parent to; written by the system
# engine alone. Rendered as ``ledger_*`` policies by
# ``app.db.guild_ddl.render_guild_rls_ddl``. Every entry here MUST also be in
# ``GUILD_LEVEL_TABLES`` — enforced in ``tenancy_test.py``.
LEDGER_TABLES: dict[str, tuple[str, str]] = {
    "webhook_deliveries": ("webhook_subscriptions", "subscription_id"),
}

# --- Row-attribution overlay on guild-schema tables ---------------------------
# Every guild-schema table that models something a person made carries
# ``created_by`` + ``updated_by`` by subclassing
# ``app.models.tenant._mixins.CreatedByMixin``. Membership is therefore
# declared by the model, not copied into a list here; what IS declared here is
# the opposite — the tables that deliberately do NOT carry the pair, each with
# the reason it does not need one. ``created_by_test.py`` fails CI when a guild
# table is in neither bucket, so a new table forces the decision.
CREATED_BY_EXEMPT_TABLES: frozenset[str] = frozenset(
    {
        # Roster rows: the membership IS the fact, and ``user_id`` already names
        # whose it is.
        "calendar_event_attendees",
        "initiative_members",
        "initiative_role_permissions",
        "task_assignees",
        # A knock at a door: ``user_id`` is both the author and the subject, and
        # ``resolved_by`` already names the manager who answered it.
        "initiative_join_requests",
        # Per-user state, keyed by the user it belongs to. ``user_id`` is both
        # the author and the subject, so a second copy of it says nothing.
        "guild_ai_member_keys",
        "guild_ai_member_prefs",
        "guild_app_user_connections",
        "app_member_consents",
        "post_reads",
        # A fact about an install: where it appears. The rows a new initiative's
        # trigger writes have no person placing them.
        "app_placements",
        # A ballot: ``user_id`` is the voter, which is both the author of the
        # row and its whole content.
        "post_poll_votes",
        "project_favorites",
        "project_orders",
        "recent_views",
        # Machinery. Written by a trigger, a poller or a scheduler rather than
        # by a person; each already records the actor it needs (the outbox
        # carries ``actor_user_id``) or has none to record.
        "event_outbox",
        "event_reminder_dispatches",
        "search_entries",
        "reaction_digest_items",
        "task_assignment_digest_items",
        "webhook_deliveries",
        # The key -> task map the intake writer reads. The case it points at
        # carries the author, and a system-opened one has none by design.
        "intake_cases",
        # A report is not authored — it is a thing several people said about
        # one target. Who said it is the reporters table, and who settled it is
        # ``decided_by``; a creator column would be a third answer to neither
        # question.
        "moderation_reports",
        "moderation_report_reporters",
    }
)

# --- Guild-scoped (derived) -------------------------------------------------
# Everything that moves into a ``guild_<id>`` schema = the initiative-scoped
# content (keys of INITIATIVE_PATHS) plus the guild-level exemptions. Derived,
# so a guild table is declared in exactly ONE place.
GUILD_SCOPED_TABLES: frozenset[str] = INITIATIVE_SCOPED_TABLES | GUILD_LEVEL_TABLES

# Union of every table that has an explicit placement decision.
ALL_CLASSIFIED_TABLES: frozenset[str] = SHARED_TABLES | GUILD_SCOPED_TABLES


def is_guild_scoped(table_name: str) -> bool:
    """Return True if ``table_name`` moves into per-guild schemas."""
    return table_name in GUILD_SCOPED_TABLES


def is_shared(table_name: str) -> bool:
    """Return True if ``table_name`` stays in the ``public`` schema."""
    return table_name in SHARED_TABLES


def is_initiative_scoped(table_name: str) -> bool:
    """Return True if ``table_name`` carries the initiative-member RLS policies
    (vs being guild-level / structural / own-row and exempt)."""
    return table_name in INITIATIVE_SCOPED_TABLES
