"""Authoritative table classification for schema-per-guild multi-tenancy.

This module is the single source of truth for *where each table lives* once
each guild becomes its own PostgreSQL schema:

- **Shared tables** stay in the ``public`` schema. They are identity, the
  tenancy roster, platform configuration, and per-user / cross-guild concerns
  that are read *without* a guild context (login, "list my guilds", platform
  admin, SSO auto-join, the notification inbox).
- **Guild-scoped tables** move into a per-guild schema (``guild_<id>``). They
  are the actual tenant content (initiatives, projects, tasks, documents,
  calendar, queues, counters, tags, and their child/association tables).

Every ``table=True`` model MUST appear in exactly one of the two sets below.
``tenancy_test.py`` enforces this against ``SQLModel.metadata`` so that a new
table cannot be added without an explicit placement decision — an unclassified
guild-scoped table would silently leak across tenants.

See ``history/schema-per-guild-design.md`` (§2 Table classification) for the
rationale behind each placement, including the resolved "Bucket C" edge cases:
``guild_invites`` / ``oidc_claim_mappings`` stay shared (read pre-routing,
before guild membership exists); ``guild_settings`` / ``recent_views`` /
``event_reminder_dispatches`` / ``task_assignment_digest_items`` are
guild-scoped (always accessed with a guild context, background jobs visit each
guild's schema in turn).
"""

from __future__ import annotations

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
        "guild_memberships",
        # Consumed pre-membership / pre-routing
        "guild_invites",  # looked up by token before the user is a member
        "oidc_claim_mappings",  # SSO auto-join rules, read across all guilds at login
        # Platform-wide
        "app_settings",  # OIDC / SMTP / branding config
        "access_grants",  # PAM — inherently cross-guild (request -> approve -> scoped)
        "notifications",  # per-user inbox spanning guilds (carries guild_id after split)
    }
)

# --- Guild-scoped (move into ``guild_<id>`` schemas) ------------------------
# The actual tenant content. Always accessed with a guild context.
GUILD_SCOPED_TABLES: frozenset[str] = frozenset(
    {
        # Guild config — guild-scoped because it holds private config (API keys)
        "guild_settings",
        "webhook_subscriptions",
        # Initiatives + roles
        "initiatives",
        "initiative_members",
        "initiative_roles",
        "initiative_role_permissions",
        # Projects + permissions / ordering / favorites / activity
        "projects",
        "project_documents",
        "project_permissions",
        "project_role_permissions",
        "project_orders",
        "project_favorites",
        "project_tags",
        # Tasks + children
        "tasks",
        "subtasks",
        "task_assignees",
        "task_statuses",
        "task_tags",
        "task_property_values",
        "task_assignment_digest_items",
        # Documents + versions / permissions / links
        "documents",
        "document_file_versions",
        "document_permissions",
        "document_role_permissions",
        "document_tags",
        "document_links",
        "document_property_values",
        # Comments, tags, custom properties, uploads
        "comments",
        "tags",
        "property_definitions",
        "uploads",
        "recent_views",
        # Calendar events + children
        "calendar_events",
        "calendar_event_attendees",
        "calendar_event_documents",
        "calendar_event_tags",
        "calendar_event_property_values",
        "event_reminder_dispatches",
        # Queues + items + permissions
        "queues",
        "queue_items",
        "queue_permissions",
        "queue_role_permissions",
        "queue_item_documents",
        "queue_item_tags",
        "queue_item_tasks",
        # Counters + groups + permissions
        "counters",
        "counter_groups",
        "counter_group_permissions",
        "counter_group_role_permissions",
    }
)

# Union of every table that has an explicit placement decision.
ALL_CLASSIFIED_TABLES: frozenset[str] = SHARED_TABLES | GUILD_SCOPED_TABLES


# --- Second level: the initiative-member access boundary --------------------
# Within a guild schema, every table is *also* one of two kinds. This partition
# is the single source of truth for the initiative-level RLS layer:
#
# - **INITIATIVE_SCOPED_TABLES** carry the four ``initiative_member_*`` policies
#   that defer to ``public.initiative_access(...)``. ``scripts/gen_guild_rls.py``
#   holds the per-table initiative-id path and generates ``guild_rls.sql`` from
#   exactly this set; ``tenancy_test.py`` asserts the generator registry equals
#   it, and a provisioning test asserts every one actually has the policies in a
#   live schema. So an initiative-level table CANNOT ship without its policies.
# - **GUILD_LEVEL_TABLES** are exempt — they are guild-wide, structural, or
#   own-row, and are protected only by the schema boundary (the ``guild_<id>``
#   role). Adding one here is the explicit "this is not initiative-scoped"
#   decision.
#
# Together they MUST partition ``GUILD_SCOPED_TABLES`` (disjoint + complete);
# ``tenancy_test.py`` fails CI otherwise, so a new guild table forces a
# conscious initiative-scoped-or-exempt choice.
INITIATIVE_SCOPED_TABLES: frozenset[str] = frozenset(
    {
        # Projects + children / associations
        "projects",
        "project_documents",
        "project_permissions",
        "project_role_permissions",
        "project_tags",
        # Tasks + children / associations
        "tasks",
        "subtasks",
        "task_assignees",
        "task_statuses",
        "task_tags",
        "task_property_values",
        # Documents + children / associations
        "documents",
        "document_file_versions",
        "document_permissions",
        "document_role_permissions",
        "document_tags",
        "document_links",
        "document_property_values",
        # Comments + custom-property definitions
        "comments",
        "property_definitions",
        # Calendar events + children
        "calendar_events",
        "calendar_event_attendees",
        "calendar_event_documents",
        "calendar_event_tags",
        "calendar_event_property_values",
        # Queues + items + permissions
        "queues",
        "queue_items",
        "queue_permissions",
        "queue_role_permissions",
        "queue_item_documents",
        "queue_item_tags",
        "queue_item_tasks",
        # Counters + groups + permissions
        "counters",
        "counter_groups",
        "counter_group_permissions",
        "counter_group_role_permissions",
        # Per-user state that still belongs to an initiative's content — scoped
        # via the entity it points at (project / event / polymorphic), so a
        # non-member never has rows for content outside their initiatives.
        "project_orders",  # via projects
        "project_favorites",  # via projects
        "task_assignment_digest_items",  # via projects
        "event_reminder_dispatches",  # via calendar_events
        "recent_views",  # polymorphic: project / document / queue / counter_group
    }
)

# Guild-scoped but NOT initiative-scoped — exempt from initiative-member RLS.
GUILD_LEVEL_TABLES: frozenset[str] = frozenset(
    {
        # Guild-wide config / data (no initiative scope)
        "guild_settings",
        "webhook_subscriptions",  # guild integration config; initiative_id nullable
        "tags",  # tags are guild-level, shared across initiatives
        "uploads",  # guild blob store: no FK to any initiative entity (documents
        # reference blobs by file_url string, and a blob can be pinned by
        # documents across initiatives), so it can't use initiative_access;
        # blob *content* access is already gated at the document layer.
        # Structural initiative tables — deliberately guild-scoped, not
        # initiative-member-scoped (the membership table can't be gated by the
        # membership check it backs without recursing; own-row scoping would
        # break co-member rosters). See guild_rls.sql header.
        "initiatives",
        "initiative_members",
        "initiative_roles",
        "initiative_role_permissions",
    }
)


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
