"""Webhook subscription request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class WebhookSubscriptionCreate(BaseModel):
    """Body for ``POST /api/v1/auto/subscriptions``.

    Initiative-id and guild-id are NOT taken from the body — they
    come from the caller's delegation token (guild) and an optional
    delegation initiative_id claim. ``workflow_id`` is opaque to us;
    we just store it so dispatched events can reference it.
    """

    target_url: HttpUrl
    event_types: list[str] = Field(min_length=1)
    initiative_id: int | None = None
    workflow_id: int | None = None


class WebhookSubscriptionUpdate(BaseModel):
    target_url: HttpUrl | None = None
    event_types: list[str] | None = Field(default=None, min_length=1)
    active: bool | None = None


class WebhookSubscriptionRead(BaseModel):
    """Public view. Notably ``hmac_secret`` is NOT in here — once minted
    on create it never leaves the DB again. Receivers either store the
    secret from the create response or rotate the subscription."""

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    guild_id: int
    initiative_id: int | None
    workflow_id: int | None
    created_by_user_id: int
    target_url: str
    event_types: list[str]
    active: bool
    created_at: datetime
    updated_at: datetime


class WebhookSubscriptionCreated(WebhookSubscriptionRead):
    """One-time create response — includes the freshly-minted HMAC secret
    so the receiver can record it. Never re-emitted on subsequent reads."""

    hmac_secret: str
