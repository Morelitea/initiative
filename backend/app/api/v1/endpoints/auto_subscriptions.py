"""Webhook subscription endpoints for initiative-auto.

Authenticated via the standard ``get_current_user`` chain — auto
calls these via delegation JWTs (RS256, public key verifier), so the
acting user is always the workflow owner. Tenant isolation is by
RLS on the table; the endpoint adds an explicit ``guild_id`` filter
on every query as defense-in-depth.

Auto's flow:

  POST /api/v1/auto/subscriptions
    body: {target_url, event_types, initiative_id?, workflow_id?}
    → returns subscription + plaintext hmac_secret (one-time)
  GET  /api/v1/auto/subscriptions
  DELETE /api/v1/auto/subscriptions/{id}
  PATCH  /api/v1/auto/subscriptions/{id}

All four are guild-scoped via the active session's ``guild_id``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.models.user import User
from app.schemas.webhook_subscription import (
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreated,
    WebhookSubscriptionRead,
    WebhookSubscriptionUpdate,
)
from app.services import webhook_subscriptions as subscriptions_service
from app.services.webhook_subscriptions import WebhookSubscriptionNotFoundError

router = APIRouter()


@router.post(
    "/subscriptions",
    response_model=WebhookSubscriptionCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription(
    payload: WebhookSubscriptionCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> WebhookSubscriptionCreated:
    """Register a new webhook subscription.

    The HMAC secret is included in the response *only here*; subsequent
    reads omit it. The receiver must persist it from this response or
    rotate the subscription if they lose it.

    Authorization: tenant isolation is enforced by the table's RLS
    policy (``guild_isolation``) plus the explicit ``guild_id`` filter
    in the service layer. The caller's guild comes from
    ``GuildContext`` — the body never carries it.
    """
    subscription, secret = await subscriptions_service.create_subscription(
        session,
        payload=payload,
        created_by_user_id=current_user.id,
        guild_id=guild_context.guild_id,
    )

    return WebhookSubscriptionCreated(
        id=subscription.id,
        guild_id=subscription.guild_id,
        initiative_id=subscription.initiative_id,
        workflow_id=subscription.workflow_id,
        created_by_user_id=subscription.created_by_user_id,
        target_url=subscription.target_url,
        event_types=subscription.event_types,
        active=subscription.active,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
        hmac_secret=secret,
    )


@router.get("/subscriptions", response_model=list[WebhookSubscriptionRead])
async def list_subscriptions(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> list[WebhookSubscriptionRead]:
    """List subscriptions in the caller's guild. ``hmac_secret`` is
    intentionally absent from the response."""
    rows = await subscriptions_service.list_subscriptions(
        session, guild_id=guild_context.guild_id
    )
    return [WebhookSubscriptionRead.model_validate(row) for row in rows]


@router.patch(
    "/subscriptions/{subscription_id}",
    response_model=WebhookSubscriptionRead,
)
async def update_subscription(
    subscription_id: int,
    payload: WebhookSubscriptionUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> WebhookSubscriptionRead:
    """Partial-update a subscription's target_url, event_types, or active flag."""
    try:
        row = await subscriptions_service.update_subscription(
            session,
            subscription_id=subscription_id,
            guild_id=guild_context.guild_id,
            payload=payload,
        )
    except WebhookSubscriptionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WEBHOOK_SUBSCRIPTION_NOT_FOUND",
        ) from exc
    return WebhookSubscriptionRead.model_validate(row)


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_subscription(
    subscription_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> None:
    """Hard-delete a subscription. Cross-guild lookups 404."""
    try:
        await subscriptions_service.delete_subscription(
            session,
            subscription_id=subscription_id,
            guild_id=guild_context.guild_id,
        )
    except WebhookSubscriptionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WEBHOOK_SUBSCRIPTION_NOT_FOUND",
        ) from exc
