"""Row-level security on the shared (``public``) tables, from one registry.

The guild schemas have had this since the squash: their policies are rendered
from ``INITIATIVE_PATHS`` and applied per schema, stamped, and held to the
catalog by ``guild_rls_test``. The shared tables did not. Their policies were
written by hand in the migrations that created each table, re-applied by
nothing and checked by nothing. This module is the same shape for ``public``.

``PUBLIC_RLS`` names every shared table with its row-security state and its
policies. ``render_public_rls_ddl`` turns that into DDL; ``ensure_public_rls``
applies it at boot on the provisioning engine (the tables' owner), after the
migrations and before the guild back-fill, and stamps the ``public`` schema's
comment with the render's digest so a boot with nothing changed does nothing.
``public_rls_test`` holds the registry to the catalog in both directions.

A migration still creates a shared table, backfills it, sets ``ENABLE`` and
``FORCE ROW LEVEL SECURITY`` and runs the ``GRANT``/``REVOKE`` — the record of
*when* access changed. Its policies come from here, for the reason guild
migrations stopped rendering theirs: a migration freezes what the registry
said the day it was written. Boot re-asserts what is registered and never
drops what is not — a policy on a shared table that this registry does not
name is reported at boot and fails the drift test, so whoever added it
registers it.

A table registered with no policy and row security forced is in the strictest
state Postgres has: a grant on it reads nothing until a policy admits a row.
That is stated here on purpose rather than implied by absence.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "PUBLIC_RLS",
    "Policy",
    "TableRls",
    "apply_public_rls",
    "apply_public_rls_if_changed",
    "policy_name",
    "ensure_public_rls",
    "public_rls_digest",
    "render_public_rls_ddl",
    "unregistered_policies",
]

# --- The request context a policy reads ---------------------------------------
# NULLIF-guarded casts throughout: a PAM grantee, and any unset context, leaves
# the value empty, and a bare ''::int raises and faults the whole query for
# every PERMISSIVE policy on the table (CLAUDE.md §6).
UID = "NULLIF(current_setting('app.current_user_id', true), '')::int"
GID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"
PAM_GID = "NULLIF(current_setting('app.pam_guild_id', true), '')::int"
BILLING_GID = "NULLIF(current_setting('app.billing_guild_id', true), '')::int"
ROUTED_ADMIN = "current_setting('app.current_guild_role', true) = 'admin'"
PAM_READ = "current_setting('app.pam_read', true) = 'true'"

# --- Predicate builders -------------------------------------------------------
# Each returns the SQL of a policy predicate. ``{table}`` is replaced with the
# table's name at render time, for the correlated references.

OPEN = "true"  # the role is the rule: whoever may assume it reads every row
CLOSED = "false"
SIGNED_IN = f"{UID} IS NOT NULL"


def own_row(col: str = "user_id") -> str:
    """The row belongs to the reader."""
    return f"{col} = {UID}"


def guild_scoped(col: str = "guild_id") -> str:
    """The row belongs to the routed community."""
    return f"{col} = {GID}"


def routed_admin(col: str = "guild_id") -> str:
    """The row belongs to the routed community and the reader is its admin."""
    return f"{col} = {GID} AND {ROUTED_ADMIN}"


def routed_or_own(guild_col: str, user_col: str) -> str:
    return f"{guild_col} = {GID} OR {user_col} = {UID}"


def routed_and_own(guild_col: str, user_col: str) -> str:
    return f"{guild_col} = {GID} AND {user_col} = {UID}"


def member_of_guild(col: str = "guild_id") -> str:
    """The reader is a member of the row's community, by the membership table."""
    return (
        "EXISTS (SELECT 1 FROM guild_memberships"
        f" WHERE guild_memberships.guild_id = {{table}}.{col}"
        f" AND guild_memberships.user_id = {UID})"
    )


def routed_or_member(col: str = "guild_id") -> str:
    """The routed community, or one the reader belongs to (the pre-routing
    reads: a member's guild list, an invite preview, a guild image)."""
    return f"{col} = {GID} OR {member_of_guild(col)}"


