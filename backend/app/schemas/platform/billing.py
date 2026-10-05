"""Payloads for the billing service endpoints.

Parsed manually from the verified request body (see
``app.services.platform.billing``) rather than by FastAPI's body machinery;
excluded from the OpenAPI schema.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import Field, model_validator

from app.core.messages import BillingMessages
from app.models.platform.billing import BillingSource
from app.models.platform.identity_ref import REF_MAX_LENGTH
from app.models.platform.guild import BILLING_SETTABLE_STATUSES, CommunityStatus
from app.schemas.base import SanitizedBaseModel


_ACTOR_REQUIRED_SOURCES = frozenset(
    {BillingSource.support_manual, BillingSource.operator_manual}
)


class BillingCommunityTierApply(SanitizedBaseModel):
    """Body of ``POST /billing/community-tier``.

    Tier *definitions* live in the billing service's own database; what
    crosses this boundary is only the display label (``tier_name``) and the
    **computed** caps initiative already owns (``max_storage_bytes`` /
    ``max_users``), plus the lifecycle ``status``.

    The writable fields use omit-to-skip sentinel semantics (the service
    inspects ``model_fields_set``): omit a field to leave it untouched, send
    ``null`` to reset it to unlimited (or, for ``tier_name``, to no paid
    tier). ``event_id`` is the idempotency key claimed in
    ``billing_event_log`` before any write — a retried delivery with the
    same id is a safe no-op.
    """

    community_ref: str = Field(min_length=1, max_length=REF_MAX_LENGTH)
    event_id: str = Field(min_length=1, max_length=128)
    source: BillingSource
    # Acting human for manual ops (support grant id / staff id); NULL for
    # automated webhook-driven writes.
    actor: Optional[str] = Field(default=None, max_length=128)

    tier_name: Optional[str] = Field(default=None, max_length=64)
    max_storage_bytes: Optional[int] = Field(default=None, ge=0)
    max_users: Optional[int] = Field(default=None, ge=1)
    status: Optional[CommunityStatus] = None
    feature_keys: Optional[list[str]] = Field(default=None, max_length=64)
    plan_is_free: Optional[bool] = None

    @model_validator(mode="after")
    def _support_source_is_storage_only(self) -> "BillingCommunityTierApply":
        """support_manual may only change the storage cap, and must name an
        actor; other fields require paddle_webhook or platinum_invoice.
        (The cannot-lower rule for the storage cap needs the current DB value
        and lives in the service — see ``apply_guild_tier``.)"""
        if self.source in _ACTOR_REQUIRED_SOURCES and not self.actor:
            raise ValueError(BillingMessages.ACTOR_REQUIRED)
        if self.source is BillingSource.support_manual:
            forbidden = {"tier_name", "max_users", "status"}
            if forbidden & self.model_fields_set:
                raise ValueError(BillingMessages.SUPPORT_SOURCE_RESTRICTED)
        # Suspension is the platform operator's, and deletion is deletion's.
        if self.status is not None and self.status not in BILLING_SETTABLE_STATUSES:
            raise ValueError(BillingMessages.STATUS_NOT_SETTABLE)
        return self


class BillingCommunityTierRead(SanitizedBaseModel):
    """State of the billing-writable surface after (or instead of) a write.

    ``applied`` is False when the event id had already been claimed — the
    values shown are the current state, untouched by the replayed delivery.

    The guild is echoed by the reference the caller sent, which is the only
    name for it the two services share.
    """

    community_ref: str
    tier_name: Optional[str] = None
    max_storage_bytes: Optional[int] = None
    max_users: Optional[int] = None
    status: CommunityStatus
    feature_keys: list[str] = Field(default_factory=list)
    plan_is_free: Optional[bool] = None
    member_count: int
    applied: bool


class BillingCommunityNoticeKind(str, Enum):
    """What a community notice says. A closed set: billing picks one, and the
    words are ours."""

    trial_ending = "trial_ending"
    trial_ended = "trial_ended"


#: The sources that send a community notice. Only the trial's end, for now.
_NOTICE_SOURCES = frozenset({BillingSource.trial_expiry})


class BillingCommunityNotice(SanitizedBaseModel):
    """Body of ``POST /billing/community-notice``.

    Billing asks for one of a fixed set of notices to reach a community's seat;
    no free text crosses. ``recipient_user_ref`` is the billing reference of the
    person billing holds as the community's owner — the one a portal handoff
    signs — or None, and either way the community's current superadmins are who
    hears it when that person is not a member any more. ``event_id`` is claimed
    in ``billing_event_log`` like a tier write's, so a retried delivery tells
    nobody twice.
    """

    community_ref: str = Field(min_length=1, max_length=REF_MAX_LENGTH)
    event_id: str = Field(min_length=1, max_length=128)
    source: BillingSource
    kind: BillingCommunityNoticeKind
    recipient_user_ref: Optional[str] = Field(default=None, max_length=REF_MAX_LENGTH)
    trial_ends_on: date

    @model_validator(mode="after")
    def _source_sends_notices(self) -> "BillingCommunityNotice":
        if self.source not in _NOTICE_SOURCES:
            raise ValueError(BillingMessages.NOTICE_SOURCE_NOT_ALLOWED)
        return self


class BillingCommunityNoticeRead(SanitizedBaseModel):
    """Whether this delivery told anybody.

    False for a replayed event id (the first delivery did the telling), for a
    community that is deleted or suspended, and for one with nobody to tell.
    """

    delivered: bool


class BillingUsageRequest(SanitizedBaseModel):
    """Body of ``POST /billing/usage`` — the storage read.

    The guild rides the signed body (not a query string) so the envelope's
    HMAC covers it, like every other verb on this boundary.
    """

    community_ref: str = Field(min_length=1, max_length=REF_MAX_LENGTH)


class BillingUsageRead(SanitizedBaseModel):
    """Current stored bytes for one guild — the same figure
    ``enforce_storage_quota`` reads. Read-only; the app never pushes usage
    anywhere."""

    community_ref: str
    usage_bytes: int


class BillingCommunityNameRequest(SanitizedBaseModel):
    """Body of ``POST /billing/community-name``.

    The guild rides the signed body rather than a query string, so the
    envelope's HMAC covers it — like every other verb on this boundary.
    """

    community_ref: str = Field(min_length=1, max_length=REF_MAX_LENGTH)


class BillingCommunityNameRead(SanitizedBaseModel):
    """What a guild calls itself, so a person is shown that and not a reference.

    A reference is what the two services key on and is unreadable by design;
    somebody looking at a page about their own community should see its name.
    Nothing else about the guild travels with it.
    """

    community_ref: str
    name: str


class BillingCommunityStatusRequest(SanitizedBaseModel):
    """Body of ``POST /billing/community-status``.

    The guild rides the signed body rather than a query string, so the
    envelope's HMAC covers it — like every other verb on this boundary.
    """

    community_ref: str = Field(min_length=1, max_length=REF_MAX_LENGTH)


class BillingCommunityStatusRead(SanitizedBaseModel):
    """Where one guild is in its lifecycle, ``deleted`` included."""

    community_ref: str
    status: CommunityStatus


class BillingPortalHandoffResponse(SanitizedBaseModel):
    """Billing-portal handoff token and its lifetime in seconds."""

    handoff_token: str
    expires_in_seconds: int
