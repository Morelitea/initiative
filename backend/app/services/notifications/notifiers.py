"""The notices content changes send, one function per kind of news.

Each builds what its notice says and hands it to :func:`delivery.deliver`.
Whoever calls one has already decided the recipient may be told (see
``app.services.tenant.audience``) and commits afterwards.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import email_t
from app.core.config import settings as app_config
from app.core.tools import Tool
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    RSVPStatus,
)
from app.models.platform.user import User
from app.models.platform.notification import NotificationType
from app.services import email as email_service
from app.core.user_display import handle_of
from app.services.notifications.delivery import (
    AppAuthor,
    Push,
    _build_smart_link,
    _initiative_target_path,
    _nt,
    _recipient_locale,
    _resolve_timezone,
    _task_target_path,
    actor_name,
    deliver,
    reference_path,
)
from app.services.notifications.rollup import _comment_rollup_key


async def notify_initiative_membership(
    session: AsyncSession,
    user: User,
    initiative_id: int,
    initiative_name: str,
    guild_id: int,
) -> None:
    """Tell somebody they were added to an initiative. The caller commits."""
    target_path = _initiative_target_path(initiative_id)
    locale = _recipient_locale(user)
    await deliver(
        session,
        recipient=user,
        notification_type=NotificationType.initiative_added,
        data={
            "initiative_id": initiative_id,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
        },
        email=email_service.initiative_added_pieces(user, initiative_name),
        push=Push(
            title=_nt("initiative.added.title", locale),
            body=_nt("initiative.added.body", locale, initiative=initiative_name),
            data={"initiative_id": str(initiative_id)},
        ),
    )


async def notify_initiative_join_requested(
    session: AsyncSession,
    managers: list[User],
    *,
    request_id: int,
    initiative_id: int,
    initiative_name: str,
    guild_id: int,
    requester: User,
    message: str | None = None,
) -> None:
    """Tell an initiative's managers that someone knocked. The caller commits.

    Addressed to the people who can answer it — the manager-role members — and
    it carries no initiative *content*, only who asked, what they said, and
    where to answer.
    """
    # Straight to the queue rather than the initiative: the recipient was told
    # about this to act on it, and only a manager is ever sent one.
    target_path = f"{_initiative_target_path(initiative_id)}/settings/members"
    link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    requester_name = handle_of(requester)
    for manager in managers:
        locale = _recipient_locale(manager)
        await deliver(
            session,
            recipient=manager,
            notification_type=NotificationType.initiative_join_requested,
            data={
                "request_id": request_id,
                "initiative_id": initiative_id,
                "guild_id": guild_id,
                "requester_id": requester.id,
                "requester_name": requester_name,
                "target_path": target_path,
                "smart_link": link,
            },
            email=email_service.initiative_join_request_pieces(
                manager,
                event="requested",
                initiative_name=initiative_name,
                link=link or app_config.APP_URL,
                requester=requester_name,
                message=message,
            ),
            push=Push(
                title=_nt("initiative.joinRequested.title", locale),
                body=_nt(
                    "initiative.joinRequested.body",
                    locale,
                    requester=requester_name,
                    initiative=initiative_name,
                ),
                data={"initiative_id": str(initiative_id)},
            ),
            # Waiting on a decision: reading the line in the app does not
            # withdraw the mail.
            email_names_line=False,
        )


async def notify_initiative_join_resolved(
    session: AsyncSession,
    requester: User,
    *,
    request_id: int,
    initiative_id: int,
    initiative_name: str,
    guild_id: int,
    approved: bool,
) -> None:
    """Tell the requester how their knock was answered. The caller commits.

    An approval points at the initiative — the membership row now exists, so the
    link resolves. A denial points at the directory instead, which is as far as
    they can go.
    """
    notification_type = (
        NotificationType.initiative_join_approved
        if approved
        else NotificationType.initiative_join_denied
    )
    target_path = _initiative_target_path(initiative_id if approved else None)
    link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    key = "initiative.joinApproved" if approved else "initiative.joinDenied"
    locale = _recipient_locale(requester)
    await deliver(
        session,
        recipient=requester,
        notification_type=notification_type,
        data={
            "request_id": request_id,
            "initiative_id": initiative_id,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": link,
        },
        email=email_service.initiative_join_request_pieces(
            requester,
            event="approved" if approved else "denied",
            initiative_name=initiative_name,
            link=link or app_config.APP_URL,
        ),
        push=Push(
            title=_nt(f"{key}.title", locale),
            body=_nt(f"{key}.body", locale, initiative=initiative_name),
            data={"initiative_id": str(initiative_id)},
        ),
        email_names_line=False,
    )


async def notify_project_added(
    session: AsyncSession,
    recipients: Sequence[User],
    *,
    initiative_name: str,
    project_name: str,
    project_id: int,
    initiative_id: int,
    guild_id: int,
) -> None:
    """Tell everybody a project was shared with that it is there. The caller
    commits."""
    target_path = reference_path(Tool.project, project_id)
    data = {
        "initiative_id": initiative_id,
        "project_id": project_id,
        "guild_id": guild_id,
        "target_path": target_path,
        "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
    }
    for user in recipients:
        locale = _recipient_locale(user)
        await deliver(
            session,
            recipient=user,
            notification_type=NotificationType.project_added,
            data=data,
            email=email_service.project_added_pieces(
                user,
                initiative_name=initiative_name,
                project_name=project_name,
                project_id=project_id,
            ),
            push=Push(
                title=_nt("project.added.title", locale),
                body=_nt(
                    "project.added.body",
                    locale,
                    project=project_name,
                    initiative=initiative_name,
                ),
                data={"project_id": str(project_id)},
            ),
        )


async def notify_document_mention(
    session: AsyncSession,
    *,
    mentioned_user: User,
    mentioned_by: "User | AppAuthor",
    document_id: int,
    document_name: str,
    guild_id: int,
    initiative_id: int | None = None,
) -> None:
    """Notify a user they were mentioned in a document.

    Rolled up per document: the mentions arrive from the editor each time it
    saves, so an unread line absorbs the next one rather than mailing again.
    """
    if mentioned_user.id == mentioned_by.id:
        return
    target_path = reference_path(Tool.document, document_id)
    mentioned_by_name = actor_name(mentioned_by)
    locale = _recipient_locale(mentioned_user)
    await deliver(
        session,
        recipient=mentioned_user,
        notification_type=NotificationType.mention,
        data={
            "document_id": document_id,
            "mentioned_by_name": mentioned_by_name,
            "mentioned_by_id": mentioned_by.id,
            "guild_id": guild_id,
            "initiative_id": initiative_id,
            "tool": Tool.document.value,
            "target_path": target_path,
            "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
        },
        email=email_service.EmailPieces(
            subject=email_t(
                "mention.document.subject", locale, document=document_name, escape=False
            ),
            headline=email_t("mention.document.title", locale),
            body=email_t(
                "mention.document.body",
                locale,
                actor=mentioned_by_name,
                document=document_name,
            ),
        ),
        push=Push(
            title=_nt("mention.document.title", locale),
            body=_nt(
                "mention.document.body",
                locale,
                actor=mentioned_by_name,
                document=document_name,
            ),
            data={"document_id": str(document_id)},
        ),
        rollup_key=_comment_rollup_key("document-body", document_id),
        actor=mentioned_by,
    )


async def notify_task_description_mention(
    session: AsyncSession,
    *,
    mentioned_user: User,
    mentioned_by: "User | AppAuthor",
    task_id: int,
    task_title: str,
    guild_id: int,
    initiative_id: int | None = None,
) -> None:
    """Notify a user they were mentioned in a task's description."""
    if mentioned_user.id == mentioned_by.id:
        return
    target_path = _task_target_path(task_id, None)
    mentioned_by_name = actor_name(mentioned_by)
    locale = _recipient_locale(mentioned_user)
    await deliver(
        session,
        recipient=mentioned_user,
        notification_type=NotificationType.mention,
        data={
            "task_id": task_id,
            "mentioned_by_name": mentioned_by_name,
            "mentioned_by_id": mentioned_by.id,
            "guild_id": guild_id,
            "initiative_id": initiative_id,
            "tool": Tool.project.value,
            "target_path": target_path,
            "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
        },
        email=email_service.EmailPieces(
            subject=email_t(
                "mention.taskDescription.subject", locale, task=task_title, escape=False
            ),
            headline=email_t("mention.taskDescription.title", locale),
            body=email_t(
                "mention.taskDescription.body",
                locale,
                actor=mentioned_by_name,
                task=task_title,
            ),
        ),
        push=Push(
            title=_nt("mention.taskDescription.title", locale),
            body=_nt(
                "mention.taskDescription.body",
                locale,
                actor=mentioned_by_name,
                task=task_title,
            ),
            data={"task_id": str(task_id)},
        ),
        actor=mentioned_by,
    )