def routed_or_pam(col: str = "guild_id") -> str:
    """The routed community, falling back to the one a PAM grant names."""
    return f"{col} = COALESCE({GID}, {PAM_GID})"


def pam_read(col: str = "guild_id") -> str:
    """A live read grant on the row's community (the PAM leg)."""
    return f"{col} = {PAM_GID} AND {PAM_READ}"


def billing_scoped(col: str = "guild_id") -> str:
    """The community the billing role was routed to (``SET ROLE`` + GUC)."""
    return f"{col} = {BILLING_GID}"


def seat(col: str = "guild_id") -> str:
    """The routed community, and the reader holds its superadmin seat."""
    return f"{col} = {GID} AND guild_superadmin({col}, {UID})"


# Predicates one table family shares, named once.
EITHER_END = f"(user_id_low = {UID}) OR (user_id_high = {UID})"
OWN_DEVICE_KEY = (
    "EXISTS (SELECT 1 FROM dm_devices d"
    f" WHERE d.id = dm_one_time_keys.device_id AND d.user_id = {UID})"
)
OWN_DEVICE_QUEUE = (
    "recipient_device_id IN"
    f" (SELECT dm_devices.id FROM dm_devices WHERE dm_devices.user_id = {UID})"
)
OWN_OR_DM_OPEN = (
    f"(user_id = {UID}) OR"
    f" (({UID} IS NOT NULL) AND (dm_apparent_permission(user_id) = 'open'))"
)
OWN_OR_DM_NOT_DENIED = (
    f"(user_id = {UID}) OR"
    f" (({UID} IS NOT NULL) AND (dm_apparent_permission(user_id) <> 'denied'))"
)
LIVE_WINDOW = (
    "(published_at IS NOT NULL) AND (published_at <= now())"
    " AND ((expires_at IS NULL) OR (expires_at > now()))"
)
CLIENT_SECTOR = "purpose = 'client' AND entity_type = 'user'"
MEMBER_ROLE_ONLY = "role = 'member'"

# --- The registry ---------------------------------------------------------------

SELECT = "SELECT"
INSERT = "INSERT"
UPDATE = "UPDATE"
DELETE = "DELETE"
ALL = "ALL"
COMMANDS = frozenset({SELECT, INSERT, UPDATE, DELETE, ALL})

#: Roles a policy may be granted to, by their unprefixed names. The platform
#: ladder and the billing role carry ``settings.PLATFORM_ROLE_PREFIX`` when
#: rendered; the rest are fixed names.
KNOWN_ROLES = frozenset(
    {
        "public",
        "app_user",
        "app_guild_base",
        "app_guild_base_ro",
        "app_dm_reader",
        "app_profile_reader",
        "initiative_billing",
        "platform_base",
        "platform_member",
        "platform_support",
        "platform_moderator",
        "platform_operator",
        "platform_owner",
    }
)
_PREFIXED = frozenset(r for r in KNOWN_ROLES if r.startswith("platform_")) | {
    "initiative_billing"
}


@dataclass(frozen=True)
class Policy:
    """One policy: its name in the catalog, the command it governs, the roles
    it is granted to, and its predicate. ``using`` is the row test for
    reading, updating and deleting; ``check`` the test on a written row. An
    UPDATE or ALL policy given only ``using`` checks the written row with the
    same predicate, which is how every such policy here was written."""

    name: str
    command: str
    roles: tuple[str, ...]
    using: str | None = None
    check: str | None = None
    restrictive: bool = False


@dataclass(frozen=True)
class TableRls:
    """A shared table's row security: whether it is on, whether the owner is
    bound by it too, and its policies. ``enabled`` with no policies is the
    strictest state (see the module docstring)."""

    policies: tuple[Policy, ...] = ()
    enabled: bool = True
    forced: bool = True


#: Row security on, forced, no policy: only the system engine reaches the rows.
FORCED_NO_POLICY = TableRls()
#: No row security at all: the table is governed by grants alone.
NO_RLS = TableRls(enabled=False, forced=False)

