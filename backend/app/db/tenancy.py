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
  ``guild_rls.sql`` is generated from it. So adding an initiative-scoped table
  is a *single* edit (a path in ``initiative_rls``).
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

# --- Guild-scoped, NOT initiative-scoped (level 2 exemptions) ----------------
# Guild-wide, structural, or own-row tables protected only by the schema
# boundary. The complement of this set within a guild schema is
# ``INITIATIVE_SCOPED_TABLES`` (declared in ``app.db.initiative_rls``).
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