def _comment_context_path(
    *,
    task_id: int | None,
    document_id: int | None,
    entity_type: str | None,
    entity_id: int | None,
) -> str | None:
    """Where a notice about a comment opens: the thread's parent.

    A task and a document are named by their own fields; any other tool parent
    arrives as an entity reference. ``None`` means the caller named no parent,
    and there is nowhere for the notice to point.
    """
    if task_id:
        return _task_target_path(task_id, None)
    if document_id:
        return reference_path(Tool.document, document_id)
    if entity_type and entity_id:
        return reference_path(entity_type, entity_id)
    return None


async def notify_comment_mention(
    session: AsyncSession,
    *,
    mentioned_user: User,
    mentioned_by: "User | AppAuthor",
    comment_id: int,
    task_id: int | None,
    document_id: int | None,
    context_title: str,
    guild_id: int,
    initiative_id: int | None = None,
    tool: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> None:
    """Notify a user they were mentioned in a comment. ``entity_type``/
    ``entity_id`` name the parent when it is a tool entity other than a
    document (a project, queue, counter group, calendar, or dashboard)."""
    if mentioned_user.id == mentioned_by.id:
        return
    target_path = _comment_context_path(
        task_id=task_id,
        document_id=document_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    if target_path is None:
        return
    mentioned_by_name = actor_name(mentioned_by)
    locale = _recipient_locale(mentioned_user)
    await deliver(
        session,
        recipient=mentioned_user,
        notification_type=NotificationType.mention,
        data={
            "comment_id": comment_id,
            "task_id": task_id,
            "document_id": document_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "mentioned_by_name": mentioned_by_name,
            "mentioned_by_id": mentioned_by.id,
            "guild_id": guild_id,
            "initiative_id": initiative_id,
            "tool": tool,
            "target_path": target_path,
            "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
        },
        email=email_service.EmailPieces(
            subject=email_t("mention.comment.subject", locale, escape=False),
            headline=email_t("mention.comment.title", locale),
            body=email_t(
                "mention.comment.body",
                locale,
                actor=mentioned_by_name,
                context=context_title,
            ),
        ),
        push=Push(
            title=_nt("mention.comment.title", locale),
            body=_nt(
                "mention.comment.body",
                locale,
                actor=mentioned_by_name,
                context=context_title,
            ),
            data={
                "comment_id": str(comment_id),
                "task_id": str(task_id) if task_id else None,
                "document_id": str(document_id) if document_id else None,
            },
        ),
        actor=mentioned_by,
    )


async def notify_task_mentioned_in_comment(
    session: AsyncSession,
    *,
    assignee: User,
    mentioned_by: "User | AppAuthor",
    comment_id: int,
    mentioned_task_id: int,
    mentioned_task_title: str,
    context_task_id: int | None,
    context_document_id: int | None,
    context_title: str,
    guild_id: int,
    initiative_id: int | None = None,
    tool: str | None = None,
    context_entity_type: str | None = None,
    context_entity_id: int | None = None,
) -> None:
    """Notify task assignee that their task was mentioned in a comment."""
    if assignee.id == mentioned_by.id:
        return
    target_path = _comment_context_path(
        task_id=context_task_id,
        document_id=context_document_id,
        entity_type=context_entity_type,
        entity_id=context_entity_id,
    )
    if target_path is None:
        return
    mentioned_by_name = actor_name(mentioned_by)
    locale = _recipient_locale(assignee)
    await deliver(
        session,
        recipient=assignee,
        notification_type=NotificationType.mention,
        data={
            "comment_id": comment_id,
            "mentioned_task_id": mentioned_task_id,
            "context_task_id": context_task_id,
            "context_document_id": context_document_id,
            "context_entity_type": context_entity_type,
            "context_entity_id": context_entity_id,
            "mentioned_by_name": mentioned_by_name,
            "mentioned_by_id": mentioned_by.id,
            "guild_id": guild_id,
            "initiative_id": initiative_id,
            "tool": tool,
            "target_path": target_path,
            "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
        },
        email=email_service.EmailPieces(
            subject=email_t("mention.task.subject", locale, escape=False),
            headline=email_t("mention.task.title", locale),
            body=email_t(
                "mention.task.body",
                locale,
                actor=mentioned_by_name,
                task=mentioned_task_title,
                context=context_title,
            ),
        ),
        push=Push(
            title=_nt("mention.task.title", locale),
            body=_nt(
                "mention.task.body",
                locale,
                actor=mentioned_by_name,
                task=mentioned_task_title,
                context=context_title,
            ),
            data={
                "comment_id": str(comment_id),
                "mentioned_task_id": str(mentioned_task_id),
            },
        ),
        actor=mentioned_by,
    )


async def notify_comment_on_task(
    session: AsyncSession,
    *,
    assignee: User,
    commenter: "User | AppAuthor",
    comment_id: int,
    task_id: int,
    task_title: str,
    project_name: str,
    guild_id: int,
    initiative_id: int | None = None,
    tool: str | None = None,
    project_id: int | None = None,
) -> None:
    """Notify task assignee that someone commented on their task.

    ``project_name`` is what the mail and the push say; ``project_id`` is what
    the bell reads the name back from when the line is opened.
    """
    if assignee.id == commenter.id:
        return
    target_path = _task_target_path(task_id, None)
    commenter_name = actor_name(commenter)
    locale = _recipient_locale(assignee)
    await deliver(
        session,
        recipient=assignee,
        notification_type=NotificationType.comment_on_task,
        data={
            "comment_id": comment_id,
            "task_id": task_id,
            "project_id": project_id,
            "commenter_name": commenter_name,
            "commenter_id": commenter.id,
            "guild_id": guild_id,
            "initiative_id": initiative_id,
            "tool": tool,
            "target_path": target_path,
            "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
        },
        email=email_service.EmailPieces(
            subject=email_t(
                "comment.onTask.subject", locale, task=task_title, escape=False
            ),
            headline=email_t("comment.onTask.title", locale),
            body=email_t(
                "comment.onTask.body", locale, actor=commenter_name, task=task_title
            ),
        ),
        push=Push(
            title=_nt("comment.onTask.title", locale),
            body=_nt(
                "comment.onTask.body", locale, actor=commenter_name, task=task_title
            ),
            data={"comment_id": str(comment_id), "task_id": str(task_id)},
        ),
        rollup_key=_comment_rollup_key("task", task_id),
        actor=commenter,
    )


async def notify_comment_on_resource(
    session: AsyncSession,
    *,
    owner: User,
    commenter: "User | AppAuthor",
    comment_id: int,
    entity_type: str,
    entity_id: int,
    entity_name: str,
    guild_id: int,
    initiative_id: int | None = None,
    tool: str | None = None,
    target: tuple[str, int] | None = None,
) -> None:
    """Notify a tool entity's creator that someone commented on it.

    One notification for every tool parent — project, document, queue,
    counter group, calendar, dashboard. ``entity_type`` is the Tool value.

    ``target`` says where the notice should OPEN where that is not the thing it
    is about: a wiki page has no address taking only its own id, so a notice
    about one opens its wiki. It defaults to the entity itself.
    """
    if owner.id == commenter.id:
        return
    target_path = reference_path(*(target or (entity_type, entity_id)))
    commenter_name = actor_name(commenter)
    locale = _recipient_locale(owner)
    await deliver(
        session,
        recipient=owner,
        notification_type=NotificationType.comment_on_resource,
        data={
            "comment_id": comment_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "commenter_name": commenter_name,
            "commenter_id": commenter.id,
            "guild_id": guild_id,
            "initiative_id": initiative_id,
            "tool": tool,
            "target_path": target_path,
            "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
        },
        email=email_service.EmailPieces(
            subject=email_t(
                "comment.onResource.subject", locale, context=entity_name, escape=False
            ),
            headline=email_t("comment.onResource.title", locale),
            body=email_t(
                "comment.onResource.body",
                locale,
                actor=commenter_name,
                context=entity_name,
            ),
        ),
        push=Push(
            title=_nt("comment.onResource.title", locale),
            body=_nt(
                "comment.onResource.body",
                locale,
                actor=commenter_name,
                context=entity_name,
            ),
            data={
                "comment_id": str(comment_id),
                "entity_type": entity_type,
                "entity_id": str(entity_id),
            },
        ),
        rollup_key=_comment_rollup_key(entity_type, entity_id),
        actor=commenter,
    )


async def notify_comment_reply(
    session: AsyncSession,
    *,
    parent_author: User,
    replier: "User | AppAuthor",
    comment_id: int,
    task_id: int | None,
    document_id: int | None,
    context_title: str,
    guild_id: int,
    initiative_id: int | None = None,
    tool: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> None:
    """Notify parent comment author that someone replied to their comment."""
    if parent_author.id == replier.id:
        return
    target_path = _comment_context_path(
        task_id=task_id,
        document_id=document_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    if target_path is None:
        return
    replier_name = actor_name(replier)
    locale = _recipient_locale(parent_author)
    await deliver(
        session,
        recipient=parent_author,
        notification_type=NotificationType.comment_reply,
        data={
            "comment_id": comment_id,
            "task_id": task_id,
            "document_id": document_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "replier_name": replier_name,
            "replier_id": replier.id,
            "guild_id": guild_id,
            "initiative_id": initiative_id,
            "tool": tool,
            "target_path": target_path,
            "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
        },
        email=email_service.EmailPieces(
            subject=email_t("comment.reply.subject", locale, escape=False),
            headline=email_t("comment.reply.title", locale),
            body=email_t(
                "comment.reply.body", locale, actor=replier_name, context=context_title
            ),
        ),
        push=Push(
            title=_nt("comment.reply.title", locale),
            body=_nt(
                "comment.reply.body", locale, actor=replier_name, context=context_title
            ),
            data={
                "comment_id": str(comment_id),
                "task_id": str(task_id) if task_id else None,
                "document_id": str(document_id) if document_id else None,
            },
        ),
        actor=replier,
    )


# Calendar event notifications


def _format_event_when(event: CalendarEvent, recipient: User) -> str:
    """Human-readable event start, localized to the recipient's timezone.

    All-day events show just the date; timed events convert the stored UTC
    instant into the recipient's IANA timezone and append the zone abbrev
    (e.g. ``Wed, Jul 1, 2026 at 2:30 PM PDT``).
    """
    if event.all_day:
        return event.start_at.strftime("%a, %b %-d, %Y")
    tz = _resolve_timezone(recipient.timezone)
    local = event.start_at.astimezone(tz)
    return local.strftime("%a, %b %-d, %Y at %-I:%M %p %Z")


#: Calendar -> its initiative, for the life of one session. Keyed by guild as
#: well: per-guild schemas mean two calendars can hold the same id.
_CALENDAR_INITIATIVES = "_calendar_initiatives"


async def _calendar_initiative(
    session: AsyncSession, *, calendar_id: int, guild_id: int
) -> int | None:
    """Which initiative a calendar belongs to.

    Memoised, because an event notification is written once per recipient:
    cancelling an event with fifty attendees asked this fifty times for the one
    calendar. A calendar does not change initiative, so a session-lifetime
    answer is the same answer.
    """
    memo: dict[tuple[int, int], int | None] = session.info.setdefault(
        _CALENDAR_INITIATIVES, {}
    )
    key = (guild_id, calendar_id)
    if key not in memo:
        memo[key] = (
            await session.exec(
                select(Calendar.initiative_id).where(Calendar.id == calendar_id)
            )
        ).scalar_one_or_none()
    return memo[key]


async def _event_data(
    session: AsyncSession, event: CalendarEvent, guild_id: int, **extra
) -> dict:
    """One event notification's payload, including where it happened.

    The initiative is read from the event's calendar here rather than passed in
    by each caller: every event notification is built through this one function,
    so this is the place none of them can forget it. A guild-level calendar has
    no initiative, and the notification then lights its community and nothing
    inside it.
    """
    target_path = reference_path("event", event.id)
    initiative_id = await _calendar_initiative(
        session, calendar_id=event.calendar_id, guild_id=guild_id
    )
    data = {
        "event_id": event.id,
        "start_at": event.start_at.isoformat(),
        "guild_id": guild_id,
        "initiative_id": initiative_id,
        "tool": Tool.calendar.value,
        "target_path": target_path,
        "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
    }
    data.update(extra)
    return data


async def notify_event_invitation(
    session: AsyncSession,
    *,
    attendee: User,
    organizer: "User | AppAuthor",
    event: CalendarEvent,
    guild_id: int,
) -> None:
    """Notify a user they were added as an attendee on a calendar event."""
    if attendee.id == organizer.id:
        return
    organizer_name = actor_name(organizer)
    when = _format_event_when(event, attendee)
    locale = _recipient_locale(attendee)
    await deliver(
        session,
        recipient=attendee,
        notification_type=NotificationType.event_invitation,
        data=await _event_data(session, event, guild_id, organizer_name=organizer_name),
        email=email_service.EmailPieces(
            subject=email_t(
                "event.invitation.subject", locale, event=event.title, escape=False
            ),
            headline=email_t("event.invitation.title", locale),
            body=email_t(
                "event.invitation.body",
                locale,
                organizer=organizer_name,
                event=event.title,
                when=when,
            ),
        ),
        push=Push(
            title=_nt("event.invitation.title", locale),
            body=_nt("event.invitation.body", locale, event=event.title, when=when),
            data={"event_id": str(event.id)},
        ),
    )


async def notify_event_updated(
    session: AsyncSession,
    *,
    attendee: User,
    editor: "User | AppAuthor",
    event: CalendarEvent,
    guild_id: int,
    time_changed: bool,
) -> None:
    """Notify an attendee that an event's details changed (or was rescheduled)."""
    if attendee.id == editor.id:
        return
    editor_name = actor_name(editor)
    when = _format_event_when(event, attendee)
    locale = _recipient_locale(attendee)
    key = "event.rescheduled" if time_changed else "event.updated"
    await deliver(
        session,
        recipient=attendee,
        notification_type=NotificationType.event_updated,
        data=await _event_data(
            session, event, guild_id, editor_name=editor_name, time_changed=time_changed
        ),
        email=email_service.EmailPieces(
            subject=email_t(f"{key}.subject", locale, event=event.title, escape=False),
            headline=email_t(f"{key}.title", locale),
            body=email_t(
                f"{key}.body", locale, editor=editor_name, event=event.title, when=when
            ),
        ),
        push=Push(
            title=_nt(f"{key}.title", locale),
            body=_nt(f"{key}.body", locale, event=event.title, when=when),
            data={"event_id": str(event.id)},
        ),
    )


async def notify_event_cancelled(
    session: AsyncSession,
    *,
    attendee: User,
    canceller: "User | AppAuthor",
    event: CalendarEvent,
    guild_id: int,
) -> None:
    """Notify an attendee that an event was cancelled (deleted)."""
    if attendee.id == canceller.id:
        return
    canceller_name = actor_name(canceller)
    when = _format_event_when(event, attendee)
    locale = _recipient_locale(attendee)
    await deliver(
        session,
        recipient=attendee,
        notification_type=NotificationType.event_cancelled,
        data=await _event_data(session, event, guild_id, canceller_name=canceller_name),
        email=email_service.EmailPieces(
            subject=email_t(
                "event.cancelled.subject", locale, event=event.title, escape=False
            ),
            headline=email_t("event.cancelled.title", locale),
            body=email_t(
                "event.cancelled.body",
                locale,
                canceller=canceller_name,
                event=event.title,
                when=when,
            ),
        ),
        push=Push(
            title=_nt("event.cancelled.title", locale),
            body=_nt("event.cancelled.body", locale, event=event.title, when=when),
            data={"event_id": str(event.id)},
        ),
    )


async def notify_event_rsvp(
    session: AsyncSession,
    *,
    organizer: User,
    responder: User,
    event: CalendarEvent,
    rsvp_status: RSVPStatus,
    guild_id: int,
) -> None:
    """Notify the organizer that an attendee responded to their event."""
    if organizer.id == responder.id:
        return
    responder_name = handle_of(responder)
    status_value = (
        rsvp_status.value if isinstance(rsvp_status, RSVPStatus) else str(rsvp_status)
    )
    locale = _recipient_locale(organizer)
    await deliver(
        session,
        recipient=organizer,
        notification_type=NotificationType.event_rsvp,
        data=await _event_data(
            session,
            event,
            guild_id,
            responder_name=responder_name,
            rsvp_status=status_value,
        ),
        email=email_service.EmailPieces(
            subject=email_t(
                "event.rsvp.subject", locale, event=event.title, escape=False
            ),
            headline=email_t("event.rsvp.title", locale),
            body=email_t(
                "event.rsvp.body",
                locale,
                responder=responder_name,
                status=status_value,
                event=event.title,
            ),
        ),
        push=Push(
            title=_nt("event.rsvp.title", locale),
            body=_nt(
                "event.rsvp.body",
                locale,
                responder=responder_name,
                status=status_value,
                event=event.title,
            ),
            data={"event_id": str(event.id)},
        ),
    )


async def notify_event_reminder(
    session: AsyncSession,
    *,
    recipient: User,
    event: CalendarEvent,
    guild_id: int,
) -> None:
    """Send a scheduled lead-time reminder for an upcoming event."""
    when = _format_event_when(event, recipient)
    locale = _recipient_locale(recipient)
    await deliver(
        session,
        recipient=recipient,
        notification_type=NotificationType.event_reminder,
        data=await _event_data(session, event, guild_id),
        email=email_service.EmailPieces(
            subject=email_t(
                "event.reminder.subject", locale, event=event.title, escape=False
            ),
            headline=email_t("event.reminder.title", locale),
            body=email_t("event.reminder.body", locale, event=event.title, when=when),
        ),
        push=Push(
            title=_nt("event.reminder.title", locale),
            body=_nt("event.reminder.body", locale, event=event.title, when=when),
            data={"event_id": str(event.id)},
        ),
    )


async def notify_post_published(
    session: AsyncSession,
    *,
    recipient: User,
    post_id: int,
    post_name: str,
    excerpt: str,
    author_name: str,
    author_id: int | None,
    guild_id: int,
    initiative_id: int | None = None,
) -> None:
    """Tell one person a notice has gone up on a board they can see.

    ``author_id`` is ``None`` when an installed app posted it.

    Takes the post's fields rather than the row: the scheduled path calls this
    from a sweep that commits between recipients, and a detached row would have
    to be re-fetched for each one.
    """
    if recipient.id == author_id:
        return
    target_path = reference_path(Tool.post, post_id)
    locale = _recipient_locale(recipient)
    await deliver(
        session,
        recipient=recipient,
        notification_type=NotificationType.post_published,
        data={
            "post_id": post_id,
            "author_name": author_name,
            "author_id": author_id,
            "guild_id": guild_id,
            "initiative_id": initiative_id,
            "tool": Tool.post.value,
            "target_path": target_path,
            "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
        },
        email=email_service.EmailPieces(
            subject=email_t(
                "post.published.subject", locale, post=post_name, escape=False
            ),
            headline=email_t("post.published.title", locale),
            body=email_t(
                "post.published.body", locale, actor=author_name, post=post_name
            ),
        ),
        push=Push(
            title=_nt("post.published.title", locale),
            body=_nt("post.published.body", locale, actor=author_name, post=post_name),
            data={"post_id": str(post_id)},
        ),
    )
