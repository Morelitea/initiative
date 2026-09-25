"""Delivering one notification to one person.

:func:`deliver` is the one way a notice reaches somebody: the bell line, then
email and push, resolved against the recipient's settings and never committing.
The link helpers here are what every notice points with.

A notification is read on the cross-guild ``/me/notifications`` surface, away
from the guild it was written in, so the people it names are named by their
handle rather than by whatever that one guild renders. The handle is the
identifier that reads the same everywhere and needs no permission resolved at
the moment someone opens the list.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import translate
from app.core.config import settings as app_config
from app.core.tools import Tool
from app.core.notification_categories import (
    Channel,
    category_of,
)
from app.models.platform.user import User
from app.models.platform.notification import Notification, NotificationType
from app.services import email as email_service
from app.services.platform import email_outbox
from app.services.platform import notification_prefs
from app.services.platform import user_notifications
from app.services.platform import push_notifications
from app.core.user_display import handle_of
from app.db.guild_standing import ActorContext, InstallContext
from app.models.tenant.guild_app import GuildApp
from app.services.notifications.rollup import _roll_up_comment

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppAuthor:
    """An installed app, as a notification names what it did.

    By its name in the community, and by no account: ``id`` is ``None``, so a
    recipient is never mistaken for the one who acted, and the ``*_id`` a
    notification records beside the name is empty.
    """

    name: str
    id: None = None


def actor_name(actor: "User | AppAuthor") -> str:
    """What a notification calls whoever caused it: a person's handle, or an
    installed app's name."""
    if isinstance(actor, AppAuthor):
        return actor.name
    return handle_of(actor)


async def author_of(
    session: AsyncSession, actor: ActorContext, user: User | None
) -> "User | AppAuthor":
    """Who a request's notifications say acted: the person, or — for an
    installed app — the install's name in its community, read from its own
    row on the request's session."""
    if user is not None:
        return user
    if not isinstance(actor, InstallContext):
        raise RuntimeError("a request with no person is an installed app's")
    name = (
        await session.exec(select(GuildApp.name).where(GuildApp.id == actor.install_id))
    ).scalar_one()
    return AppAuthor(name=name)


# My Tasks is the app root: the cross-guild list of everything assigned to you.
# Cross-guild notifications point here instead of at one guild's copy.
MY_TASKS_TARGET_PATH = "/"


@dataclass(frozen=True)
class Channels:
    """Which ways this notification may reach one recipient.

    ``in_app`` is applied by ``user_notifications.create_notification`` — the
    single place every notification is written — so notifiers read it only when
    they need to know whether a line exists. Email and push are the caller's to
    apply, because only the caller knows what it would say.
    """

    in_app: bool
    email: bool
    push: bool
    #: The document the three answers above came from. Every notifier needs it
    #: twice — once to pick channels, once to decide when the email may go —
    #: so resolving it here saves loading the same row again.
    prefs: Mapping[str, Any]


async def _channels(
    session: AsyncSession,
    recipient: User,
    *,
    notification_type: NotificationType,
    guild_id: int | None = None,
    prefs: Mapping[str, Any] | None = None,
) -> Channels:
    """How this recipient wants to hear about this, on each channel.

    ``prefs`` lets a caller fanning out to an audience resolve the whole set
    from one batch load rather than a query per recipient.
    """
    if prefs is None:
        prefs = await notification_prefs.prefs_for_delivery(recipient)
    # Holds are folded in here rather than left to each caller to remember,
    # through the one resolver the other two fan-out paths also use. Email is
    # the exception it makes for itself: a held email is deferred rather than
    # refused, so this asks only whether the account wants it and lets
    # ``email_due_at`` decide when it goes.
    allowed = {
        channel: notification_prefs.reachable(
            prefs,
            notification_type=notification_type,
            channel=channel,
            guild_id=guild_id,
            tz_name=recipient.timezone,
            last_active_at=recipient.last_active_at,
        )
        for channel in (Channel.in_app, Channel.push)
    }
    allowed[Channel.email] = notification_prefs.wants(
        prefs,
        notification_type=notification_type,
        channel=Channel.email,
        guild_id=guild_id,
    )
    return Channels(
        in_app=allowed[Channel.in_app],
        email=allowed[Channel.email],
        push=allowed[Channel.push],
        prefs=prefs,
    )


@dataclass(frozen=True)
class Push:
    """What a notification says on a device.

    ``data`` names the ids this one notification is about; its type, its
    community and where it opens are the three every push carries, and
    :func:`deliver` adds them.
    """

    title: str
    body: str
    data: Mapping[str, str | None] = field(default_factory=dict)


