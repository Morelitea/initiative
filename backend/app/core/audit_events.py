"""The catalogue of things Initiative writes down.

One enum drives every surface — the table, the ingestible line, the board, the
filters — so adding a newly-audited action is an enum member, a metadata row,
and one ``record()`` call at the site. There is no second list to keep in step;
``audit_events_test`` fails CI if the two here ever disagree.

Tiers come from ``history/pam-audit-sink-design.md``. Tier 1 is the privileged
-access family, which that design writes to immutable storage as well; Tier 2 is
everything else Initiative owns. Nothing here ships anywhere yet — the tier is
recorded now so the shipper does not have to reclassify history later.

Initiative records only actions whose authority it enforces itself. Infra
access, the identity provider's own sign-ins and billing all emit their own
streams; the envelope carries the fields that stitch them together downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AuditEventType(str, Enum):
    """A recorded action. Values are stable strings — treat them as a contract
    with whatever reads the log."""

    # Trust & safety: what a moderator does to an account, none of which needs
    # a PAM grant because none of it reaches a guild's content.
    USER_AVATAR_REMOVED = "user.avatar_removed"
    USER_USERNAME_CHANGED = "user.username_changed"
    USER_SUSPENDED = "user.suspended"
    USER_UNSUSPENDED = "user.unsuspended"
    USER_AGE_BLOCK_CLEARED = "user.age_block_cleared"
    USER_SIGN_IN_LOCK_LIFTED = "user.sign_in_lock_lifted"

    # The platform ladder. Granting a rung is an operator's job (``roles.assign``),
    # not a moderator's, so it is recorded apart from the account actions above:
    # the account it happened to, and the two roles it moved between.
    USER_PLATFORM_ROLE_CHANGED = "user.platform_role_changed"

    # Authentication: who got in, who did not, and what changed about the
    # credentials. Every failed attempt is recorded, whether or not it
    # resolved to an account; one that did not carries no target and no
    # submitted address, so nothing unowned reaches the log. See T123.
    AUTH_SIGNED_IN = "auth.signed_in"
    AUTH_SIGN_IN_FAILED = "auth.sign_in_failed"
    AUTH_SIGNED_OUT = "auth.signed_out"
    #: The account ended a session other than the one it was asking from —
    #: a row in its own "where you're signed in" list, or all of them at
    #: once. Apart from a sign-out because the session that ends is not the
    #: session that asked, which is the whole point of recording it.
    AUTH_SESSION_REVOKED = "auth.session_revoked"
    AUTH_PASSWORD_CHANGED = "auth.password_changed"
    #: The account gave its password up and signs in by another way from
    #: now on. Recorded apart from a change, because what the account holds
    #: is different afterwards rather than merely different in value.
    AUTH_PASSWORD_REMOVED = "auth.password_removed"
    AUTH_IDENTITY_LINKED = "auth.identity_linked"
    #: An address was proved for the first time, and the credentials the
    #: account held while it was unproven were retired with it.
    AUTH_CREDENTIALS_RETIRED = "auth.credentials_retired"
    AUTH_REFRESH_REUSE_DETECTED = "auth.refresh_reuse_detected"
    #: The account's own second factor. ``failed`` is a refused code against a
    #: standing challenge, so it is the shape a run of guesses makes.
    AUTH_SECOND_FACTOR_ENROLLED = "auth.second_factor_enrolled"
    AUTH_SECOND_FACTOR_DISABLED = "auth.second_factor_disabled"
    AUTH_SECOND_FACTOR_FAILED = "auth.second_factor_failed"
    AUTH_SIGN_IN_LOCKED = "auth.sign_in_locked"
    AUTH_SIGN_IN_HELD = "auth.sign_in_held"
    #: Cleared by somebody else — a support path, so actor and target differ.
    AUTH_SECOND_FACTOR_RESET = "auth.second_factor_reset"
    AUTH_RECOVERY_CODE_USED = "auth.recovery_code_used"
    AUTH_RECOVERY_CODES_ISSUED = "auth.recovery_codes_issued"
    #: A WebAuthn credential joined or left the account. The row carries the
    #: passkey's id and what the ceremony reported about it, never the
    #: credential id and never any key material.
    AUTH_PASSKEY_REGISTERED = "auth.passkey_registered"
    AUTH_PASSKEY_REMOVED = "auth.passkey_removed"
    # The native credential, recorded so its use can be observed rather than
    # guessed at. ``used`` rides the sliding window's own throttle, so it is
    # about one event per device per day, not one per request.
    AUTH_DEVICE_TOKEN_ISSUED = "auth.device_token_issued"
    AUTH_DEVICE_TOKEN_USED = "auth.device_token_used"
    #: A client traded a device token it already had for a session. Counted
    #: apart from ``issued``, because nothing was issued — this is the one
    #: that reads as movement onto the session path.
    AUTH_DEVICE_TOKEN_EXCHANGED = "auth.device_token_exchanged"
    #: Who holds a guild's sign-in configuration changed. The seat is passed
    #: on by whoever holds it — by membership, or through a superadmin
    #: settings grant — from the guild's own role route.
    GUILD_SUPERADMIN_CHANGED = "guild.superadmin_changed"
    #: A privileged-access grant was asked for, decided, or self-issued. The
    #: ``access_grants`` row is the record of what was granted; these say when
    #: each step happened and carry the purpose and the rung with them, so
    #: "who held this community's settings, at what level, and on whose
    #: authority" is answerable from the log by itself.
    ACCESS_GRANT_REQUESTED = "access_grant.requested"
    ACCESS_GRANT_DECIDED = "access_grant.decided"
    ACCESS_GRANT_SELF_ISSUED = "access_grant.self_issued"
    #: One request served through a grant rather than through membership —
    #: every one of them, read or write. The grant says what somebody was let
    #: into; this says what they then did with it, which is the difference
    #: between "an operator held this community for an hour" and "an operator
    #: opened four hundred documents". It records the reach, so it is not a
    #: write itself: a request that changed something records that separately,
    #: under the event for what it changed.
    PAM_REQUEST = "pam.request"
    #: Somebody serving a grant changed a document's or a wiki page's body,
    #: which happens over a live editing socket rather than through a request.
    #: One line the first time they do it in a session: that they edited it is
    #: the fact worth having, and a line per keystroke would bury it.
    PAM_CONTENT_EDITED = "pam.content_edited"
    #: Which ways in the deployment permits changed. Carries the count of
    #: accounts an operator acknowledged stranding, where they did.
    PLATFORM_LOGIN_METHODS_CHANGED = "platform.login_methods_changed"
    #: Who the deployment asks to hold a second factor changed.
    PLATFORM_SECOND_FACTOR_REQUIREMENT_CHANGED = (
        "platform.second_factor_requirement_changed"
    )

    # Who may reach what. A membership is the first gate into a community's
    # content and an initiative's the second; a share is the last. Each row
    # names the account it happened to, so "everything ever granted to this
    # person" is one query on ``target_user_id``.
    GUILD_MEMBER_ADDED = "guild.member_added"
    GUILD_MEMBER_REMOVED = "guild.member_removed"
    #: Between member and admin. A change to or from the seat that holds a
    #: community's sign-in is ``GUILD_SUPERADMIN_CHANGED`` instead.
    GUILD_MEMBER_ROLE_CHANGED = "guild.member_role_changed"
    #: An invite is a standing offer of membership; issuing or withdrawing
    #: one is recorded, and redeeming one is a ``GUILD_MEMBER_ADDED``.
    GUILD_INVITE_CREATED = "guild.invite_created"
    GUILD_INVITE_REVOKED = "guild.invite_revoked"
    INITIATIVE_MEMBER_ADDED = "initiative.member_added"
    INITIATIVE_MEMBER_REMOVED = "initiative.member_removed"
    INITIATIVE_MEMBER_ROLE_CHANGED = "initiative.member_role_changed"
    #: The roles themselves: a role is a bundle of permissions, so changing
    #: one changes what every holder may do.
    INITIATIVE_ROLE_CREATED = "initiative.role_created"
    INITIATIVE_ROLE_UPDATED = "initiative.role_updated"
    INITIATIVE_ROLE_DELETED = "initiative.role_deleted"
    #: One grantee's level on one resource moved: granted, raised, lowered
    #: or withdrawn. A share rebuilt from a list is one of these per grantee
    #: whose level actually changed.
    SHARING_GRANT_CHANGED = "sharing.grant_changed"
    #: Everything one account owned in a community now belongs to another,
    #: or to nobody. One record per transfer, with counts by tool.
    CONTENT_OWNERSHIP_TRANSFERRED = "content.ownership_transferred"
    #: A member let an installed app act as them, or took that back.
    DELEGATION_GRANTED = "delegation.granted"
    DELEGATION_REVOKED = "delegation.revoked"

    # Configuration. The record says which fields moved; a value is copied in
    # only where its type rules out a secret (see ``audit.changed_fields``).
    #: The deployment's own settings row: interface, community, email,
    #: storage, session lifetime, AI mode. ``detail.area`` says which.
    PLATFORM_SETTINGS_CHANGED = "platform.settings_changed"
    AUTH_PROVIDER_CREATED = "auth_provider.created"
    AUTH_PROVIDER_UPDATED = "auth_provider.updated"
    AUTH_PROVIDER_DELETED = "auth_provider.deleted"
    #: The answer a provider gives every community that has not given its
    #: own.
    AUTH_PROVIDER_DEFAULT_SET = "auth_provider.default_set"
    AUTH_PROVIDER_DEFAULT_CLEARED = "auth_provider.default_cleared"
    #: A claim rule places arriving accounts; written by the community's
    #: superadmin for that community.
    CLAIM_RULE_CREATED = "claim_rule.created"
    CLAIM_RULE_UPDATED = "claim_rule.updated"
    CLAIM_RULE_DELETED = "claim_rule.deleted"
    PROVIDER_PLACEMENT_EVERYWHERE_CHANGED = (
        "platform.provider_placement_everywhere_changed"
    )
    GUILD_PROVIDER_CONNECTED = "guild.provider_connected"
    GUILD_PROVIDER_CONNECTION_UPDATED = "guild.provider_connection_updated"
    GUILD_PROVIDER_DISCONNECTED = "guild.provider_disconnected"
    #: What a community requires of a sign-in before it counts.
    GUILD_AUTH_POLICY_CHANGED = "guild.auth_policy_changed"
    #: A community's other settings — its own (API keys, session limit,
    #: retention, profile) and the operator's for it (caps, options).
    GUILD_SETTINGS_CHANGED = "guild.settings_changed"
    AI_CONNECTION_CREATED = "ai_connection.created"
    AI_CONNECTION_UPDATED = "ai_connection.updated"
    AI_CONNECTION_DELETED = "ai_connection.deleted"
    APP_SERVICE_CREATED = "app_service.created"
    APP_SERVICE_UPDATED = "app_service.updated"
    APP_SERVICE_DELETED = "app_service.deleted"
    APP_SERVICE_VERIFIED = "app_service.verified"
    #: An operator re-read the catalogue sources; carries what was published
    #: and withdrawn.
    MARKETPLACE_CATALOG_REFRESHED = "marketplace.catalog_refreshed"
    #: A member shared an item from a community to this deployment's
    #: marketplace; carries the listing, its version, and whether it waits for
    #: review.
    MARKETPLACE_LISTING_SHARED = "marketplace.listing_shared"
    #: The owner approved or refused a shared version.
    MARKETPLACE_LISTING_REVIEWED = "marketplace.listing_reviewed"
    #: The owner uploaded a listing file.
    MARKETPLACE_LISTING_UPLOADED = "marketplace.listing_uploaded"
    #: A member took down a listing they shared.
    MARKETPLACE_LISTING_WITHDRAWN = "marketplace.listing_withdrawn"
    #: An installed app's own settings or configuration.
    APP_UPDATED = "app.updated"

    # Lifecycle: accounts and communities coming and going, and the bulk
    # movements of data — out of the deployment, or gone for good.
    USER_CREATED = "user.created"
    USER_DEACTIVATED = "user.deactivated"
    #: Personal details removed, contributions kept under a placeholder.
    USER_ANONYMIZED = "user.anonymized"
    #: The account and everything it left, removed outright.
    USER_DELETED = "user.deleted"
    #: The holder asked for the account to go. It is kept for the deployment's
    #: window, and erased at the end of it unless somebody comes back.
    USER_DELETION_SCHEDULED = "user.deletion_scheduled"
    #: Called off inside the window — by the holder signing in, or by an
    #: operator restoring it.
    USER_DELETION_CANCELLED = "user.deletion_cancelled"
    GUILD_CREATED = "guild.created"
    #: Deleted and kept: the community stops existing for everyone in it, and
    #: is retained for the restore window before the purge below destroys it.
    GUILD_DELETED = "guild.deleted"
    #: Brought back inside the window by a platform operator, who named the
    #: status it returns at and, where the roster was emptied, who runs it.
    GUILD_RESTORED = "guild.restored"
    #: The retention window ran out. What the deletion kept is now gone: the
    #: shared rows, the guild's schema, and its stored blobs.
    GUILD_PURGED = "guild.purged"
    GUILD_STATUS_CHANGED = "guild.status_changed"
    #: A whole community handed over as a bundle.
    GUILD_EXPORTED = "guild.exported"
    #: A community's roster, as a spreadsheet.
    GUILD_MEMBERS_EXPORTED = "guild.members_exported"
    #: Every account on the deployment, as a spreadsheet.
    PLATFORM_USERS_EXPORTED = "platform.users_exported"
    INITIATIVE_EXPORTED = "initiative.exported"
    INITIATIVE_DELETED = "initiative.deleted"
    #: Rows gone past recovery: one item purged from the trash by an admin,
    #: or a community's sweep, which carries counts and no actor.
    TRASH_PURGED = "trash.purged"
    API_KEY_CREATED = "api_key.created"
    API_KEY_DELETED = "api_key.deleted"
    APP_INSTALLED = "app.installed"
    APP_UNINSTALLED = "app.uninstalled"
    WEBHOOK_CREATED = "webhook.created"
    WEBHOOK_UPDATED = "webhook.updated"
    WEBHOOK_DELETED = "webhook.deleted"
    #: Content left the deployment for an AI provider. Recorded before the
    #: request goes out, since the disclosure does not wait on the reply.
    AI_REQUEST_SENT = "ai.request_sent"


class AuditCategory(str, Enum):
    """Which family an event belongs to. The board groups by this."""

    MODERATION = "moderation"
    AUTHENTICATION = "authentication"
    #: Who may reach what: memberships, roles, shares, delegations, and
    #: privileged access into a community from outside it.
    AUTHORIZATION = "authorization"
    #: The platform itself: who holds which rung of its ladder. Operator
    #: work, which is a different job from moderating an account.
    PLATFORM = "platform"
    #: Settings, at either level: how sign-in, email, storage, AI and apps
    #: are wired.
    CONFIGURATION = "configuration"
    #: Accounts and communities arriving and leaving, and data moved in
    #: bulk — exported, or destroyed.
    LIFECYCLE = "lifecycle"


@dataclass(frozen=True)
class AuditEventMeta:
    #: 1 for the privileged-access family (destined for immutable storage),
    #: 2 for everything else. Denormalized onto the row so a shipper can
    #: select by it without reading this registry.
    tier: int
    category: AuditCategory
    #: Whether the action changed something. Reads are recorded too (a PAM
    #: grantee's are the point of the log), so this is not implied by presence.
    is_write: bool


AUDIT_EVENT_META: dict[AuditEventType, AuditEventMeta] = {
    AuditEventType.USER_AVATAR_REMOVED: AuditEventMeta(
        tier=2, category=AuditCategory.MODERATION, is_write=True
    ),
    AuditEventType.USER_USERNAME_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.MODERATION, is_write=True
    ),
    AuditEventType.USER_SUSPENDED: AuditEventMeta(
        tier=2, category=AuditCategory.MODERATION, is_write=True
    ),
    AuditEventType.USER_UNSUSPENDED: AuditEventMeta(
        tier=2, category=AuditCategory.MODERATION, is_write=True
    ),
    AuditEventType.USER_AGE_BLOCK_CLEARED: AuditEventMeta(
        tier=2, category=AuditCategory.MODERATION, is_write=True
    ),
    AuditEventType.USER_SIGN_IN_LOCK_LIFTED: AuditEventMeta(
        tier=2, category=AuditCategory.MODERATION, is_write=True
    ),
    AuditEventType.USER_PLATFORM_ROLE_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.PLATFORM, is_write=True
    ),
    # A sign-in opens a session, so it is a write; a refused one changed
    # nothing and is not.
    AuditEventType.AUTH_SIGNED_IN: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_SIGN_IN_FAILED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=False
    ),
    AuditEventType.AUTH_SIGNED_OUT: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_SESSION_REVOKED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_PASSWORD_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_PASSWORD_REMOVED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_CREDENTIALS_RETIRED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_IDENTITY_LINKED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_REFRESH_REUSE_DETECTED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_SECOND_FACTOR_ENROLLED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_SECOND_FACTOR_DISABLED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    # A refused code changed nothing, like a refused sign-in.
    AuditEventType.AUTH_SECOND_FACTOR_FAILED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=False
    ),
    # Wrong answers adding up: the account's password and codes are refused
    # for a while, or until a moderator lifts it.
    AuditEventType.AUTH_SIGN_IN_LOCKED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_SIGN_IN_HELD: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_SECOND_FACTOR_RESET: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_RECOVERY_CODE_USED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_RECOVERY_CODES_ISSUED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_PASSKEY_REGISTERED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_PASSKEY_REMOVED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.PLATFORM_LOGIN_METHODS_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.PLATFORM_SECOND_FACTOR_REQUIREMENT_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_DEVICE_TOKEN_ISSUED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    # Presenting one slides its expiry, which is the write this records.
    AuditEventType.AUTH_DEVICE_TOKEN_USED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_DEVICE_TOKEN_EXCHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.GUILD_SUPERADMIN_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.ACCESS_GRANT_REQUESTED: AuditEventMeta(
        tier=1, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.ACCESS_GRANT_DECIDED: AuditEventMeta(
        tier=1, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.ACCESS_GRANT_SELF_ISSUED: AuditEventMeta(
        tier=1, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.PAM_REQUEST: AuditEventMeta(
        tier=1, category=AuditCategory.AUTHORIZATION, is_write=False
    ),
    AuditEventType.PAM_CONTENT_EDITED: AuditEventMeta(
        tier=1, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    # Who may reach what.
    AuditEventType.GUILD_MEMBER_ADDED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.GUILD_MEMBER_REMOVED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.GUILD_MEMBER_ROLE_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.GUILD_INVITE_CREATED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.GUILD_INVITE_REVOKED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.INITIATIVE_MEMBER_ADDED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.INITIATIVE_MEMBER_REMOVED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.INITIATIVE_MEMBER_ROLE_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.INITIATIVE_ROLE_CREATED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.INITIATIVE_ROLE_UPDATED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.INITIATIVE_ROLE_DELETED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.SHARING_GRANT_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.CONTENT_OWNERSHIP_TRANSFERRED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.DELEGATION_GRANTED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    AuditEventType.DELEGATION_REVOKED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHORIZATION, is_write=True
    ),
    # Configuration, at either level.
    AuditEventType.PLATFORM_SETTINGS_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.AUTH_PROVIDER_CREATED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.AUTH_PROVIDER_UPDATED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.AUTH_PROVIDER_DELETED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.AUTH_PROVIDER_DEFAULT_SET: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.AUTH_PROVIDER_DEFAULT_CLEARED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.CLAIM_RULE_CREATED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.CLAIM_RULE_UPDATED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.CLAIM_RULE_DELETED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.PROVIDER_PLACEMENT_EVERYWHERE_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.GUILD_PROVIDER_CONNECTED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.GUILD_PROVIDER_CONNECTION_UPDATED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.GUILD_PROVIDER_DISCONNECTED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.GUILD_AUTH_POLICY_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.GUILD_SETTINGS_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.AI_CONNECTION_CREATED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.AI_CONNECTION_UPDATED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.AI_CONNECTION_DELETED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.APP_SERVICE_CREATED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.APP_SERVICE_UPDATED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.APP_SERVICE_DELETED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.APP_SERVICE_VERIFIED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.MARKETPLACE_CATALOG_REFRESHED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.MARKETPLACE_LISTING_SHARED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.MARKETPLACE_LISTING_REVIEWED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.MARKETPLACE_LISTING_UPLOADED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.MARKETPLACE_LISTING_WITHDRAWN: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    AuditEventType.APP_UPDATED: AuditEventMeta(
        tier=2, category=AuditCategory.CONFIGURATION, is_write=True
    ),
    # A personal API key is a credential, so it sits with the rest of them.
    AuditEventType.API_KEY_CREATED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.API_KEY_DELETED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    # Lifecycle.
    AuditEventType.USER_CREATED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.USER_DEACTIVATED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.USER_ANONYMIZED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.USER_DELETED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.USER_DELETION_SCHEDULED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.USER_DELETION_CANCELLED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.GUILD_CREATED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.GUILD_DELETED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.GUILD_RESTORED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.GUILD_PURGED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.GUILD_STATUS_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.INITIATIVE_DELETED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.TRASH_PURGED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.APP_INSTALLED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.APP_UNINSTALLED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.WEBHOOK_CREATED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.WEBHOOK_UPDATED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    AuditEventType.WEBHOOK_DELETED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=True
    ),
    # Data leaving: nothing here changed, which is what is worth knowing.
    AuditEventType.GUILD_EXPORTED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=False
    ),
    AuditEventType.GUILD_MEMBERS_EXPORTED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=False
    ),
    AuditEventType.PLATFORM_USERS_EXPORTED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=False
    ),
    AuditEventType.INITIATIVE_EXPORTED: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=False
    ),
    AuditEventType.AI_REQUEST_SENT: AuditEventMeta(
        tier=2, category=AuditCategory.LIFECYCLE, is_write=False
    ),
}


def meta_for(event_type: AuditEventType) -> AuditEventMeta:
    return AUDIT_EVENT_META[event_type]


#: The envelope's shape version. Downstream contracts against it; bump only on
#: a breaking change.
SCHEMA_VERSION = 1

#: The line names the service it came from. Billing and auto emit streams of
#: the same shape about the same communities, so a reader filtering on a
#: community sees all three, and this is what tells them apart.
SERVICE = "initiative"
