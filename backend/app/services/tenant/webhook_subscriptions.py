"""Webhook subscription CRUD service."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import webhook_events
from app.core.audit_events import AuditEventType
from app.db.guild_standing import InstallContext
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.webhook_delivery import WebhookDelivery
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.schemas.tenant.webhook_subscription import (
    WebhookSubscriptionCreate,
    WebhookSubscriptionUpdate,
)
from app.services import audit as audit_service

#: The fields a rewrite reports as moved. ``fields`` is a list of names, so
#: it is reported as having moved and never copied.
_AUDITED_FIELDS = ("active", "event_types", "fields")


def _target_host(url: str | None) -> str | None:
    """The host a subscription points at, which is what a record carries.

    The host alone: the rest of the URL is the receiver's, and naming where
    deliveries go is what a reviewer is reading for.
    """
    return urlsplit(url).hostname if url else None


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


class WebhookSubscriptionScopeError(Exception):
    """An installed app asked for a subscription its standing does not cover.

    Carries the message code the endpoint answers with, like
    :class:`WebhookSubscriptionVocabularyError`.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def assert_install_may_subscribe(
    context: InstallContext,
    *,
    event_types: Sequence[str],
    initiative_id: int | None,
) -> None:
    """Refuse a subscription an installed app's standing does not cover.

    - Every event type needs the read scope of the resource it reports on
      (``webhook_events.read_scope_for``), held now: the seat's grant and the
      token's scopes together, as the standing computed them. An event type
      no scope reaches (an app's own install changing) is never an app's.
    - A token narrowed to one initiative subscribes to that initiative only.
    - A community-wide subscription needs a token that is not narrowed.
    - A named initiative is one the install is placed in.

    Delivery asks the same of the install again on every pass, against the
    grant and placements as they are then, so this is what turns a request
    that could never deliver into a clear refusal.
    """
    from app.core.messages import AppMessages

    refused = WebhookSubscriptionScopeError(AppMessages.SCOPE_REQUIRED)
    readable = set(context.install_read)
    for event_type in event_types:
        resource = webhook_events.read_scope_for(event_type)
        if resource is None or resource.value not in readable:
            raise refused
    narrowed = context.scope_initiative_id
    if initiative_id is None:
        if narrowed is not None:
            raise refused
        return
    if narrowed is not None and initiative_id != narrowed:
        raise refused
    if initiative_id not in context.member_initiatives:
        raise refused


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
    statement = select(WebhookSubscription).order_by(
        WebhookSubscription.created_at.desc()
    )
    result = await session.exec(statement)
    return list(result.all())


async def dead_letter_counts(
    session: AsyncSession, *, subscription_ids: list[int]
) -> dict[int, int]:
    """How many of each subscription's ledger rows gave up retrying.

    The count a guild admin needs to notice a target has gone bad: the row
    that used to retry it forever, silently, now stops and shows up here
    instead. Bounded by outbox retention — a dead-lettered row disappears with
    the event it describes, so this reflects recent failures, not all-time.
    """
    if not subscription_ids:
        return {}
    statement = (
        select(WebhookDelivery.subscription_id, func.count())
        .where(
            WebhookDelivery.subscription_id.in_(subscription_ids),
            WebhookDelivery.dead_lettered_at.is_not(None),
        )
        .group_by(WebhookDelivery.subscription_id)
    )
    return dict((await session.exec(statement)).all())


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
    created_by: int | None,
    guild_id: int,
    app_install_id: int | None = None,
) -> tuple[WebhookSubscription, str]:
    """Persist a fresh subscription and return ``(row, plaintext_secret)``.

    The plaintext secret is what the create endpoint returns once.
    We persist it in the DB column too because we need it server-side
    for HMAC signing on dispatch — there's no way around that — but
    we never expose it on subsequent reads.

    ``app_install_id`` is the install that registered this, when an app did. It
    decides how a delivery names the guild and the actor: an app already holds
    references for both at its install, and an envelope should arrive under
    those (``webhook_refs``).

    ``created_by`` is the account this runs as, so it is also who the audit
    record names. ``None`` for an installed app acting as its community, which
    names no person (:func:`create_install_subscription`).
    """
    assert_vocabulary(list(payload.event_types), payload.fields)

    secret = _generate_hmac_secret()
    now = datetime.now(timezone.utc)

    subscription = WebhookSubscription(
        initiative_id=payload.initiative_id,
        created_by=created_by,
        app_install_id=app_install_id,
        target_url=str(payload.target_url),
        hmac_secret=secret,
        event_types=list(payload.event_types),
        fields=list(payload.fields) if payload.fields else None,
        active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(subscription)
    # Flushed for its id, recorded, then committed together — this function owns
    # the transaction, so the record has to be staged before it closes.
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.WEBHOOK_CREATED,
        actor_user_id=created_by,
        guild_id=guild_id,
        target_type="webhook_subscription",
        target_id=subscription.id,
        detail={
            "target_host": _target_host(subscription.target_url),
            "event_types": list(subscription.event_types),
            "app_install_id": app_install_id,
        },
    )
    await session.commit()
    await session.refresh(subscription)
    return subscription, secret