async def deliver(
    session: AsyncSession,
    *,
    recipient: User,
    notification_type: NotificationType,
    data: dict[str, Any],
    email: email_service.EmailPieces | None = None,
    push: Push | None = None,
    rollup_key: str | None = None,
    actor: "User | AppAuthor | None" = None,
    email_names_line: bool = True,
) -> Notification | None:
    """Tell one person one thing: the bell line, then email and push.

    Every notifier in the app delivers through here. It never commits — the
    caller's transaction is what the notice rides on, so a write that rolls
    back tells nobody.

    With a ``rollup_key`` the notice joins this recipient's unread line for
    that thread and the mail and the push go only when it opened one; without
    one each notice is its own line and its own interruption. ``actor`` is who
    the rolled-up line names.

    The email's link defaults to the line's smart link. ``email_names_line``
    ties the mail to the bell line so reading the line withdraws it; a notice
    waiting on somebody's decision leaves it off, because withdrawing that mail
    is the unsafe way round.
    """
    guild_id = data.get("guild_id")
    guild_id = guild_id if isinstance(guild_id, int) else None
    channels = await _channels(
        session, recipient, notification_type=notification_type, guild_id=guild_id
    )
    if rollup_key is None:
        opened = True
        notification = await user_notifications.create_notification(
            session,
            user_id=recipient.id,
            notification_type=notification_type,
            data=data,
            prefs=channels.prefs,
        )
    else:
        if actor is None:
            raise ValueError("a rolled-up notice names who acted")
        opened, notification = await _roll_up_comment(
            session,
            recipient=recipient,
            notification_type=notification_type,
            rollup_key=rollup_key,
            data=data,
            commenter_name=actor_name(actor),
            commenter_id=actor.id,
            prefs=channels.prefs,
        )
    if not opened:
        return notification
    if email is not None and channels.email:
        if email.link is None:
            email = replace(email, link=data.get("smart_link"))
        await email_outbox.enqueue(
            session,
            recipient,
            category=category_of(notification_type),
            guild_id=guild_id,
            notification_id=(
                notification.id
                if notification is not None and email_names_line
                else None
            ),
            prefs=channels.prefs,
            pieces=email,
        )
    if push is not None and channels.push:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=recipient.id,
                notification_type=notification_type,
                guild_id=guild_id,
                locale=_recipient_locale(recipient),
                title=push.title,
                body=push.body,
                data={
                    "type": notification_type.value,
                    **push.data,
                    "guild_id": str(guild_id),
                    "target_path": data.get("target_path", "/"),
                },
            )
        except Exception as exc:
            logger.error("Failed to send push notification: %s", exc, exc_info=True)
    return notification


def _normalize_target_path(target_path: str) -> str:
    if not target_path:
        return "/"
    return target_path if target_path.startswith("/") else f"/{target_path}"


def _build_smart_link(*, target_path: str, guild_id: int | None) -> str | None:
    if guild_id is None:
        return None
    normalized = _normalize_target_path(target_path)
    encoded = quote(normalized, safe="")
    base = app_config.APP_URL.rstrip("/") or "http://localhost:5173"
    return f"{base}/navigate?guild_id={guild_id}&target={encoded}"


# A tool entity's URL names its initiative (/i/{initiative}/projects/{id}), and
# a notifier holds only the entity id — reaching the initiative here would mean
# an extra load at every call site, and a stored target_path would go stale the
# moment an entity moved. So these emit an entity REFERENCE and let the client's
# /go resolver turn it into the canonical address on the way in.
def reference_path(kind: Tool | str, entity_id: int | None) -> str:
    """One entity's reference path, the same for every notifier and for any
    other service that addresses the entity.

    ``kind`` is a ``Tool``, or the name of a kind that lives inside one
    (``task``, ``event``), spelled the way the client's resolver speaks it —
    kebab singular. Without an id there is no entity to resolve, so the guild
    home is the landing spot.
    """
    if entity_id is None:
        return "/"
    name = kind.value if isinstance(kind, Tool) else kind
    return f"/go/{name.replace('_', '-')}/{entity_id}"


def _task_target_path(task_id: int | None, project_id: int | None) -> str:
    """Where a notice about a task opens — the task, or the project holding it
    when the notice names no one task."""
    if task_id:
        return reference_path("task", task_id)
    if project_id:
        return reference_path(Tool.project, project_id)
    # No entity to resolve — the guild home is the only honest landing spot now
    # that there is no guild-wide project list.
    return "/"


def _initiative_target_path(initiative_id: int | None) -> str:
    """An initiative is addressed directly rather than through the resolver: it
    is the thing tool references resolve INTO, so it has a stable address of its
    own."""
    if initiative_id is None:
        # No one initiative to open, so land on the guild's front page — which
        # is where the initiative list lives now that the standalone page is
        # gone. "/i" would only redirect here anyway.
        return "/"
    return f"/i/{initiative_id}"


def _recipient_locale(user: User) -> str:
    return getattr(user, "locale", None) or "en"


def _nt(key: str, locale: str, **kwargs: str | int) -> str:
    """Translate a push string from the ``notifications`` namespace.

    Push notifications carry only a ``title`` and ``body``. Email copy for the
    same events lives in the ``email`` namespace (``email_t``); the two are kept
    separate because their wording differs (push is terse, email is richer).
    """
    return translate(key, locale, namespace="notifications", **kwargs)


def _resolve_timezone(value: str | None) -> ZoneInfo:
    zone_id = value or "UTC"
    try:
        return ZoneInfo(zone_id)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")
