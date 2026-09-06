"""Comments across every commentable surface.

``TOOL_COMMENT_TARGETS`` is the registry: **every** ``Tool`` entity is
commentable — one nullable FK per tool on ``comments``, drift-tested against
the enum — plus the task, the one content-level extra (it anchors to its
project for access). Reading a thread takes read access on the parent, posting
takes write access, exactly as it always has for tasks and documents.

Every tool entity also carries its own switch, ``comments_disabled``: while it
is set, that entity's thread is neither readable nor postable and the UI shows
none of it. Tasks have no switch — a task's thread belongs to the task, not to
the project's tool surface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, Optional, Set, cast

from sqlalchemy import ColumnElement, func
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import (
    CalendarMessages,
    CommentMessages,
    CounterMessages,
    DashboardMessages,
    PostMessages,
    QueueMessages,
)
from app.core.tools import Tool
from app.models.tenant.calendar import Calendar
from app.models.tenant.comment import Comment
from app.models.tenant.counter import CounterGroup
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.post import Post
from app.models.tenant.document import Document
from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.queue import Queue
from app.models.tenant.task import Task
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.services import rls as rls_service
from app.services import notifications
from app.services import permissions as permissions_service
from app.services.platform import accounts as accounts_service
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
    Tool.post: CommentTarget(
        Tool.post,
        Post,
        CommentMessages.TARGET_NOT_FOUND,
        PostMessages.FEATURE_DISABLED,
    ),
}

_TARGETS_BY_COLUMN: dict[str, CommentTarget] = {
    target.column: target for target in TOOL_COMMENT_TARGETS.values()
}

#: Every comment-parent column, task first — the single-parent rule and the
#: create/list surfaces all read this tuple.
COMMENT_PARENT_COLUMNS: tuple[str, ...] = ("task_id", *_TARGETS_BY_COLUMN)


async def annotate_comment_counts(
    session: AsyncSession,
    rows: Sequence[Any],
    *,
    column: str,
) -> None:
    """Set ``comment_count`` on each row from one grouped query.

    ``column`` is the comment-parent column these rows are the parent of —
    ``post_id`` for posts, ``queue_id`` for queues, and so on; every member of
    :data:`COMMENT_PARENT_COLUMNS` works. One statement for the whole page,
    rather than a count per row, because a board asks this about twenty posts
    at once.

    Trashed comments are excluded by the soft-delete filter, so a thread that
    was cleared out reads as empty rather than as history.
    """
    if column not in COMMENT_PARENT_COLUMNS:
        raise KeyError(f"{column} is not a comment parent")
    ids = [row.id for row in rows if getattr(row, "id", None) is not None]
    if not ids:
        return
    parent = getattr(Comment, column)
    result = await session.exec(
        select(parent, func.count(Comment.id))
        .where(parent.in_(tuple(ids)))
        .group_by(parent)
    )
    counts = dict(result.all())
    for row in rows:
        # ``object.__setattr__`` because these are SQLModel rows and the field
        # is not a column — it rides along for serialization only.
        object.__setattr__(row, "comment_count", counts.get(row.id, 0))


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


def comment_target(comment: Comment) -> tuple[str, int]:
    """Which parent column a comment hangs off, and that parent's id."""
    return _comment_target(comment)


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
    tool's master switch first, then its own comment switch, then DAC — where a
    request that reaches the whole guild (guild admin, or a live PAM grant at
    the right level) needs no grant row.

    The comment switch is checked for tool entities only: a task's thread
    belongs to the task, so a project with comments off still has task threads.
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
        if getattr(ctx.resource, "comments_disabled", False):
            raise CommentPermissionError(CommentMessages.COMMENTS_DISABLED)
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


def serialize_comment(comment: Comment, *, viewer_id: Optional[int] = None):
    """The read shape of one comment. A task comment reports its task's
    project — resolved by whichever service call loaded the parent — through
    the same ``project_id`` field a project comment fills from its own column.

    Reactions come from rows stamped on the comment by
    :func:`attach_reactions`; a comment that was never stamped serializes with
    none rather than issuing a query of its own here.
    """
    from app.schemas.tenant.comment import CommentRead
    from app.services.tenant import reactions as reactions_service

    read = CommentRead.model_validate(comment)
    task_project_id = getattr(comment, "_task_project_id", None)
    if task_project_id is not None:
        read.project_id = task_project_id
    rows = getattr(comment, "_reactions", None)
    if rows:
        read.reactions = reactions_service.summarize(rows, viewer_id=viewer_id)
    return read