#: Every shared table (``system_grants.GRANTABLE_SHARED_TABLES``), with its
#: row security. Policy names are the ones the migrations gave them.
PUBLIC_RLS: dict[str, TableRls] = {
    "access_grants": TableRls(
        policies=(
            Policy(
                "access_grants_admin",
                ALL,
                (
                    "platform_operator",
                    "platform_owner",
                ),
                using=OPEN,
            ),
            Policy("access_grants_self", ALL, ("public",), using=own_row("user_id")),
        ),
    ),
    "announcement_images": TableRls(
        policies=(
            Policy(
                "announcement_image_read",
                SELECT,
                (
                    "app_guild_base",
                    "platform_base",
                ),
                using=OPEN,
            ),
        ),
    ),
    "announcement_reads": TableRls(
        policies=(
            Policy(
                "announcement_read_self",
                SELECT,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "announcement_read_self_insert",
                INSERT,
                ("platform_base",),
                check=own_row("user_id"),
            ),
            Policy(
                "announcement_read_self_update",
                UPDATE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
        ),
    ),
    "announcements": TableRls(
        policies=(
            Policy(
                "announcement_live_read",
                SELECT,
                (
                    "app_guild_base",
                    "platform_base",
                ),
                using=LIVE_WINDOW,
            ),
        ),
    ),
    "app_service_registrations": TableRls(
        policies=(
            Policy(
                "app_service_registrations_owner_read",
                SELECT,
                ("platform_owner",),
                using=OPEN,
            ),
        ),
    ),
    "app_settings": TableRls(
        policies=(
            Policy("app_settings_owner", ALL, ("platform_owner",), using=OPEN),
            Policy("app_settings_read", SELECT, ("public",), using=OPEN),
        ),
    ),
    "billing_event_log": TableRls(
        policies=(
            Policy(
                "billing_event_insert",
                INSERT,
                ("initiative_billing",),
                check=billing_scoped("guild_id"),
            ),
        ),
    ),
    "contact_grants": TableRls(
        policies=(
            Policy(
                "contact_grants_self_delete",
                DELETE,
                ("platform_base",),
                using=EITHER_END,
            ),
            Policy(
                "contact_grants_self_insert",
                INSERT,
                ("platform_base",),
                check=EITHER_END,
            ),
            Policy(
                "contact_grants_self_select",
                SELECT,
                ("platform_base",),
                using=EITHER_END,
            ),
            Policy(
                "contact_grants_self_update",
                UPDATE,
                ("platform_base",),
                using=EITHER_END,
            ),
            Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
        ),
    ),
    "dm_conversation_members": TableRls(
        policies=(
            Policy(
                "dm_conversation_members_self_delete",
                DELETE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "dm_conversation_members_self_insert",
                INSERT,
                ("platform_base",),
                check=OWN_OR_DM_NOT_DENIED,
            ),
            Policy(
                "dm_conversation_members_self_select",
                SELECT,
                ("platform_base",),
                using="dm_on_roster(conversation_id)",
            ),
            Policy(
                "dm_conversation_members_self_update",
                UPDATE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
        ),
    ),
    "dm_conversations": TableRls(
        policies=(
            Policy(
                "dm_conversations_self_delete",
                DELETE,
                ("platform_base",),
                using="dm_in_conversation(id)",
            ),
            Policy(
                "dm_conversations_self_insert",
                INSERT,
                ("platform_base",),
                check=SIGNED_IN,
            ),
            Policy(
                "dm_conversations_self_select",
                SELECT,
                ("platform_base",),
                using="dm_on_roster(id)",
            ),
            Policy(
                "dm_conversations_self_update",
                UPDATE,
                ("platform_base",),
                using="dm_in_conversation(id)",
            ),
        ),
    ),
    "dm_devices": TableRls(
        policies=(
            Policy(
                "dm_devices_self_delete",
                DELETE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "dm_devices_self_insert",
                INSERT,
                ("platform_base",),
                check=own_row("user_id"),
            ),
            Policy(
                "dm_devices_self_select",
                SELECT,
                ("platform_base",),
                using=OWN_OR_DM_OPEN,
            ),
            Policy(
                "dm_devices_self_update",
                UPDATE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
        ),
    ),
    "dm_one_time_keys": TableRls(
        policies=(
            Policy(
                "dm_one_time_keys_self_delete",
                DELETE,
                ("platform_base",),
                using=OWN_DEVICE_KEY,
            ),
            Policy(
                "dm_one_time_keys_self_insert",
                INSERT,
                ("platform_base",),
                check=OWN_DEVICE_KEY,
            ),
            Policy(
                "dm_one_time_keys_self_select",
                SELECT,
                ("platform_base",),
                using=OWN_DEVICE_KEY,
            ),
            Policy("dm_reader_keys", ALL, ("app_dm_reader",), using=OPEN),
        ),
    ),
    "dm_queue": TableRls(
        policies=(
            Policy(
                "dm_queue_self_delete",
                DELETE,
                ("platform_base",),
                using=OWN_DEVICE_QUEUE,
            ),
            Policy(
                "dm_queue_self_insert",
                INSERT,
                ("platform_base",),
                check="dm_in_conversation(conversation_id) AND dm_device_in_conversation(recipient_device_id, conversation_id)",
            ),
            Policy(
                "dm_queue_self_select",
                SELECT,
                ("platform_base",),
                using=OWN_DEVICE_QUEUE,
            ),
            Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
        ),
    ),
    "federated_identities": TableRls(
        policies=(
            Policy(
                "federated_identities_self", ALL, ("public",), using=own_row("user_id")
            ),
        ),
    ),
    "guild_administration": TableRls(
        policies=(
            Policy(
                "billing_guild_administration_select",
                SELECT,
                ("initiative_billing",),
                using=billing_scoped("guild_id"),
            ),
            Policy(
                "billing_guild_administration_update",
                UPDATE,
                ("initiative_billing",),
                using=billing_scoped("guild_id"),
            ),
            Policy(
                "guild_administration_pam_read",
                SELECT,
                ("public",),
                using=pam_read("guild_id"),
            ),
            Policy(
                "guild_administration_select",
                SELECT,
                (
                    "app_guild_base",
                    "app_user",
                    "platform_base",
                ),
                using=routed_or_member("guild_id"),
            ),
        ),
    ),
    "guild_auth_policies": TableRls(
        policies=(
            Policy("guild_auth_policies_read", SELECT, ("public",), using=OPEN),
            Policy(
                "guild_auth_policies_seat_delete",
                DELETE,
                ("public",),
                using=seat("guild_id"),
            ),
            Policy(
                "guild_auth_policies_seat_insert",
                INSERT,
                ("public",),
                check=seat("guild_id"),
            ),
            Policy(
                "guild_auth_policies_seat_update",
                UPDATE,
                ("public",),
                using=seat("guild_id"),
            ),
        ),
    ),
    "guild_images": TableRls(
        policies=(
            Policy(
                "guild_image_member_read",
                SELECT,
                (
                    "app_guild_base",
                    "app_user",
                    "platform_base",
                ),
                using=routed_or_member("guild_id"),
            ),
        ),
    ),
    "guild_invites": TableRls(
        policies=(
            Policy("guild_delete", DELETE, ("public",), using=guild_scoped("guild_id")),
            Policy("guild_insert", INSERT, ("public",), check=guild_scoped("guild_id")),
            Policy(
                "guild_select", SELECT, ("public",), using=member_of_guild("guild_id")
            ),
            Policy("guild_update", UPDATE, ("public",), using=guild_scoped("guild_id")),
        ),
    ),
    "guild_memberships": TableRls(
        policies=(
            Policy(
                "billing_membership_select",
                SELECT,
                ("initiative_billing",),
                using=billing_scoped("guild_id"),
            ),
            Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
            Policy(
                "guild_membership_projection_read",
                SELECT,
                ("app_profile_reader",),
                using=routed_or_pam("guild_id"),
            ),
            Policy(
                "guild_memberships_delete",
                DELETE,
                ("public",),
                using=routed_and_own("guild_id", "user_id"),
            ),
            Policy(
                "guild_memberships_insert",
                INSERT,
                ("public",),
                check=guild_scoped("guild_id"),
            ),
            Policy(
                "guild_memberships_request_insert_member_only",
                INSERT,
                ("public",),
                check=MEMBER_ROLE_ONLY,
                restrictive=True,
            ),
            Policy(
                "guild_memberships_select",
                SELECT,
                ("public",),
                using=routed_or_own("guild_id", "user_id"),
            ),
            Policy(
                "guild_memberships_update",
                UPDATE,
                ("public",),
                using=own_row("user_id"),
            ),
        ),
    ),
    "guild_provider_connections": TableRls(
        policies=(
            Policy("guild_provider_connections_read", SELECT, ("public",), using=OPEN),
        ),
    ),
    "guilds": TableRls(
        policies=(
            Policy(
                "billing_guild_select",
                SELECT,
                ("initiative_billing",),
                using=billing_scoped("id"),
            ),
            Policy(
                "billing_guild_update",
                UPDATE,
                ("initiative_billing",),
                using=billing_scoped("id"),
            ),
            Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
            Policy("guild_delete", DELETE, ("public",), using=routed_admin("id")),
            Policy("guild_insert", INSERT, ("public",), check=SIGNED_IN),
            Policy(
                "guild_select",
                SELECT,
                (
                    "app_guild_base",
                    "app_user",
                    "platform_base",
                ),
                using=routed_or_member("id"),
            ),
            Policy("guild_update", UPDATE, ("public",), using=routed_admin("id")),
            Policy("guilds_pam_read", SELECT, ("public",), using=pam_read("id")),
            Policy(
                "profile_reader_reads_the_name_rule",
                SELECT,
                ("app_profile_reader",),
                using=OPEN,
            ),
        ),
    ),
    "identity_refs": TableRls(
        policies=(
            Policy(
                "identity_refs_client_sector",
                SELECT,
                ("app_user",),
                using=CLIENT_SECTOR,
            ),
        ),
    ),
    "legal_acceptances": TableRls(
        policies=(
            Policy(
                "legal_acceptances_self_insert",
                INSERT,
                ("platform_base",),
                check=own_row("user_id"),
            ),
            Policy(
                "legal_acceptances_self_read",
                SELECT,
                ("platform_base",),
                using=own_row("user_id"),
            ),
        ),
    ),
    "marketplace_listing_versions": TableRls(
        policies=(
            Policy(
                "marketplace_listing_versions_read",
                SELECT,
                (
                    "app_guild_base",
                    "platform_base",
                ),
                using=OPEN,
            ),
        ),
    ),
    "marketplace_listings": TableRls(
        policies=(
            Policy(
                "marketplace_listings_read",
                SELECT,
                (
                    "app_guild_base",
                    "platform_base",
                ),
                using=OPEN,
            ),
        ),
    ),
    "marketplace_media": TableRls(
        policies=(
            Policy(
                "marketplace_media_read",
                SELECT,
                (
                    "app_guild_base",
                    "app_user",
                    "platform_base",
                ),
                using=OPEN,
            ),
        ),
    ),
    "oidc_claim_mappings": TableRls(
        policies=(
            Policy("guild_isolation", ALL, ("public",), using=guild_scoped("guild_id")),
        ),
    ),
    "platform_ai_connections": TableRls(
        policies=(
            Policy(
                "platform_ai_connections_owner", ALL, ("platform_owner",), using=OPEN
            ),
        ),
    ),
    "platform_provider_defaults": TableRls(
        policies=(
            Policy("platform_provider_defaults_read", SELECT, ("public",), using=OPEN),
        ),
    ),
    "profile_favorites": TableRls(
        policies=(
            Policy(
                "profile_favorites_self_delete",
                DELETE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "profile_favorites_self_insert",
                INSERT,
                ("platform_base",),
                check=own_row("user_id"),
            ),
            Policy(
                "profile_favorites_self_read",
                SELECT,
                ("platform_base",),
                using=own_row("user_id"),
            ),
        ),
    ),
    "user_avatars": TableRls(
        policies=(
            Policy(
                "user_avatar_public_read",
                SELECT,
                (
                    "app_guild_base",
                    "app_user",
                    "platform_base",
                ),
                using=OPEN,
            ),
            Policy(
                "user_avatar_self_delete",
                DELETE,
                (
                    "app_guild_base",
                    "app_user",
                    "platform_base",
                ),
                using=own_row("user_id"),
            ),
            Policy(
                "user_avatar_self_insert",
                INSERT,
                (
                    "app_guild_base",
                    "app_user",
                    "platform_base",
                ),
                check=own_row("user_id"),
            ),
            Policy(
                "user_avatar_self_update",
                UPDATE,
                (
                    "app_guild_base",
                    "app_user",
                    "platform_base",
                ),
                using=own_row("user_id"),
            ),
        ),
    ),
    "user_cookie_consent": TableRls(
        policies=(
            Policy(
                "user_cookie_consent_self_insert_app_guild_base",
                INSERT,
                ("app_guild_base",),
                check=own_row("user_id"),
            ),
            Policy(
                "user_cookie_consent_self_insert_{prefix}platform_base",
                INSERT,
                ("platform_base",),
                check=own_row("user_id"),
            ),
            Policy(
                "user_cookie_consent_self_select_app_guild_base",
                SELECT,
                ("app_guild_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_cookie_consent_self_select_app_guild_base_ro",
                SELECT,
                ("app_guild_base_ro",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_cookie_consent_self_select_{prefix}platform_base",
                SELECT,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_cookie_consent_self_update_app_guild_base",
                UPDATE,
                ("app_guild_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_cookie_consent_self_update_{prefix}platform_base",
                UPDATE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
        ),
    ),
    "user_decorations": TableRls(
        policies=(
            Policy(
                "user_decoration_self_read",
                SELECT,
                (
                    "app_guild_base",
                    "platform_base",
                ),
                using=own_row("user_id"),
            ),
        ),
    ),
    "user_dm_guild_optouts": TableRls(
        policies=(
            Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
            Policy(
                "user_dm_guild_optouts_self_delete",
                DELETE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_dm_guild_optouts_self_insert",
                INSERT,
                ("platform_base",),
                check=own_row("user_id"),
            ),
            Policy(
                "user_dm_guild_optouts_self_select",
                SELECT,
                ("platform_base",),
                using=own_row("user_id"),
            ),
        ),
    ),
    "user_dm_settings": TableRls(
        policies=(
            Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
            Policy(
                "user_dm_settings_self_delete",
                DELETE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_dm_settings_self_insert",
                INSERT,
                ("platform_base",),
                check=own_row("user_id"),
            ),
            Policy(
                "user_dm_settings_self_select",
                SELECT,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_dm_settings_self_update",
                UPDATE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
        ),
    ),
    "user_ignores": TableRls(
        policies=(
            Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
            Policy(
                "user_ignores_self_delete",
                DELETE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_ignores_self_insert",
                INSERT,
                ("platform_base",),
                check=own_row("user_id"),
            ),
            Policy(
                "user_ignores_self_select",
                SELECT,
                ("platform_base",),
                using=own_row("user_id"),
            ),
        ),
    ),
    "user_notification_prefs": TableRls(
        policies=(
            Policy(
                "user_notification_prefs_self_insert_app_guild_base",
                INSERT,
                ("app_guild_base",),
                check=own_row("user_id"),
            ),
            Policy(
                "user_notification_prefs_self_insert_{prefix}platform_base",
                INSERT,
                ("platform_base",),
                check=own_row("user_id"),
            ),
            Policy(
                "user_notification_prefs_self_select_app_guild_base",
                SELECT,
                ("app_guild_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_notification_prefs_self_select_app_guild_base_ro",
                SELECT,
                ("app_guild_base_ro",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_notification_prefs_self_select_{prefix}platform_base",
                SELECT,
                ("platform_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_notification_prefs_self_update_app_guild_base",
                UPDATE,
                ("app_guild_base",),
                using=own_row("user_id"),
            ),
            Policy(
                "user_notification_prefs_self_update_{prefix}platform_base",
                UPDATE,
                ("platform_base",),
                using=own_row("user_id"),
            ),
        ),
    ),
    "user_view_preferences": TableRls(
        policies=(
            Policy(
                "user_view_preferences_self_scope",
                ALL,
                ("public",),
                using=own_row("user_id"),
            ),
        ),
    ),
    "users": TableRls(
        policies=(
            Policy("dm_reader_read", SELECT, ("app_dm_reader",), using=OPEN),
            Policy("users_app_user_read", SELECT, ("app_user",), using=OPEN),
            Policy(
                "users_app_user_self_update", UPDATE, ("app_user",), using=own_row("id")
            ),
            Policy(
                "users_no_delete", DELETE, ("public",), using=CLOSED, restrictive=True
            ),
            Policy(
                "users_platform_read",
                SELECT,
                (
                    "platform_moderator",
                    "platform_operator",
                    "platform_owner",
                    "platform_support",
                ),
                using=OPEN,
            ),
            Policy("users_platform_self", ALL, ("platform_base",), using=own_row("id")),
            Policy("users_profile_read", SELECT, ("app_profile_reader",), using=OPEN),
            Policy(
                "users_request_insert_member_only",
                INSERT,
                ("public",),
                check=MEMBER_ROLE_ONLY,
                restrictive=True,
            ),
        ),
    ),
    "app_service_nonces": FORCED_NO_POLICY,
    "auth_challenges": FORCED_NO_POLICY,
    "auth_provider_secrets": FORCED_NO_POLICY,
    "auth_providers": FORCED_NO_POLICY,
    "auth_sessions": FORCED_NO_POLICY,
    "federated_identity_secrets": FORCED_NO_POLICY,
    "import_credentials": FORCED_NO_POLICY,
    "marketplace_registry_state": FORCED_NO_POLICY,
    "mfa_recovery_codes": FORCED_NO_POLICY,
    "user_api_keys": FORCED_NO_POLICY,
    "user_email_assertions": FORCED_NO_POLICY,
    "user_emails": FORCED_NO_POLICY,
    "user_passkeys": FORCED_NO_POLICY,
    "user_totp": FORCED_NO_POLICY,
    "user_totp_secrets": FORCED_NO_POLICY,
    "storage_backfill_state": FORCED_NO_POLICY,
    "alembic_version": NO_RLS,
    "auto_delegation_jti_blocklist": NO_RLS,
    "billing_jti_blocklist": NO_RLS,
    "email_outbox": NO_RLS,
    "push_tokens": NO_RLS,
    "user_tokens": NO_RLS,
    # 0245: FORCE without ENABLE and no policy — inert, and left as that
    # migration decided until the notification write path has its own design.
    "notifications": TableRls(enabled=False, forced=True),
}


# --- Rendering ------------------------------------------------------------------


def _roles_sql(roles: tuple[str, ...]) -> str:
    out = []
    for role in roles:
        if role == "public":
            out.append("PUBLIC")
        elif role in _PREFIXED:
            out.append(f'"{settings.PLATFORM_ROLE_PREFIX}{role}"')
        else:
            out.append(f'"{role}"')
    return ", ".join(out)


def policy_name(policy: Policy) -> str:
    """The name as the catalog holds it: ``{prefix}`` is the platform role
    prefix (two migrations named their per-role policies after the role), and
    Postgres keeps the first 63 characters of an identifier."""
    return policy.name.replace("{prefix}", settings.PLATFORM_ROLE_PREFIX)[:63]


def render_policy(table: str, policy: Policy) -> str:
    """The idempotent DDL for one policy: drop what is there, create this."""
    name = policy_name(policy)
    using = policy.using.replace("{table}", table) if policy.using else None
    check = policy.check.replace("{table}", table) if policy.check else None
    if check is None and policy.command in (UPDATE, ALL):
        check = using
    kind = "RESTRICTIVE" if policy.restrictive else "PERMISSIVE"
    lines = [
        f"DROP POLICY IF EXISTS {name} ON public.{table};",
        f"CREATE POLICY {name} ON public.{table} AS {kind} FOR {policy.command}",
        f"  TO {_roles_sql(policy.roles)}",
    ]
    if using is not None:
        lines.append(f"  USING ({using})")
    if check is not None:
        lines.append(f"  WITH CHECK ({check})")
    lines[-1] += ";"
    return "\n".join(lines)


def render_table_rls(table: str, rls: TableRls) -> str:
    """Row security and policies for one table. Never disables: a table that
    has row security on when the registry says off is drift for the test to
    report, not something boot turns off."""
    lines = []
    if rls.enabled:
        lines.append(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;")
    if rls.forced:
        lines.append(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;")
    lines.extend(render_policy(table, p) for p in rls.policies)
    return "\n".join(lines)


def render_public_rls_ddl(tables: frozenset[str] | None = None) -> str:
    """The whole registry as DDL, table by table in name order."""
    blocks = [
        f"-- {table}\n{render_table_rls(table, rls)}"
        for table, rls in sorted(PUBLIC_RLS.items())
        if (tables is None or table in tables) and (rls.enabled or rls.forced)
    ]
    return (
        "-- RENDERED from app.db.public_rls. Idempotent; run as the tables' owner.\n\n"
        + "\n\n".join(blocks)
        + "\n"
    )


def public_rls_digest() -> str:
    """What the schema comment carries once the render has been applied."""
    return hashlib.sha256(render_public_rls_ddl().encode()).hexdigest()[:16]


STAMP_PREFIX = "public_rls:"


# --- Applying -------------------------------------------------------------------


async def _existing_public_tables(conn: AsyncConnection) -> frozenset[str]:
    rows = await conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    return frozenset(r[0] for r in rows)


async def apply_public_rls(conn: AsyncConnection) -> None:
    """Run the registry's DDL for every registered table that exists.

    ``storage_backfill_state`` is created lazily by its service, so a table
    registered here may not exist yet; it is picked up on the next boot.
    """
    existing = await _existing_public_tables(conn)
    ddl = render_public_rls_ddl(existing & frozenset(PUBLIC_RLS))
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(ddl)


async def unregistered_policies(conn: AsyncConnection) -> list[tuple[str, str]]:
    """Policies on shared tables that the registry does not name."""
    rows = await conn.execute(
        text(
            "SELECT tablename, policyname FROM pg_policies "
            "WHERE schemaname = 'public' ORDER BY 1, 2"
        )
    )
    known = {
        (table, policy_name(policy))
        for table, rls in PUBLIC_RLS.items()
        for policy in rls.policies
    }
    return [(t, p) for t, p in rows if (t, p) not in known]


async def apply_public_rls_if_changed(conn: AsyncConnection) -> bool:
    """Apply the registry when its render differs from the last one applied.

    The ``public`` schema's comment carries the digest of the render last
    applied, the way a guild schema's carries its provisioning stamp; a boot
    whose render matches it does nothing. Anything on a shared table that the
    registry does not name is left in place and logged. Returns whether the
    render was applied.
    """
    digest = public_rls_digest()
    stamp = (
        await conn.execute(
            text("SELECT obj_description('public'::regnamespace, 'pg_namespace')")
        )
    ).scalar()
    if stamp == STAMP_PREFIX + digest:
        return False
    await apply_public_rls(conn)
    stray = await unregistered_policies(conn)
    if stray:
        logger.warning(
            "policies on shared tables that app.db.public_rls does not name: %s",
            ", ".join(f"{t}.{p}" for t, p in stray),
        )
    try:
        await conn.execute(
            text(f"COMMENT ON SCHEMA public IS '{STAMP_PREFIX}{digest}'")
        )
    except Exception:  # noqa: BLE001 — the render applied; only the stamp did not
        logger.warning(
            "public RLS applied but the public schema could not be stamped; "
            "it will be re-applied on every boot until the schema is owned by "
            "the provisioning login"
        )
    return True


async def ensure_public_rls() -> None:
    """Apply the registry on boot, over the provisioning engine.

    Called after the migrations and before the guild back-fill, on the login
    that owns the shared tables.
    """
    from app.db import session as db_session

    async with db_session.provisioning_engine.begin() as conn:
        applied = await apply_public_rls_if_changed(conn)
    if applied:
        logger.info("public RLS applied: %s", public_rls_digest())
