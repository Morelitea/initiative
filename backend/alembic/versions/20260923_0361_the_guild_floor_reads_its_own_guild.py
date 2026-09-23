"""the guild floor reads its own guild

The guild floor (``app_guild_base``, inherited by every routed ``guild_<id>``
role, and its read twin ``app_guild_base_ro``, inherited by the read-only and
query roles) stops holding verbs on per-person platform tables, and reads the
guild-keyed shared tables for the routed community alone. The registries
(``app.db.system_grants``, ``app.db.public_rls``) record the result.

* ``user_avatars``, ``user_cookie_consent``, ``user_notification_prefs``,
  ``user_view_preferences``, ``user_decorations``, ``announcements`` and
  ``announcement_images`` are read and written under a platform tier, the
  bare login role or the system engine. Both guild floors lose every verb on
  them, and the guild floor its ``user_view_preferences`` id sequence.
* ``marketplace_media`` is served on the bare login role alone, so both guild
  floors and the platform floor lose ``SELECT``.
* The guild-floor policies on ``user_cookie_consent`` and
  ``user_notification_prefs`` go; the registry no longer names them.

The rest is the registry's to render at boot, which runs after the migrations
and before the app serves: the policies on the remaining tables drop the guild
floor, and ``guilds``, ``guild_memberships``, ``guild_administration``,
``guild_images``, ``guild_auth_policies`` and ``guild_provider_connections``
each gain a policy that admits a routed request to its own community's rows,
beside the one the bare login role and the platform floor keep.

Revision ID: 20260923_0361
Revises: 20260923_0360
Create Date: 2026-09-23
"""

from alembic import op

from app.core.config import settings

revision = "20260923_0361"
down_revision = "20260923_0360"
branch_labels = None
depends_on = None

GUILD_FLOOR = "app_guild_base"
READ_FLOOR = "app_guild_base_ro"
PLATFORM_FLOOR = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"

ALL_VERBS = "SELECT, INSERT, UPDATE, DELETE"

#: (verbs, table, role), revoked on the way up and granted on the way down.
TAKEN_BACK: tuple[tuple[str, str, str], ...] = (
    (ALL_VERBS, "user_avatars", GUILD_FLOOR),
    ("SELECT", "user_avatars", READ_FLOOR),
    (ALL_VERBS, "user_cookie_consent", GUILD_FLOOR),
    ("SELECT", "user_cookie_consent", READ_FLOOR),
    (ALL_VERBS, "user_notification_prefs", GUILD_FLOOR),
    ("SELECT", "user_notification_prefs", READ_FLOOR),
    (ALL_VERBS, "user_view_preferences", GUILD_FLOOR),
    ("SELECT", "user_view_preferences", READ_FLOOR),
    ("SELECT", "user_decorations", GUILD_FLOOR),
    ("SELECT", "user_decorations", READ_FLOOR),
    ("SELECT", "announcements", GUILD_FLOOR),
    ("SELECT", "announcements", READ_FLOOR),
    ("SELECT", "announcement_images", GUILD_FLOOR),
    ("SELECT", "announcement_images", READ_FLOOR),
    ("SELECT", "marketplace_media", GUILD_FLOOR),
    ("SELECT", "marketplace_media", READ_FLOOR),
    ("SELECT", "marketplace_media", PLATFORM_FLOOR),
)

#: (table, role) whose id-sequence USAGE goes with the table's INSERT.
SEQUENCES_TAKEN_BACK: tuple[tuple[str, str], ...] = (
    ("user_view_preferences", GUILD_FLOOR),
)

#: (policy, table) the registry no longer names.
DROPPED_POLICIES: tuple[tuple[str, str], ...] = (
    ("user_cookie_consent_self_insert_app_guild_base", "user_cookie_consent"),
    ("user_cookie_consent_self_select_app_guild_base", "user_cookie_consent"),
    ("user_cookie_consent_self_select_app_guild_base_ro", "user_cookie_consent"),
    ("user_cookie_consent_self_update_app_guild_base", "user_cookie_consent"),
    ("user_notification_prefs_self_insert_app_guild_base", "user_notification_prefs"),
    ("user_notification_prefs_self_select_app_guild_base", "user_notification_prefs"),
    (
        "user_notification_prefs_self_select_app_guild_base_ro",
        "user_notification_prefs",
    ),
    ("user_notification_prefs_self_update_app_guild_base", "user_notification_prefs"),
)

#: (policy, table) the registry renders at boot from this revision on. The
#: revision this reverts to names none of them, so a downgrade removes them.
ADDED_POLICIES: tuple[tuple[str, str], ...] = (
    ("guild_select_routed", "guilds"),
    ("guild_memberships_select_routed", "guild_memberships"),
    ("guild_administration_select_routed", "guild_administration"),
    ("guild_image_member_read_routed", "guild_images"),
    ("guild_auth_policies_member_read", "guild_auth_policies"),
    ("guild_auth_policies_routed_read", "guild_auth_policies"),
    ("guild_provider_connections_member_read", "guild_provider_connections"),
    ("guild_provider_connections_routed_read", "guild_provider_connections"),
)


def _on_role(role: str, statement: str) -> None:
    """Run ``statement`` when ``role`` exists on this cluster."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE '{statement}';
            END IF;
        END
        $$;
        """
    )


def _on_sequence(table: str, role: str, action: str) -> None:
    """``GRANT`` or ``REVOKE`` the id sequence of ``table`` for ``role``, when
    both exist on this cluster."""
    clause = (
        "GRANT USAGE, SELECT ON SEQUENCE %s TO %I"
        if action == "GRANT"
        else "REVOKE ALL ON SEQUENCE %s FROM %I"
    )
    op.execute(
        f"""
        DO $$
        DECLARE
            seq text := pg_get_serial_sequence('public.{table}', 'id');
        BEGIN
            IF seq IS NOT NULL
               AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE format('{clause}', seq, '{role}');
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    for verbs, table, role in TAKEN_BACK:
        _on_role(role, f'REVOKE {verbs} ON public.{table} FROM "{role}"')
    for table, role in SEQUENCES_TAKEN_BACK:
        _on_sequence(table, role, "REVOKE")
    for policy, table in DROPPED_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")


def downgrade() -> None:
    """Give the verbs back and remove the policies this revision's registry
    added. The rest are the registry's: a boot on the revision this reverts to
    renders them again from what it names."""
    for policy, table in ADDED_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
    for table, role in SEQUENCES_TAKEN_BACK:
        _on_sequence(table, role, "GRANT")
    for verbs, table, role in TAKEN_BACK:
        _on_role(role, f'GRANT {verbs} ON public.{table} TO "{role}"')