async def attach_reactions(session: AsyncSession, *comments: Comment) -> None:
    """Load every comment's reactions in ONE query and stamp them on the rows.

    A plain attribute, like ``_task_project_id`` above — the comments table has
    no relationship to the polymorphic reactions table, and a thread of fifty
    must not become fifty queries.
    """
    from app.services.tenant import reactions as reactions_service
    from app.core.reactions import ReactionTarget

    rows = [c for c in comments if c.id is not None]
    if not rows:
        return
    grouped = await reactions_service.load_reactions(
        session,
        target=ReactionTarget.comment,
        target_ids=[cast(int, c.id) for c in rows],
    )
    for comment in rows:
        object.__setattr__(comment, "_reactions", grouped.get(comment.id, []))


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


async def get_comment_with_parent(
    session: AsyncSession,
    *,
    comment_id: int,
    user: User,
    guild_id: int,
    access: str = "read",
) -> tuple[Comment, _ParentContext]:
    """One comment plus its resolved parent, gated at ``access``.

    The parent is what every decision about a comment runs through — who may
    read the thread, who may add to it — so anything acting ON a comment
    (reactions, the read-back route) resolves both in one call rather than
    re-deriving the chain.
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
        access=access,
    )
    _stamp_task_project(ctx, comment)
    await attach_reactions(session, comment)
    return comment, ctx


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
    comment, _ctx = await get_comment_with_parent(
        session, comment_id=comment_id, user=user, guild_id=guild_id, access="read"
    )
    return comment


async def initiative_of_comment(
    session: AsyncSession, comment: Comment
) -> Optional[int]:
    """Which initiative a comment's parent lives in, or None.

    Resolved through whichever parent the comment hangs off — the task's
    project, or the tool entity itself. A parent that names no initiative (a
    guild-level calendar) yields None, and so does a parent the routed session
    cannot see. Both callers of this — the comment events and the reaction
    events — must land in the SAME room for the same comment, which is why
    there is one lookup rather than two.
    """
    if comment.task_id is not None:
        row = (
            await session.exec(
                select(Project.initiative_id)
                .join(Task, Task.project_id == Project.id)
                .where(Task.id == comment.task_id)
            )
        ).one_or_none()
        return row
    for target in TOOL_COMMENT_TARGETS.values():
        value = getattr(comment, target.column)
        if value is None:
            continue
        return (
            await session.exec(
                select(target.model.initiative_id).where(target.model.id == value)
            )
        ).one_or_none()
    return None


def comment_target_path(comment: Comment, ctx: _ParentContext) -> str:
    """Where a notification about ``comment`` should land.

    The comment has no page of its own — it lives on its parent's — so the
    address is the parent's, built with the same helpers the comment
    notifications use so both point at the same place.
    """
    from app.services import notifications

    if comment.task_id is not None:
        return notifications.task_target_path(
            comment.task_id, ctx.project.id if ctx.project is not None else None
        )
    if comment.document_id is not None:
        return notifications.document_target_path(comment.document_id)
    return notifications.tool_target_path(cast(Tool, ctx.tool).value, ctx.entity_id)


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
    post_id: Optional[int] = None,
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
            "post_id": post_id,
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


async def _notify_target(
    user_id: int | None, *, actor_id: int | None = None
) -> User | None:
    """Who to tell, with the preferences and address a notice needs.

    On the system engine: an account's notification settings and address are
    not a guild's to read. ``actor_id`` drops anybody who ignores whoever is
    doing this, so they are simply not a recipient."""
    return await accounts_service.load_one(user_id, excluding_ignorers_of=actor_id)


async def _notify_targets(
    user_ids: list[int], *, actor_id: int | None = None
) -> list[User]:
    """The same, for the several people one comment can reach."""
    return await accounts_service.load_all(user_ids, excluding_ignorers_of=actor_id)


async def _load_task_with_assignees(
    session: AsyncSession, task_id: int, guild_id: int
) -> tuple[Task, list[MemberProfile], str] | None:
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
        parent_author = await _notify_target(
            parent_comment.created_by, actor_id=author.id
        )
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
        mentioned_user = await _notify_target(user_id, actor_id=author.id)
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
        wanted = [
            assignee.id
            for assignee in assignees
            if assignee.id != author.id and assignee.id not in notified_user_ids
        ]
        for assignee in await _notify_targets(wanted, actor_id=author.id):
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
            wanted = [
                assignee.id
                for assignee in assignees
                if assignee.id != author.id and assignee.id not in notified_user_ids
            ]
            for assignee in await _notify_targets(wanted, actor_id=author.id):
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
        owner = await _notify_target(ctx.resource.created_by, actor_id=author.id)
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
    post_id: Optional[int] = None,
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
            "post_id": post_id,
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
    await attach_reactions(session, *comments)
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
    # The edit reply is what the client writes back into its cache, so it must
    # carry the reactions the comment still has — serializing without them
    # would blank the chips until the next refetch.
    await attach_reactions(session, comment)
    return comment
