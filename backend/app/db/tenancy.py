"""Authoritative table classification for schema-per-guild multi-tenancy.

Single source of truth for *where each table lives* and *how it is access-scoped*
once each guild becomes its own PostgreSQL schema. Two orthogonal levels:

**Level 1 — schema placement:**

- **Shared tables** stay in the ``public`` schema — identity, the tenancy
  roster, platform config, and per-user / cross-guild concerns read *without* a
  guild context (login, "list my guilds", platform admin, SSO auto-join, the
  notification inbox). Listed explicitly in ``SHARED_TABLES``.
- **Guild-scoped tables** move into a per-guild schema (``guild_<id>``) — the
  actual tenant content. ``GUILD_SCOPED_TABLES`` is *derived* as
  ``INITIATIVE_SCOPED_TABLES | GUILD_LEVEL_TABLES`` (level 2), so a guild table
  is declared in exactly one of those — never copied here.

**Level 2 — initiative access boundary (within a guild schema):**

- **Initiative-scoped** tables carry the four ``initiative_member_*`` RLS
  policies deferring to ``public.initiative_access(...)``. They are declared once
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
        "auto_delegation_jti_blocklist",
        "user_view_preferences",  # personal UI state (filters/sort/view-mode)
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
        "auth_providers",  # login provider registry (operator-global or guild-scoped)
        "auth_provider_secrets",  # provider client secret; app_admin-only companion
        "federated_identities",  # (provider, subject) -> user links
        "federated_identity_secrets",  # IdP refresh token; app_admin-only companion
        "auth_sessions",  # session/refresh store (JWT sid = row id); app_admin-only
        "guild_auth_policies",  # per-guild sign-in requirement, read pre-routing by the gate
        # Platform-wide
        "app_settings",  # OIDC / SMTP / branding config
        # Marketplace catalog: what is installable, platform-wide. Holds no
        # guild_id by design — the catalog never records who installed what.
        "marketplace_listings",
        "marketplace_listing_versions",
        # Deployment-level wiring for external app services (URL, shared secret,
        # operator-conferred grants). Platform-wide by definition — one row per
        # app, never per guild — and owner-managed.
        "app_service_registrations",
        # Spent one-shot nonces from the app-service request-signing channel.
        # Hangs off a registration, which is platform-wide, and a single signed
        # request may address any guild — so the guard cannot live in a schema.
        "app_service_nonces",
        # Registry client state: what this deployment last accepted from a
        # signed index, and the artwork that index named, mirrored locally so
        # listing media is served from here. Operator/system state, no guild.
        "marketplace_registry_state",
        "marketplace_media",
        "platform_ai_connections",  # operator AI connections (platform config mode)
        "access_grants",  # PAM — inherently cross-guild (request -> approve -> scoped)
        "notifications",  # per-user inbox spanning guilds (carries guild_id after split)
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
        # the sidebar has to know an app is there. Installing/removing is gated
        # at the endpoint (guild admin); what a member may do *inside* an app is
        # decided by that instance's own grants, not by this row.
        "guild_apps",
        "guild_ai_connections",  # guild admin's AI connections (guild config mode);
        # guild-wide config, no initiative scope. The api_key ciphertext is never
        # returned by the API (reads expose only has_key).
        "webhook_deliveries",  # per-subscription delivery ledger, no initiative of its own
        "tags",  # tags are guild-level, shared across initiatives (purge-guarded)
        "uploads",  # guild blob store: no FK to any initiative entity (documents
        # reference blobs by file_url string, and a blob can be pinned by
        # documents across initiatives), so it can't use initiative_access;
        # blob *content* access is already gated at the document layer.
        # Structural initiative tables — deliberately guild-scoped, not
        # initiative-member-scoped (the membership table can't be gated by the
        # membership check it backs without recursing; own-row scoping would
        # break co-member rosters). See the rendered RLS DDL header.
        "initiatives",  # purge-guarded (admin-only DELETE), not membership-gated
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
        # What one installed app calls one member — a pairwise pseudonymous
        # subject (OIDC Core §8.1). No initiative, and one owner per row, so it
        # carries own_row_* policies like its neighbours: the link is the whole
        # point of the value, and a row that resolved for anyone would undo the
        # unlinkability it exists to provide.
        "guild_app_subjects",
        # A member's authorization for an installed app to act as them. Same
        # shape and same reasons as the connections beside it: no FK to any
        # initiative (an app is guild-wide), one owner per row, and guild-
        # governed access rather than private property — so own_row_* policies,
        # owner OR guild admin.
        "guild_app_user_delegations",
    }
)

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
    "guild_app_user_delegations": "user_id",
    "guild_app_subjects": "user_id",
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
        # Junctions and link rows. Each already carries its own matched pair
        # naming the relation rather than a row author — ``attached_by_id`` /
        # ``attached_at`` on the document links, ``created_at`` on the tag
        # links — and the thing that was authored is the entity at either end.
        "calendar_event_documents",
        "calendar_event_tags",
        "calendar_tags",
        "counter_group_tags",
        "dashboard_tags",
        "document_tags",
        "project_documents",
        "project_tags",
        "queue_item_documents",
        "queue_item_tags",
        "queue_item_tasks",
        "queue_tags",
        "task_tags",
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
        "guild_app_subjects",
        "guild_app_user_connections",
        "guild_app_user_delegations",
        "project_favorites",
        "project_orders",
        "recent_views",
        # Machinery. Written by a trigger, a poller or a scheduler rather than
        # by a person; each already records the actor it needs (the outbox
        # carries ``actor_user_id``) or has none to record.
        "event_outbox",
        "event_reminder_dispatches",
        "task_assignment_digest_items",
        "webhook_deliveries",
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
