"""Webhook subscription CRUD service."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import func, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.schemas.tenant.webhook_subscription import (
    WebhookSubscriptionCreate,
    WebhookSubscriptionUpdate,
)


class WebhookSubscriptionNotFoundError(Exception):
    """Raised when the requested subscription doesn't exist under the
    caller's scope."""


class WebhookSubscriptionLimitError(Exception):
    """This member already holds as many subscriptions as the operator allows."""


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
) -> WebhookSubscription:
    """Fetch by id, scoped to the caller's guild. Raises
    :class:`WebhookSubscriptionNotFoundError` so cross-guild lookups
    leak "not found" rather than "forbidden"."""
    statement = select(WebhookSubscription).where(
        WebhookSubscription.id == subscription_id,
        WebhookSubscription.guild_id == guild_id,
    )
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
    # Count and insert under one lock, or two concurrent creates each see a
    # count below the cap and both land. Advisory locks are transaction-scoped
    # and keyed per (guild, member), so this serializes one member's own creates
    # and nothing else.
    await session.exec(
        text("SELECT pg_advisory_xact_lock(:guild, :user)").bindparams(
            guild=guild_id, user=created_by_user_id
        )
    )
    mine = await session.scalar(
        select(func.count())
        .select_from(WebhookSubscription)
        .where(WebhookSubscription.guild_id == guild_id)
        .where(WebhookSubscription.created_by_user_id == created_by_user_id)
    )
    if (mine or 0) >= settings.WEBHOOK_MAX_SUBSCRIPTIONS_PER_MEMBER:
        raise WebhookSubscriptionLimitError

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
    """
    subscription = await get_subscription(
        session, subscription_id=subscription_id, guild_id=guild_id
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