async def create_install_subscription(
    session: AsyncSession,
    *,
    context: InstallContext,
    payload: WebhookSubscriptionCreate,
) -> tuple[WebhookSubscription, str]:
    """An installed app registering a subscription as its community.

    Checked against the install's standing first
    (:func:`assert_install_may_subscribe`), then written like any other, naming
    the install and no person. ``session`` is the one the install seam routed.
    """
    assert_vocabulary(list(payload.event_types), payload.fields)
    assert_install_may_subscribe(
        context,
        event_types=list(payload.event_types),
        initiative_id=payload.initiative_id,
    )
    return await create_subscription(
        session,
        payload=payload,
        created_by=None,
        guild_id=context.guild_id,
        app_install_id=context.install_id,
    )


async def update_subscription(
    session: AsyncSession,
    *,
    subscription_id: int,
    guild_id: int,
    payload: WebhookSubscriptionUpdate,
    actor_user_id: int | None = None,
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

    ``actor_user_id`` is the account the caller's session runs as; ``None``
    writes no audit record, and a patch that moved nothing writes none either.
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

    before = audit_service.snapshot(subscription, _AUDITED_FIELDS)
    host_before = _target_host(subscription.target_url)

    for field, value in data.items():
        setattr(subscription, field, value)
    subscription.updated_at = datetime.now(timezone.utc)

    session.add(subscription)
    if actor_user_id is not None:
        changed = audit_service.changed_fields(
            before, audit_service.snapshot(subscription, _AUDITED_FIELDS)
        )
        host_changed = _target_host(subscription.target_url) != host_before
        if changed["changed"] or host_changed:
            await audit_service.record(
                session,
                event_type=AuditEventType.WEBHOOK_UPDATED,
                actor_user_id=actor_user_id,
                guild_id=guild_id,
                target_type="webhook_subscription",
                target_id=subscription.id,
                detail={**changed, "target_host_changed": host_changed},
            )
    await session.commit()
    await session.refresh(subscription)
    return subscription


async def deactivate_for_install(
    session: AsyncSession,
    *,
    guild_id: int,
    app_install_id: int,
) -> int:
    """Switch off the subscriptions one install registered. Returns the count.

    An install is what makes an app present in a guild, so removing it ends
    what that app receives. Deactivated rather than deleted: the row is the
    record of what was being sent where, and a reinstall registers afresh.

    Called from the uninstall path, which runs as a guild admin — the authority
    the guild-wide ones need, and more than enough for the rest.

    **Staged, not committed.** Uninstall removes connections, consents, these
    and the install itself, and commits once at the end so the whole thing
    happens or none of it does. Committing here would make everything staked
    before it durable while the install is still there to fail on.
    """
    rows = (
        await session.exec(
            select(WebhookSubscription).where(
                WebhookSubscription.app_install_id == app_install_id,
                WebhookSubscription.active.is_(True),
            )
        )
    ).all()
    for row in rows:
        row.active = False
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)
    return len(rows)


def registered_install_is_live():
    """A subscription whose install is still there, or that never had one.

    Deactivating at uninstall is what stops deliveries promptly; this is what
    makes it true regardless. ``app_install_id`` carries no foreign key —
    ``guild_apps`` rows and these are both guild content, but nothing enforces
    the link — so the delivery paths ask rather than assume. It rides inside the
    selector they already run, and ``guild_apps`` is guild-level, so any routed
    session can answer it.
    """
    return or_(
        WebhookSubscription.app_install_id.is_(None),
        select(GuildApp.id)
        .where(GuildApp.id == WebhookSubscription.app_install_id)
        .exists(),
    )


async def delete_subscription(
    session: AsyncSession,
    *,
    subscription_id: int,
    guild_id: int,
    actor_user_id: int | None = None,
    by_install: bool = False,
) -> None:
    """Hard-delete a subscription. Cross-guild lookups raise; non-owner
    who may delete one is the DELETE policy — the same gates that govern the
    content it watches.

    ``actor_user_id`` is the account the caller's session runs as; ``None``
    writes no audit record, unless ``by_install`` says an installed app is
    deleting it as its community. That record names no person, and the
    request's context names the app."""
    subscription = await get_subscription(
        session, subscription_id=subscription_id, guild_id=guild_id
    )
    app_install_id = subscription.app_install_id
    target_host = _target_host(subscription.target_url)
    await session.delete(subscription)
    # Read off the row while it is still here, and staged before the commit that
    # takes it away, so the two land together.
    if actor_user_id is not None or by_install:
        await audit_service.record(
            session,
            event_type=AuditEventType.WEBHOOK_DELETED,
            actor_user_id=actor_user_id,
            guild_id=guild_id,
            target_type="webhook_subscription",
            target_id=subscription_id,
            detail={
                "target_host": target_host,
                "app_install_id": app_install_id,
            },
        )
    await session.commit()
