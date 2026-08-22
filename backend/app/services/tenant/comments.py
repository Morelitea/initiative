"""Comments across every commentable surface.

``TOOL_COMMENT_TARGETS`` is the registry: **every** ``Tool`` entity is
commentable — one nullable FK per tool on ``comments``, drift-tested against
the enum — plus the task, the one content-level extra (it anchors to its
project for access). Reading a thread takes read access on the parent, posting
takes write access, exactly as it always has for tasks and documents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Optional, Set, cast

from sqlalchemy import ColumnElement
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import (
    CalendarMessages,
    CommentMessages,
    CounterMessages,
    DashboardMessages,
    QueueMessages,
)
from app.core.tools import Tool
from app.models.tenant.calendar import Calendar
from app.models.tenant.comment import Comment
from app.models.tenant.counter import CounterGroup
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.document import Document
from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.queue import Queue
from app.models.tenant.task import Task
from app.models.platform.user import User
from app.services import rls as rls_service
from app.services import notifications
from app.services import permissions as permissions_service
from app.services.tenant.mention_parser import (
    extract_mentioned_user_ids,
    extract_mentioned_task_ids,
)

logger = logging.getLogger(__name__)


class CommentError(Exception):
    """Base error for comment operations."""


class CommentNotFoundError(CommentError):
    """Raised when a linked resource cannot be found."""


class CommentPermissionError(CommentError):
    """Raised when the user lacks permission to comment."""


class CommentValidationError(CommentError):
    """Raised when the payload is inconsistent."""


@dataclass(frozen=True)
class CommentTarget:
    """How one tool binds to comments: its model, the FK column on
    ``comments`` (``{tool}_id``), and the codes its failures report.
    ``feature_disabled`` is ``None`` for core tools, which have no master
    switch."""

    tool: Tool
    model: type[SQLModel]
    not_found: str
    feature_disabled: Optional[str] = None

    @property
    def column(self) -> str:
        return f"{self.tool.value}_id"


# Every Tool is commentable — comments_test asserts this spans the enum, and
# that the columns here match the model and the RLS parent registry
# (app.db.initiative_rls._COMMENT_PARENTS).
TOOL_COMMENT_TARGETS: dict[Tool, CommentTarget] = {
    Tool.project: CommentTarget(
        Tool.project, Project, CommentMessages.TARGET_NOT_FOUND
    ),
    Tool.document: CommentTarget(
        Tool.document, Document, CommentMessages.DOCUMENT_NOT_FOUND
    ),
    Tool.queue: CommentTarget(
        Tool.queue,
        Queue,
        CommentMessages.TARGET_NOT_FOUND,
        QueueMessages.FEATURE_DISABLED,
    ),
    Tool.counter_group: CommentTarget(
        Tool.counter_group,
        CounterGroup,
        CommentMessages.TARGET_NOT_FOUND,
        CounterMessages.FEATURE_DISABLED,
    ),
    Tool.calendar: CommentTarget(
        Tool.calendar,
        Calendar,
        CommentMessages.TARGET_NOT_FOUND,
        CalendarMessages.FEATURE_DISABLED,
    ),
    Tool.dashboard: CommentTarget(
        Tool.dashboard,
        Dashboard,
        CommentMessages.TARGET_NOT_FOUND,
        DashboardMessages.FEATURE_DISABLED,
    ),
}

_TARGETS_BY_COLUMN: dict[str, CommentTarget] = {
    target.column: target for target in TOOL_COMMENT_TARGETS.values()
}

#: Every comment-parent column, task first — the single-parent rule and the
#: create/list surfaces all read this tuple.
COMMENT_PARENT_COLUMNS: tuple[str, ...] = ("task_id", *_TARGETS_BY_COLUMN)


@dataclass
class _ParentContext:
    """The resolved parent of a comment, whichever shape it takes.

    A task comment anchors to its project (``task``/``project`` set); a tool
    comment carries the tool and its row (``tool``/``resource`` set). Either
    way the fields every caller needs — the comments column, the parent id,
    the initiative (``None`` for a guild-level calendar), a display title —
    are filled.
    """

    column: str
    entity_id: int
    initiative_id: Optional[int]
    title: str
    task: Optional[Task] = None
    project: Optional[Project] = None
    tool: Optional[Tool] = None
    resource: Optional[SQLModel] = None


def _single_target(ids: dict[str, Optional[int]]) -> tuple[str, int]:
    provided = [(column, value) for column, value in ids.items() if value is not None]
    if len(provided) != 1:
        raise CommentValidationError(CommentMessages.PROVIDE_ONE_ENTITY)
    return provided[0]


def _comment_target(comment: Comment) -> tuple[str, int]:
    for column in COMMENT_PARENT_COLUMNS:
        value = getattr(comment, column)
        if value is not None:
            return column, value
    raise CommentValidationError(CommentMessages.NOT_LINKED)


async def _get_task_context(
    session: AsyncSession,
    *,
    task_id: int,
    guild_id: int,
) -> Optional[_ParentContext]:
    stmt = (
        select(Task, Project, Initiative)
        .join(Project, Project.id == Task.project_id)
        .join(Initiative, Initiative.id == Project.initiative_id)
        .where(
            Task.id == task_id,
            Initiative.guild_id == guild_id,
        )
    )
    result = await session.exec(stmt)
    row = result.one_or_none()
    if not row:
        return None
    task, project, initiative = row
    return _ParentContext(
        column="task_id",
        entity_id=cast(int, task.id),
        initiative_id=initiative.id,
        title=task.title,
        task=task,
        project=project,
    )


async def _get_tool_context(
    session: AsyncSession,
    target: CommentTarget,
    *,
    entity_id: int,
    guild_id: int,
) -> Optional[_ParentContext]:
    """Load one tool row with its initiative. The guild is checked through the
    initiative when the row has one, else through the row itself (a guild-level
    calendar names no initiative)."""
    stmt = (
        select(target.model)
        .where(target.model.id == entity_id)  # type: ignore[attr-defined]
        .options(selectinload(target.model.initiative))  # type: ignore[attr-defined]
    )
    row = (await session.exec(stmt)).one_or_none()
    if row is None:
        return None
    initiative = row.initiative
    owner_guild = initiative.guild_id if initiative is not None else row.guild_id
    if owner_guild != guild_id:
        return None
    return _ParentContext(
        column=target.column,
        entity_id=cast(int, row.id),
        initiative_id=row.initiative_id,
        title=row.name,
        tool=target.tool,
        resource=row,
    )


async def _load_parent(
    session: AsyncSession,
    *,
    column: str,
    entity_id: int,
    guild_id: int,
) -> Optional[_ParentContext]:
    if column == "task_id":
        return await _get_task_context(session, task_id=entity_id, guild_id=guild_id)
    return await _get_tool_context(
        session, _TARGETS_BY_COLUMN[column], entity_id=entity_id, guild_id=guild_id
    )


async def _shares_resource(
    session: AsyncSession,
    tool: Tool,
    id_col: ColumnElement[int],
    *,
    resource_id: int,
    user_id: int,
    guild_id: int,
    access: str,
) -> bool:
    """Whether the sharing gate lets this request reach one resource by id.

    The id is already known, so this asks the gate directly rather than loading
    the row and its grants to run the engine over them.
    """
    stmt = select(id_col).where(
        id_col == resource_id,
        permissions_service.dac_scope_clause(
            tool, id_col, user_id, guild_id=guild_id, access=access
        ),
    )
    return (await session.exec(stmt)).first() is not None


async def _ensure_parent_access(
    session: AsyncSession,
    ctx: _ParentContext,
    *,
    user: User,
    access: str = "read",
) -> None:
    """Ensure the user can reach the comment's parent at ``access`` level.

    A task inherits from its project; a tool entity answers for itself. The
    sharing decision is the same one the parent's own endpoints make: the
    tool's master switch first, then DAC — where a request that reaches the
    whole guild (guild admin, or a live PAM grant at the right level) needs no
    grant row.
    """
    if ctx.task is not None:
        anchor_tool, anchor_model, anchor_row = Tool.project, Project, ctx.project
    else:
        target = TOOL_COMMENT_TARGETS[cast(Tool, ctx.tool)]
        initiative = getattr(ctx.resource, "initiative", None)
        if (
            target.feature_disabled is not None
            and initiative is not None
            and not getattr(initiative, target.tool.view_permission)
        ):
            raise CommentPermissionError(target.feature_disabled)
        anchor_tool, anchor_model, anchor_row = target.tool, target.model, ctx.resource

    guild_id = anchor_row.guild_id
    if permissions_service.request_bypasses_dac(guild_id, access=access):
        return
    if await _shares_resource(
        session,
        anchor_tool,
        anchor_model.id,  # type: ignore[attr-defined]
        resource_id=cast(int, anchor_row.id),
        user_id=cast(int, user.id),
        guild_id=guild_id,
        access=access,
    ):
        return
    raise CommentPermissionError(CommentMessages.PERMISSION_DENIED)


def serialize_comment(comment: Comment):
    """The read shape of one comment. A task comment reports its task's
    project — resolved by whichever service call loaded the parent — through
    the same ``project_id`` field a project comment fills from its own column.
    """
    from app.schemas.tenant.comment import CommentRead

    read = CommentRead.model_validate(comment)
    task_project_id = getattr(comment, "_task_project_id", None)
    if task_project_id is not None:
        read.project_id = task_project_id
    return read


async def _get_comment(
    session: AsyncSession,
    *,
    comment_id: int,
) -> Optional[Comment]:
    stmt = select(Comment).where(Comment.id == comment_id)
    result = await session.exec(stmt)
    return result.one_or_none()


def _parent_not_found(column: str) -> str:
    if column == "task_id":
        return CommentMessages.TASK_NOT_FOUND
    return _TARGETS_BY_COLUMN[column].not_found


async def _resolved_parent(
    session: AsyncSession,
    *,
    column: str,
    entity_id: int,
    guild_id: int,
    user: User,
    access: str,
) -> _ParentContext:
    """Load + authorize one comment parent, raising the comment-shaped errors."""
    ctx = await _load_parent(
        session, column=column, entity_id=entity_id, guild_id=guild_id
    )
    if ctx is None:
        raise CommentNotFoundError(_parent_not_found(column))
    await _ensure_parent_access(session, ctx, user=user, access=access)
    return ctx


def _stamp_task_project(ctx: _ParentContext, *comments: Comment) -> None:
    """Record the task's project on loaded rows for serialization — a plain
    attribute, never the ``project_id`` column (that names a comment ON a
    project)."""
    if ctx.project is None:
        return
    for comment in comments:
        object.__setattr__(comment, "_task_project_id", ctx.project.id)


async def get_comment(
    session: AsyncSession,
    *,
    comment_id: int,
    user: User,
    guild_id: int,
) -> Comment:
    """One comment, gated exactly like listing its parent's thread.

    The read-back half of the event contract: a ``comments.*`` event names an
    id, and this is what resolves it. Access is the parent's — read on the
    task's project or on the tool entity — same as ``list_comments``.
    """
    stmt = (
        select(Comment)
        .where(Comment.id == comment_id)
        .options(selectinload(Comment.author))
    )
    comment = (await session.exec(stmt)).one_or_none()
    if not comment:
        raise CommentNotFoundError(CommentMessages.NOT_FOUND)

    column, entity_id = _comment_target(comment)
    ctx = await _resolved_parent(
        session,
        column=column,
        entity_id=entity_id,
        guild_id=guild_id,
        user=user,
        access="read",
    )
    _stamp_task_project(ctx, comment)
    return comment


async def create_comment(
    session: AsyncSession,
    *,
    author: User,
    guild_id: int,
    content: str,
    task_id: Optional[int] = None,
    document_id: Optional[int] = None,
    project_id: Optional[int] = None,
    queue_id: Optional[int] = None,
    counter_group_id: Optional[int] = None,
    calendar_id: Optional[int] = None,
    dashboard_id: Optional[int] = None,
    parent_comment_id: Optional[int] = None,
) -> Comment:
    parent_comment = None
    if parent_comment_id is not None:
        parent_comment = await _get_comment(session, comment_id=parent_comment_id)
        if not parent_comment:
            raise CommentNotFoundError(CommentMessages.PARENT_NOT_FOUND)

    column, entity_id = _single_target(
        {
            "task_id": task_id,
            "document_id": document_id,
            "project_id": project_id,
            "queue_id": queue_id,
            "counter_group_id": counter_group_id,
            "calendar_id": calendar_id,
            "dashboard_id": dashboard_id,
        }
    )
    ctx = await _resolved_parent(
        session,
        column=column,
        entity_id=entity_id,
        guild_id=guild_id,
        user=author,
        access="write",
    )
    if parent_comment and getattr(parent_comment, column) != ctx.entity_id:
        raise CommentValidationError(CommentMessages.PARENT_MISMATCH)

    comment = Comment(
        content=content,
        created_by=cast(int, author.id),
        parent_comment_id=parent_comment_id,
        **{column: ctx.entity_id},
    )
    session.add(comment)
    await session.flush()
    await session.refresh(comment, attribute_names=["author"])
    _stamp_task_project(ctx, comment)

    await _process_comment_notifications(
        session,
        comment=comment,
        author=author,
        guild_id=guild_id,
        ctx=ctx,
        parent_comment=parent_comment,
    )

    return comment


async def _load_user(session: AsyncSession, user_id: int) -> User | None:
    """Load a user by ID."""
    result = await session.exec(select(User).where(User.id == user_id))
    return result.one_or_none()


async def _load_task_with_assignees(
    session: AsyncSession, task_id: int, guild_id: int
) -> tuple[Task, list[User], str] | None:
    """Load a task with its assignees and project name."""
    stmt = (
        select(Task, Project, Initiative)
        .join(Project, Project.id == Task.project_id)
        .join(Initiative, Initiative.id == Project.initiative_id)
        .where(Task.id == task_id, Initiative.guild_id == guild_id)
        .options(selectinload(Task.assignees))
    )
    result = await session.exec(stmt)
    row = result.one_or_none()
    if not row:
        return None
    task, project, _ = row
    return task, list(task.assignees), project.name


async def _process_comment_notifications(
    session: AsyncSession,
    *,
    comment: Comment,
    author: User,
    guild_id: int,
    ctx: _ParentContext,
    parent_comment: Comment | None,
) -> None:
    """Process all notifications for a new comment.

    Notification priority (deduplicated):
    1. Reply to comment → notify parent comment author
    2. @user mentions
    3. #task mentions → notify assignees
    4. Task comment → notify assignees
    5. Tool comment → notify the entity's creator
    """
    notified_user_ids: Set[int] = set()
    content = comment.content
    context_title = ctx.title

    # Tool parents beyond task/document link through the entity reference the
    # resolver understands; the original pair keeps its dedicated fields.
    extra_entity_type: str | None = None
    extra_entity_id: int | None = None
    if ctx.tool is not None and ctx.tool is not Tool.document:
        extra_entity_type = ctx.tool.value
        extra_entity_id = ctx.entity_id

    # 1. Reply to comment → notify parent comment author
    if parent_comment and parent_comment.created_by != author.id:
        parent_author = await _load_user(session, parent_comment.created_by)
        if parent_author:
            await notifications.notify_comment_reply(
                session,
                parent_author=parent_author,
                replier=author,
                comment_id=cast(int, comment.id),
                task_id=comment.task_id,
                document_id=comment.document_id,
                entity_type=extra_entity_type,
                entity_id=extra_entity_id,
                context_title=context_title,
                guild_id=guild_id,
            )
            notified_user_ids.add(parent_comment.created_by)

    # 2. Process @user mentions
    mentioned_user_ids = extract_mentioned_user_ids(content)
    for user_id in mentioned_user_ids:
        if user_id == author.id:
            continue
        if user_id in notified_user_ids:
            continue
        mentioned_user = await _load_user(session, user_id)
        if not mentioned_user:
            continue
        await notifications.notify_comment_mention(
            session,
            mentioned_user=mentioned_user,
            mentioned_by=author,
            comment_id=cast(int, comment.id),
            task_id=comment.task_id,
            document_id=comment.document_id,
            entity_type=extra_entity_type,
            entity_id=extra_entity_id,
            context_title=context_title,
            guild_id=guild_id,
        )
        notified_user_ids.add(user_id)

    # 3. Process #task mentions → notify assignees
    mentioned_task_ids = extract_mentioned_task_ids(content)
    for mentioned_task_id in mentioned_task_ids:
        task_data = await _load_task_with_assignees(
            session, mentioned_task_id, guild_id
        )
        if not task_data:
            continue
        mentioned_task, assignees, _ = task_data
        for assignee in assignees:
            if assignee.id == author.id:
                continue
            if assignee.id in notified_user_ids:
                continue
            await notifications.notify_task_mentioned_in_comment(
                session,
                assignee=assignee,
                mentioned_by=author,
                comment_id=cast(int, comment.id),
                mentioned_task_id=mentioned_task_id,
                mentioned_task_title=mentioned_task.title,
                context_task_id=comment.task_id,
                context_document_id=comment.document_id,
                context_entity_type=extra_entity_type,
                context_entity_id=extra_entity_id,
                context_title=context_title,
                guild_id=guild_id,
            )
            notified_user_ids.add(assignee.id)

    # 4. Task comment → notify assignees (who haven't been notified yet)
    if ctx.task is not None:
        task_with_assignees = await _load_task_with_assignees(
            session, cast(int, ctx.task.id), guild_id
        )
        if task_with_assignees:
            task, assignees, project_name = task_with_assignees
            for assignee in assignees:
                if assignee.id == author.id:
                    continue
                if assignee.id in notified_user_ids:
                    continue
                await notifications.notify_comment_on_task(
                    session,
                    assignee=assignee,
                    commenter=author,
                    comment_id=cast(int, comment.id),
                    task_id=task.id,
                    task_title=task.title,
                    project_name=project_name,
                    guild_id=guild_id,
                )
                notified_user_ids.add(assignee.id)

    # 5. Tool comment → notify the entity's creator (if not already notified)
    if ctx.resource is not None:
        owner = await _load_user(session, ctx.resource.created_by)
        if owner and owner.id != author.id and owner.id not in notified_user_ids:
            await notifications.notify_comment_on_resource(
                session,
                owner=owner,
                commenter=author,
                comment_id=cast(int, comment.id),
                entity_type=cast(Tool, ctx.tool).value,
                entity_id=ctx.entity_id,
                entity_name=ctx.title,
                guild_id=guild_id,
            )
            notified_user_ids.add(cast(int, owner.id))


async def list_comments(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    task_id: Optional[int] = None,
    document_id: Optional[int] = None,
    project_id: Optional[int] = None,
    queue_id: Optional[int] = None,
    counter_group_id: Optional[int] = None,
    calendar_id: Optional[int] = None,
    dashboard_id: Optional[int] = None,
) -> Sequence[Comment]:
    column, entity_id = _single_target(
        {
            "task_id": task_id,
            "document_id": document_id,
            "project_id": project_id,
            "queue_id": queue_id,
            "counter_group_id": counter_group_id,
            "calendar_id": calendar_id,
            "dashboard_id": dashboard_id,
        }
    )
    ctx = await _resolved_parent(
        session,
        column=column,
        entity_id=entity_id,
        guild_id=guild_id,
        user=user,
        access="read",
    )
    stmt = (
        select(Comment)
        .where(getattr(Comment, column) == ctx.entity_id)
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .options(selectinload(Comment.author))
    )
    comments = (await session.exec(stmt)).all()
    _stamp_task_project(ctx, *comments)
    return comments


async def delete_comment(
    session: AsyncSession,
    *,
    comment_id: int,
    user: User,
    guild_id: int,
    guild_role: GuildRole,
) -> Comment:
    comment = await _get_comment(session, comment_id=comment_id)
    if not comment:
        raise CommentNotFoundError(CommentMessages.NOT_FOUND)

    column, entity_id = _comment_target(comment)
    ctx = await _load_parent(
        session, column=column, entity_id=entity_id, guild_id=guild_id
    )
    if ctx is None:
        raise CommentNotFoundError(CommentMessages.NOT_FOUND)
    await _ensure_parent_access(session, ctx, user=user, access="read")
    _stamp_task_project(ctx, comment)
    initiative_id = ctx.initiative_id

    is_author = comment.created_by == user.id
    is_guild_admin = guild_role == GuildRole.admin
    is_initiative_manager = False
    if not is_author and not is_guild_admin and initiative_id is not None:
        is_initiative_manager = await rls_service.is_initiative_manager(
            session,
            initiative_id=initiative_id,
            user=user,
        )

    if not (is_author or is_guild_admin or is_initiative_manager):
        raise CommentPermissionError(CommentMessages.AUTHOR_ONLY_DELETE)

    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    retention_days = await guilds_service.get_guild_retention_days(session, guild_id)
    await soft_delete_entity(
        session,
        comment,
        deleted_by_user_id=user.id,
        retention_days=retention_days,
    )
    return comment


async def update_comment(
    session: AsyncSession,
    *,
    comment_id: int,
    user: User,
    guild_id: int,
    content: str,
) -> Comment:
    """Update a comment's content. Only the original author can edit."""
    comment = await _get_comment(session, comment_id=comment_id)
    if not comment:
        raise CommentNotFoundError(CommentMessages.NOT_FOUND)

    # Only the author can edit their own comment
    if comment.created_by != user.id:
        raise CommentPermissionError(CommentMessages.AUTHOR_ONLY_EDIT)

    # Verify access to the linked entity (same checks as delete_comment)
    column, entity_id = _comment_target(comment)
    ctx = await _load_parent(
        session, column=column, entity_id=entity_id, guild_id=guild_id
    )
    if ctx is None:
        raise CommentNotFoundError(CommentMessages.NOT_FOUND)
    await _ensure_parent_access(session, ctx, user=user, access="read")
    _stamp_task_project(ctx, comment)

    comment.content = content
    comment.updated_at = datetime.now(timezone.utc)
    session.add(comment)
    await session.flush()
    await session.refresh(comment, attribute_names=["author"])
    return comment
