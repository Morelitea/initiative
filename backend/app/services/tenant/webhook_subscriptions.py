"""Webhook subscription CRUD service."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import webhook_events
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.schemas.tenant.webhook_subscription import (
    WebhookSubscriptionCreate,
    WebhookSubscriptionUpdate,
)


class WebhookSubscriptionVocabularyError(Exception):
    """A subscription named an event type or field that could never fire.

    Carries the message code the endpoint answers with, so the check has one
    home rather than one per caller.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def assert_vocabulary(event_types: list[str] | None, fields: list[str] | None) -> None:
    """Reject event types and field names that could never fire.

    Callers pass the values the row will END UP with. Both vocabularies derive
    from the capture registry, so this is what turns a typo into a 400 rather
    than a subscription that looks healthy and never delivers.
    """
    from app.core.messages import WebhookSubscriptionMessages

    if event_types and webhook_events.unknown_event_types(event_types):
        raise WebhookSubscriptionVocabularyError(
            WebhookSubscriptionMessages.UNKNOWN_EVENT_TYPE
        )
    if fields and webhook_events.unknown_fields(fields, event_types or []):
        raise WebhookSubscriptionVocabularyError(
            WebhookSubscriptionMessages.UNKNOWN_FIELD
        )


class WebhookSubscriptionNotFoundError(Exception):
    """Raised when the requested subscription doesn't exist under the
    caller's scope."""


def _generate_hmac_secret() -> str:
    """Random opaque secret. 64 url-safe chars ≈ 384 bits of entropy —
    well above the 256 we need to make brute-forcing infeasible."""
    return secrets.token_urlsafe(48)


async def list_subscriptions(
    session: AsyncSession,
    *,
    guild_id: int,
) -> list[WebhookSubscription]:
    """List all subscriptions in the caller's guild.

    Relies on the table's RLS policy for tenant isolation; the
    ``guild_id`` filter here is defense-in-depth so test fixtures that
    don't set the RLS context still see correct results.
    """
    statement = (
        select(WebhookSubscription)
        .where(WebhookSubscription.guild_id == guild_id)
        .order_by(WebhookSubscription.created_at.desc())
    )
    result = await session.exec(statement)
    return list(result.all())


async def get_subscription(
    session: AsyncSession,
    *,
    subscription_id: int,
    guild_id: int,
    for_update: bool = False,
) -> WebhookSubscription:
    """Fetch by id, scoped to the caller's guild. Raises
    :class:`WebhookSubscriptionNotFoundError` so cross-guild lookups
    leak "not found" rather than "forbidden".

    ``for_update`` locks the row for the rest of the transaction, for callers
    that read it, decide something from it, and write it back.
    """
    statement = select(WebhookSubscription).where(
        WebhookSubscription.id == subscription_id,
        WebhookSubscription.guild_id == guild_id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await session.exec(statement)).one_or_none()
    if row is None:
        raise WebhookSubscriptionNotFoundError(
            f"webhook subscription {subscription_id} not found in guild {guild_id}"
        )
    return row


async def create_subscription(
    session: AsyncSession,
    *,
    payload: WebhookSubscriptionCreate,
    created_by_user_id: int,
    guild_id: int,
) -> tuple[WebhookSubscription, str]:
    """Persist a fresh subscription and return ``(row, plaintext_secret)``.

    The plaintext secret is what the create endpoint returns once.
    We persist it in the DB column too because we need it server-side
    for HMAC signing on dispatch — there's no way around that — but
    we never expose it on subsequent reads.
    """
    assert_vocabulary(list(payload.event_types), payload.fields)

    secret = _generate_hmac_secret()
    now = datetime.now(timezone.utc)

    subscription = WebhookSubscription(
        guild_id=guild_id,
        initiative_id=payload.initiative_id,
        created_by_user_id=created_by_user_id,
        target_url=str(payload.target_url),
        hmac_secret=secret,
        event_types=list(payload.event_types),
        fields=list(payload.fields) if payload.fields else None,
        active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(subscription)
    await session.commit()
    await session.refresh(subscription)
    return subscription, secret


async def update_subscription(
    session: AsyncSession,
    *,
    subscription_id: int,
    guild_id: int,
    payload: WebhookSubscriptionUpdate,
) -> WebhookSubscription:
    """Apply a partial update to an existing subscription.

    Who may rewrite one is decided by the gates, not here: the UPDATE policy is
    the same ``initiative_access(..., need_write=true)`` that governs the content
    the subscription watches, so someone who can edit an initiative's tasks can
    edit its webhooks. Authorship is not a gate in this app.

    The row is locked before the merged values are checked, because the check
    spans two columns a patch may touch separately. Validating against a row read
    outside the write lets two complementary patches — one narrowing the events,
    one widening the fields — each pass against state the other is about to
    replace, and commit a pair that matches nothing. Locking makes the second
    re-read what the first wrote.
    """
    subscription = await get_subscription(
        session, subscription_id=subscription_id, guild_id=guild_id, for_update=True
    )
    assert_vocabulary(
        payload.event_types
        if payload.event_types is not None
        else subscription.event_types,
        payload.fields if payload.fields is not None else subscription.fields,
    )

    data = payload.model_dump(exclude_unset=True)
    if "target_url" in data and data["target_url"] is not None:
        data["target_url"] = str(data["target_url"])

    for field, value in data.items():
        setattr(subscription, field, value)
    subscription.updated_at = datetime.now(timezone.utc)

    session.add(subscription)
    await session.commit()
    await session.refresh(subscription)
    return subscription


async def delete_subscription(
    session: AsyncSession,
    *,
    subscription_id: int,
    guild_id: int,
) -> None:
    """Hard-delete a subscription. Cross-guild lookups raise; non-owner
    who may delete one is the DELETE policy — the same gates that govern the
    content it watches."""
    subscription = await get_subscription(
        session, subscription_id=subscription_id, guild_id=guild_id
    )
    await session.delete(subscription)
    await session.commit()
