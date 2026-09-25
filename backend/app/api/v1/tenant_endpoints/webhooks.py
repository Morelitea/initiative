"""Outbound webhook subscriptions for a guild.

Register a URL and the change events it should receive; the delivery worker
POSTs signed, content-free envelopes to it (see
``app.services.tenant.outbox_poller``).

**A subscription's reach is the scope it names.** ``initiative_id`` means that
initiative's changes; omitting it means the whole community's, which is why
registering one of those is a guild admin's to do. Nobody's standing is read at
delivery: an envelope is identifiers and changed column names, and a consumer
reads current state back through the REST path, where every gate applies to the
read. An installed app calling back does so on its own token, whose standing is
read on every call.

So a subscription is the community's integration configuration rather than the
personal property of whoever registered it, and it outlives their membership,
their role and their account. See
``history/webhook-scope-not-principal-design.md``.

  POST   /api/v1/c/{guild_id}/webhooks/subscriptions
    body: {target_url, event_types, fields?, initiative_id?}
    → returns subscription + plaintext hmac_secret (one-time)
  GET    /api/v1/c/{guild_id}/webhooks/subscriptions
  PATCH  /api/v1/c/{guild_id}/webhooks/subscriptions/{id}
  DELETE /api/v1/c/{guild_id}/webhooks/subscriptions/{id}

Every read includes ``dead_letter_count`` — how many of the poller's ledger
rows for that subscription (``app.services.tenant.outbox_poller``) gave up
retrying. It is the only surface a broken target has: the poller itself never
raises, so a nonzero count is what tells whoever owns the subscription to
check the target or deactivate it.

Who may rewrite or remove one is the row's own gates, the same ones that govern
the content it watches: initiative write access for an initiative-scoped
subscription, guild admin for a community-wide one. Authorship is not a gate in
this app.

An installed app registers and removes subscriptions on its installation token
(``history/app-principal-design.md`` §D9). What it may register depends on the
event types it names — each needs the read scope of its tool — so the two
routes take :func:`app.api.deps.app_scope_checked` and the service asks those
scopes of the install's standing. An install sees and removes only the
subscriptions it registered.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    GuildContext,
    RLSSessionDep,
    app_scope_checked,
    get_current_active_user,
    get_guild_membership,
)
from app.core import webhook_events
from app.core.messages import WebhookSubscriptionMessages
from app.db.guild_standing import InstallContext
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
    WebhookSubscriptionScopeError,
    WebhookSubscriptionVocabularyError,
)
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
    assert_target_url_is_public_async,
)

logger = logging.getLogger(__name__)

router = APIRouter(route_class=ActorRoute)

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
#: The routes an installed app may call. Registering asks the read scope of
#: each event type's tool, which the service checks once it has the body;
#: removing reaches only the install's own subscriptions.
SubscriptionsByEventType = Annotated[
    ActorContext,
    Depends(app_scope_checked(webhook_events.event_read_scopes(), per="event type")),
]


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


async def _named(
    row: WebhookSubscription,
    *,
    guild_id: int,
    dead_letter_count: int,
    actor: ActorContext | None = None,
) -> WebhookSubscriptionRead:
    """One subscription, with the guild and its creator named for its receiver.

    Minted rather than stored, and in the same sector its deliveries use, so
    what a receiver reads here is what it will be sent. An installed app that
    registered one names no person on it, and its standing already carries
    what the install calls the guild, so nothing is minted for it here.
    """
    if (
        isinstance(actor, InstallContext)
        and actor.guild_ref is not None
        and row.app_install_id == actor.install_id
        and row.created_by is None
    ):
        guild_ref, actor_refs = actor.guild_ref, {}
    else:
        guild_ref, actor_refs = await webhook_refs.name_for_subscriber(
            guild_id=guild_id,
            app_install_id=row.app_install_id,
            subscription_id=row.id,
            actor_ids=() if row.created_by is None else (row.created_by,),
        )
    return WebhookSubscriptionRead(
        id=row.id,
        guild_ref=guild_ref,
        initiative_id=row.initiative_id,
        created_by_ref=(None if row.created_by is None else actor_refs[row.created_by]),
        target_url=row.target_url,
        event_types=row.event_types,
        fields=row.fields,
        active=row.active,
        dead_letter_count=dead_letter_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post(
    "/subscriptions",
    response_model=WebhookSubscriptionCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription(
    payload: WebhookSubscriptionCreate,
    session: ActorSessionDep,
    guild_context: SubscriptionsByEventType,
) -> WebhookSubscriptionCreated:
    """Register a new webhook subscription.

    The HMAC secret is included in the response *only here*; subsequent reads
    omit it. The receiver must persist it from this response or rotate the
    subscription if they lose it.

    A subscription is the community's configuration: delivery carries the change
    log of the scope it names, the initiative it was registered against or, for
    one a guild admin registers, the whole community.

    An installed app registers one as its community, naming no person: each
    event type needs the read scope of its tool, a token narrowed to one
    initiative registers for that initiative only, and a community-wide one
    needs a token that is not narrowed. Otherwise 403 (``APP_SCOPE_REQUIRED``).

    Target policy: ``target_url`` must be https and resolve to a public unicast
    address; private, loopback and link-local addresses are rejected.
    """
    await _validate_target_url(str(payload.target_url))

    try:
        if isinstance(guild_context, InstallContext):
            (
                subscription,
                secret,
            ) = await subscriptions_service.create_install_subscription(
                session, context=guild_context, payload=payload
            )
        else:
            subscription, secret = await subscriptions_service.create_subscription(
                session,
                payload=payload,
                created_by=guild_context.user_id,
                guild_id=guild_context.guild_id,
            )
    except WebhookSubscriptionVocabularyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
        ) from exc
    except WebhookSubscriptionScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=exc.code
        ) from exc

    return WebhookSubscriptionCreated(
        # A subscription that was just created has no delivery history yet.
        **(
            await _named(
                subscription,
                guild_id=guild_context.guild_id,
                dead_letter_count=0,
                actor=guild_context,
            )
        ).model_dump(),
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
    counts = await subscriptions_service.dead_letter_counts(
        session, subscription_ids=[row.id for row in rows]
    )
    return [
        await _named(
            row,
            guild_id=guild_context.guild_id,
            dead_letter_count=counts.get(row.id, 0),
        )
        for row in rows
    ]


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

    Who may is the UPDATE policy — initiative write access, or guild admin for
    a community-wide subscription. ``target_url`` (when provided) is
    re-validated against the SSRF allowlist.
    """
    if payload.target_url is not None:
        await _validate_target_url(str(payload.target_url))

    try:
        row = await subscriptions_service.update_subscription(
            session,
            subscription_id=subscription_id,
            guild_id=guild_context.guild_id,
            payload=payload,
            actor_user_id=current_user.id,
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
    counts = await subscriptions_service.dead_letter_counts(
        session, subscription_ids=[row.id]
    )
    return await _named(
        row,
        guild_id=guild_context.guild_id,
        dead_letter_count=counts.get(row.id, 0),
    )


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_subscription(
    subscription_id: int,
    session: ActorSessionDep,
    guild_context: SubscriptionsByEventType,
) -> None:
    """Hard-delete a subscription. Who may is the DELETE policy, the same gates
    that govern the content it watches; a cross-guild lookup is a 404. An
    installed app reaches only the subscriptions it registered, and any other
    is a 404."""
    by_install = isinstance(guild_context, InstallContext)
    try:
        await subscriptions_service.delete_subscription(
            session,
            subscription_id=subscription_id,
            guild_id=guild_context.guild_id,
            actor_user_id=guild_context.user_id,
            by_install=by_install,
        )
    except WebhookSubscriptionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=WebhookSubscriptionMessages.NOT_FOUND,
        ) from exc
    if by_install:
        # An install's subscriptions are named in the install's own sector,
        # which outlives any one of them; there is nothing of this one's to
        # remove.
        return

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
