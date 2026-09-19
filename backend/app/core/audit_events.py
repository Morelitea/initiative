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
    AUTH_PASSWORD_CHANGED = "auth.password_changed"
    #: The account gave its password up and signs in by another way from
    #: now on. Recorded apart from a change, because what the account holds
    #: is different afterwards rather than merely different in value.
    AUTH_PASSWORD_REMOVED = "auth.password_removed"
    AUTH_IDENTITY_LINKED = "auth.identity_linked"
    AUTH_REFRESH_REUSE_DETECTED = "auth.refresh_reuse_detected"
    #: The account's own second factor. ``failed`` is a refused code against a
    #: standing challenge, so it is the shape a run of guesses makes.
    AUTH_SECOND_FACTOR_ENROLLED = "auth.second_factor_enrolled"
    AUTH_SECOND_FACTOR_DISABLED = "auth.second_factor_disabled"
    AUTH_SECOND_FACTOR_FAILED = "auth.second_factor_failed"
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
    #: Who holds a guild's sign-in configuration changed. An operator seats
    #: the first one; from then on the seat is passed on by whoever holds it,
    #: and both paths record this.
    GUILD_SUPERADMIN_CHANGED = "guild.superadmin_changed"
    #: A privileged-access grant was asked for, decided, or self-issued. The
    #: ``access_grants`` row is the record of what was granted; these say when
    #: each step happened and carry the purpose and the rung with them, so
    #: "who held this community's settings, at what level, and on whose
    #: authority" is answerable from the log by itself.
    ACCESS_GRANT_REQUESTED = "access_grant.requested"
    ACCESS_GRANT_DECIDED = "access_grant.decided"
    ACCESS_GRANT_SELF_ISSUED = "access_grant.self_issued"
    #: Which ways in the deployment permits changed. Carries the count of
    #: accounts an operator acknowledged stranding, where they did.
    PLATFORM_LOGIN_METHODS_CHANGED = "platform.login_methods_changed"
    #: Who the deployment asks to hold a second factor changed.
    PLATFORM_SECOND_FACTOR_REQUIREMENT_CHANGED = (
        "platform.second_factor_requirement_changed"
    )


class AuditCategory(str, Enum):
    """Which family an event belongs to. The board groups by this."""

    MODERATION = "moderation"
    AUTHENTICATION = "authentication"
    #: Privileged access: who was let into a community they are not in, on
    #: whose say-so, and how far.
    AUTHORIZATION = "authorization"
    #: The platform itself: who holds which rung of its ladder. Operator
    #: work, which is a different job from moderating an account.
    PLATFORM = "platform"


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
    AuditEventType.AUTH_PASSWORD_CHANGED: AuditEventMeta(
        tier=2, category=AuditCategory.AUTHENTICATION, is_write=True
    ),
    AuditEventType.AUTH_PASSWORD_REMOVED: AuditEventMeta(
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
}


def meta_for(event_type: AuditEventType) -> AuditEventMeta:
    return AUDIT_EVENT_META[event_type]


#: The envelope's shape version. Downstream contracts against it; bump only on
#: a breaking change.
SCHEMA_VERSION = 1
