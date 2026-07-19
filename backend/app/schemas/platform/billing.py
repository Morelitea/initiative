"""Payloads for the billing service endpoints.

Parsed manually from the verified request body (see
``app.services.platform.billing``) rather than by FastAPI's body machinery;
excluded from the OpenAPI schema.
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field, model_validator

from app.core.messages import BillingMessages
from app.models.platform.billing import BillingSource
from app.models.platform.guild import GuildStatus
from app.schemas.base import SanitizedBaseModel


class BillingGuildTierApply(SanitizedBaseModel):
    """Body of ``POST /billing/guild-tier``.

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

    guild_id: int = Field(ge=1)
    event_id: str = Field(min_length=1, max_length=128)
    source: BillingSource
    # Acting human for manual ops (support grant id / staff id); NULL for
    # automated webhook-driven writes.
    actor: Optional[str] = Field(default=None, max_length=128)

    tier_name: Optional[str] = Field(default=None, max_length=64)
    max_storage_bytes: Optional[int] = Field(default=None, ge=0)
    max_users: Optional[int] = Field(default=None, ge=1)
    status: Optional[GuildStatus] = None

    @model_validator(mode="after")
    def _support_source_is_storage_only(self) -> "BillingGuildTierApply":
        """support_manual may only change the storage cap, and must name an
        actor; other fields require paddle_webhook or platinum_invoice.
        (The cannot-lower rule for the storage cap needs the current DB value
        and lives in the service — see ``apply_guild_tier``.)"""
        if self.source is BillingSource.support_manual:
            if not self.actor:
                raise ValueError(BillingMessages.ACTOR_REQUIRED)
            forbidden = {"tier_name", "max_users", "status"}
            if forbidden & self.model_fields_set:
                raise ValueError(BillingMessages.SUPPORT_SOURCE_RESTRICTED)
        return self


class BillingGuildTierRead(SanitizedBaseModel):
    """State of the billing-writable surface after (or instead of) a write.

    ``applied`` is False when the event id had already been claimed — the
    values shown are the current state, untouched by the replayed delivery.
    """

    guild_id: int
    tier_name: Optional[str] = None
    max_storage_bytes: Optional[int] = None
    max_users: Optional[int] = None
    status: GuildStatus
    member_count: int
    applied: bool


class BillingHeadcountRequest(SanitizedBaseModel):
    """Body of ``POST /billing/headcount`` — the per-user-billing read."""

    guild_id: int = Field(ge=1)


class BillingHeadcountRead(SanitizedBaseModel):
    guild_id: int
    member_count: int


class BillingUsageRequest(SanitizedBaseModel):
    """Body of ``POST /billing/usage`` — the storage read.

    The guild rides the signed body (not a query string) so the envelope's
    HMAC covers it, exactly like the headcount read.
    """

    guild_id: int = Field(ge=1)


class BillingUsageRead(SanitizedBaseModel):
    """Current stored bytes for one guild — the same figure
    ``enforce_storage_quota`` reads. Read-only; the app never pushes usage
    anywhere."""

    guild_id: int
    usage_bytes: int


class BillingPortalHandoffResponse(SanitizedBaseModel):
    """Billing-portal handoff token and its lifetime in seconds."""

    handoff_token: str
    expires_in_seconds: int
