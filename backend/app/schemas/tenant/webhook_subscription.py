"""Webhook subscription request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict, Field, HttpUrl

from app.schemas.base import SanitizedBaseModel


class WebhookSubscriptionCreate(SanitizedBaseModel):
    """Body for ``POST /api/v1/auto/subscriptions``.

    Initiative-id and guild-id are NOT taken from the body — they
    come from the caller's delegation token (guild) and an optional
    delegation initiative_id claim.
    """

    target_url: HttpUrl
    event_types: list[str] = Field(min_length=1)
    #: Column names to narrow updates to. Omit for any change.
    fields: list[str] | None = Field(default=None, min_length=1)
    initiative_id: int | None = None


class WebhookSubscriptionUpdate(SanitizedBaseModel):
    target_url: HttpUrl | None = None
    event_types: list[str] | None = Field(default=None, min_length=1)
    fields: list[str] | None = Field(default=None, min_length=1)
    active: bool | None = None


class WebhookSubscriptionRead(SanitizedBaseModel):
    """Public view. Notably ``hmac_secret`` is NOT in here — once minted
    on create it never leaves the DB again. Receivers either store the
    secret from the create response or rotate the subscription.

    The guild and the creator are named by reference, because this view is read
    by whoever registered the subscription — which may be an app. ``id`` and
    ``initiative_id`` are per-guild-schema and say nothing without the guild.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    #: What this subscription's receiver calls the guild — the same name its
    #: deliveries arrive under, so the two can be matched. Pairwise: another
    #: subscriber holds an unrelated value for the same guild.
    guild_ref: str
    initiative_id: int | None
    #: Who registered it, named in the same sector as the guild.
    created_by_ref: str
    target_url: str
    event_types: list[str]
    fields: list[str] | None
    active: bool
    created_at: datetime
    updated_at: datetime


class WebhookSubscriptionCreated(WebhookSubscriptionRead):
    """One-time create response — includes the freshly-minted HMAC secret
    so the receiver can record it. Never re-emitted on subsequent reads."""

    hmac_secret: str
