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


class AuditCategory(str, Enum):
    """Which family an event belongs to. The board groups by this."""

    MODERATION = "moderation"


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
}


def meta_for(event_type: AuditEventType) -> AuditEventMeta:
    return AUDIT_EVENT_META[event_type]


#: The envelope's shape version. Downstream contracts against it; bump only on
#: a breaking change.
SCHEMA_VERSION = 1
