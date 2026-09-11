"""Outbound webhook subscriptions for a guild.

Register a URL and the change events it should receive; the delivery worker
POSTs signed, content-free envelopes to it (see
``app.services.tenant.outbox_poller``).

**A subscription never sees more than the member who created it.** Delivery
reads the change log *as that member*, so RLS decides which events reach the
target and keeps deciding as access changes — leaving an initiative or losing a
PAM grant stops the matching deliveries with no edit here. That is why these
routes need no permission of their own: a subscription's reach is its owner's
reach, and an app acting for a member acts at exactly that member's level.

``initiative_id`` narrows a subscription to one initiative. Omitting it means
"everything in this guild I can reach" — which for a guild admin is the guild,
and for a member is their initiatives.

  POST   /api/v1/g/{guild_id}/webhooks/subscriptions
    body: {target_url, event_types, fields?, initiative_id?}
    → returns subscription + plaintext hmac_secret (one-time)
  GET    /api/v1/g/{guild_id}/webhooks/subscriptions
  PATCH  /api/v1/g/{guild_id}/webhooks/subscriptions/{id}
  DELETE /api/v1/g/{guild_id}/webhooks/subscriptions/{id}

Mutation routes require the acting user to be the subscription's creator or a
guild admin — ordinary ownership, the same rule any other guild resource uses.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import WebhookSubscriptionMessages
from app.models.platform.user import User
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.schemas.tenant.webhook_subscription import (
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreated,
    WebhookSubscriptionRead,
    WebhookSubscriptionUpdate,
)
from app.services.tenant import webhook_refs
from app.services.tenant import webhook_subscriptions as subscriptions_service
from app.services.tenant.webhook_subscriptions import (
    WebhookSubscriptionNotFoundError,
    WebhookSubscriptionVocabularyError,
)
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
    assert_target_url_is_public_async,
)

logger = logging.getLogger(__name__)

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _validate_target_url(url: str) -> None:
    """Reject URLs that resolve into private/loopback/link-local space.

    Async because DNS resolution can block; we don't want to stall the
    event loop on a slow resolver. Raises HTTPException with codes the
    frontend can localize.
    """
    try:
        await assert_target_url_is_public_async(url)
    except WebhookTargetUrlPrivateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=WebhookSubscriptionMessages.PRIVATE_TARGET_URL,
        ) from exc
    except WebhookTargetUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=WebhookSubscriptionMessages.INVALID_TARGET_URL,
        ) from exc


async def _named(row: WebhookSubscription) -> WebhookSubscriptionRead:
    """One subscription, with the guild and its creator named for its receiver.

    Minted rather than stored, and in the same sector its deliveries use, so
    what a receiver reads here is what it will be sent.
    """
    guild_ref, actor_refs = await webhook_refs.name_for_subscriber(
        guild_id=row.guild_id,
        app_install_id=row.app_install_id,
        subscription_id=row.id,
        actor_ids=(row.created_by,),
    )
    return WebhookSubscriptionRead(
        id=row.id,
        guild_ref=guild_ref,
        initiative_id=row.initiative_id,
        created_by_ref=actor_refs[row.created_by],
        target_url=row.target_url,
        event_types=row.event_types,
        fields=row.fields,
        active=row.active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post(
    "/subscriptions",
    response_model=WebhookSubscriptionCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription(
    request: Request,
    payload: WebhookSubscriptionCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> WebhookSubscriptionCreated:
    """Register a new webhook subscription.

    The HMAC secret is included in the response *only here*; subsequent reads
    omit it. The receiver must persist it from this response or rotate the
    subscription if they lose it.

    Any member of the guild may register one, because doing so grants no access:
    delivery reads the change log as this creator, so the target receives
    exactly what they can see and nothing more.

    Target policy: ``target_url`` must be https and resolve to a public unicast
    address; private, loopback and link-local addresses are rejected.
    """
    await _validate_target_url(str(payload.target_url))

    try:
        subscription, secret = await subscriptions_service.create_subscription(
            session,
            payload=payload,
            created_by=current_user.id,
            guild_id=guild_context.guild_id,
            # Set when an app registered this through its delegation. The
            # install decides which names its deliveries arrive under.
            app_install_id=getattr(request.state, "delegating_install_id", None),
        )
    except WebhookSubscriptionVocabularyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
        ) from exc

    return WebhookSubscriptionCreated(
        **(await _named(subscription)).model_dump(),
        hmac_secret=secret,
    )


@router.get("/subscriptions", response_model=list[WebhookSubscriptionRead])
async def list_subscriptions(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> list[WebhookSubscriptionRead]:
    """List subscriptions in the caller's guild. ``hmac_secret`` is
    intentionally absent from the response — it is returned once, on create."""
    rows = await subscriptions_service.list_subscriptions(
        session, guild_id=guild_context.guild_id
    )
    return [await _named(row) for row in rows]


@router.patch(
    "/subscriptions/{subscription_id}",
    response_model=WebhookSubscriptionRead,
)
async def update_subscription(
    subscription_id: int,
    payload: WebhookSubscriptionUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> WebhookSubscriptionRead:
    """Partial-update target_url, event_types, or active flag.

    Only the acting user who created it, or a guild admin, may mutate.
    ``target_url`` (when provided) is re-validated against the SSRF allowlist.
    """
    if payload.target_url is not None:
        await _validate_target_url(str(payload.target_url))

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
            detail=WebhookSubscriptionMessages.NOT_FOUND,
        ) from exc
    except WebhookSubscriptionVocabularyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
        ) from exc
    return await _named(row)


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_subscription(
    subscription_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Hard-delete a subscription. Cross-guild lookups 404; non-owner
    non-admin attempts 403."""
    try:
        await subscriptions_service.delete_subscription(
            session,
            subscription_id=subscription_id,
            guild_id=guild_context.guild_id,
        )
    except WebhookSubscriptionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=WebhookSubscriptionMessages.NOT_FOUND,
        ) from exc

    # The names this subscription minted for itself. Only its own sector: one an
    # app registered is named in that app's, which belongs to the install and
    # outlives any single subscription.
    #
    # Reported rather than raised, like the same step on app uninstall: the row
    # is already gone and committed, so failing the request here would answer
    # "no" to something that happened, and the retry it invites answers 404.
    try:
        await webhook_refs.drop_subscription_refs(
            guild_id=guild_context.guild_id, subscription_id=subscription_id
        )
    except SQLAlchemyError:
        logger.warning(
            "webhook refs: references for subscription %s in guild %s were not "
            "removed; they name a subscription that no longer exists",
            subscription_id,
            guild_context.guild_id,
        )
