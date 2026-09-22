"""Comments across every commentable surface.

``TOOL_COMMENT_TARGETS`` is the registry: **every** ``Tool`` entity is
commentable — one nullable FK per tool on ``comments``, drift-tested against
the enum — plus the content-level extras in ``EXTRA_COMMENT_TARGETS``, which
are not tools and anchor to the tool that owns them for access (a task to its
project, a wiki page to its wiki). Reading a thread takes read access on that
anchor, posting takes write access, exactly as it always has for tasks and
documents.

Every tool entity also carries its own switch, ``comments_enabled``: while it
is off, that entity's thread is neither readable nor postable and the UI shows
none of it. An extra has no switch of its own, so its anchor's is what answers
for it — a wiki with comments off has no threads on its pages. The task is the
exception: its thread belongs to the task, not to the project's tool surface,
so a project with comments off still has task threads.
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

from app.core.routed_guild import routed_guild_id
from app.core.messages import (
    CommentMessages,
    TaskMessages,
    WikiMessages,
)
from app.core.tools import Tool
from app.db.initiative_rls import (
    COMMENT_PARENTS,
    COMMENT_PARENT_COLUMNS as RLS_COMMENT_PARENT_COLUMNS,
)
from app.models.tenant._mixins import tool_models
from app.models.tenant.calendar import Calendar
from app.models.tenant.comment import Comment
from app.models.tenant.counter import CounterGroup
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.post import Post
from app.models.tenant.gallery import Gallery
from app.models.tenant.document import Document
from app.models.platform.guild import GUILD_ADMIN_ROLES, GuildRole
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.queue import Queue
from app.models.tenant.wiki import Wiki, WikiPage
from app.models.tenant.task import Task
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.services import rls as rls_service
from app.services.tenant import content_references
from app.services import notifications
from app.services import permissions as permissions_service
from app.services import reachability
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


#: Every tool's model, imported so it is *registered*: a class has to have been
#: imported before ``tool_models`` can find it by table name. Naming them here is
#: what makes the lookup below independent of import order.
_REGISTERED = (
    Calendar,
    CounterGroup,
    Dashboard,
    Document,
    Gallery,
    Post,
    Project,
    Queue,
    Wiki,
)

#: The one tool whose "no such thing" code is its own rather than the generic
#: comment-target one. A document comment is the oldest surface here and its
#: refusal is already mapped in every locale under that code.
_OWN_NOT_FOUND_CODE = frozenset({Tool.document})

# Every Tool is commentable, derived from the enum rather than listed — a new
# tool carries a comment thread the day its model exists. comments_test asserts
# this spans the enum, and that the columns here match the model and the RLS
# parent registry (app.db.initiative_rls._COMMENT_PARENTS).
TOOL_COMMENT_TARGETS: dict[Tool, CommentTarget] = {
    tool: CommentTarget(
        tool,
        tool_models()[tool.plural],
        tool.not_found_code
        if tool in _OWN_NOT_FOUND_CODE
        else CommentMessages.TARGET_NOT_FOUND,
        tool.feature_disabled_code,
    )
    for tool in Tool
}


_TARGETS_BY_COLUMN: dict[str, CommentTarget] = {
    target.column: target for target in TOOL_COMMENT_TARGETS.values()
}


@dataclass(frozen=True)
class ExtraCommentTarget:
    """A commentable thing that is NOT a tool — a task, a wiki page.

    It has no sharing and no comment switch of its own, so the tool it belongs
    to answers both; which tool that is, and how a row reaches it, is declared
    once in ``app.db.initiative_rls.COMMENT_PARENTS`` and read from there. What
    is left is what only this layer knows: the model to load, the field that
    titles the thread, and the code its absence reports.
    """

    #: The kind's name — the ``{kind}_id`` column, and what an event or a
    #: notification about this thread calls it.
    kind: str
    model: type[SQLModel]
    #: The column holding what the thread is called.
    title_field: str
    not_found: str
    #: Whether a new comment tells whoever wrote the row. A page's author
    #: wants to hear about a note on their page; a task instead tells the
    #: people it is assigned to, which is a different question and already
    #: answered further down.
    notifies_author: bool = True
    #: Whether the anchoring tool's ``comments_enabled`` governs this thread.
    #: True for a wiki page — the wiki is where that switch is offered, and a
    #: wiki with comments off should have none on its pages. False for a task:
    #: its thread belongs to the task, so a project with comments off still
    #: has task threads. Either way the anchor's SHARING is what admits the
    #: reader.
    anchor_switch: bool = True

    @property
    def column(self) -> str:
        return f"{self.kind}_id"


#: The content-level extras, in the order the parent registry declares them.
EXTRA_COMMENT_TARGETS: dict[str, ExtraCommentTarget] = {
    target.column: target
    for target in (
        ExtraCommentTarget(
            "task",
            Task,
            "title",
            TaskMessages.NOT_FOUND,
            notifies_author=False,
            anchor_switch=False,
        ),
        ExtraCommentTarget("wiki_page", WikiPage, "title", WikiMessages.PAGE_NOT_FOUND),
    )
}

#: Every comment-parent column, extras first — the single-parent rule and the
#: create/list surfaces all read this tuple. Ordered by the parent registry so
#: this and the policies cannot disagree about the set.
COMMENT_PARENT_COLUMNS: tuple[str, ...] = RLS_COMMENT_PARENT_COLUMNS


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

    A tool comment carries the tool and its row (``tool``/``resource`` set). An
    extra carries its own row as well (``extra``/``extra_row``), plus the tool
    it anchors to — a task also fills ``task``/``project``, which is the pair
    the task notifications and the task serializer read. Either way the fields
    every caller needs — the comments column, the parent id, the initiative
    (``None`` for a guild-level calendar), a display title — are filled.
    """

    column: str
    entity_id: int
    initiative_id: Optional[int]
    title: str
    task: Optional[Task] = None
    project: Optional[Project] = None
    tool: Optional[Tool] = None
    resource: Optional[SQLModel] = None
    extra: Optional[ExtraCommentTarget] = None
    extra_row: Optional[SQLModel] = None

    @property
    def ref_type(self) -> Optional[str]:
        """What a notification about this thread is ABOUT — the extra's own
        kind where there is one, else the tool. This names the thread, which is
        not always the same as where a link to it goes."""
        if self.extra is not None:
            return self.extra.kind
        return self.tool.value if self.tool is not None else None

    @property
    def address(self) -> Optional[tuple[str, int]]:
        """Where a link about this thread should land, as (ref type, id).

        Not every thread's parent has a page of its own: a wiki page is read
        inside its wiki and has no address taking only its own id, so a link
        about one opens the wiki. The tool it anchors to is always addressable,
        which is why that is the fallback rather than nothing.
        """
        if self.extra is not None:
            if self.tool is None or self.resource is None:
                return None
            return self.tool.value, cast(int, self.resource.id)
        if self.tool is None:
            return None
        return self.tool.value, self.entity_id


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
        extra=EXTRA_COMMENT_TARGETS["task_id"],
        extra_row=task,
    )


async def _get_extra_context(
    session: AsyncSession,
    target: ExtraCommentTarget,
    *,
    entity_id: int,
    guild_id: int,
) -> Optional[_ParentContext]:
    """One extra's row, resolved through the tool that answers for it.

    The anchor is loaded by the same call a comment ON that tool would make, so
    a thread on a page is gated by exactly what a thread on its wiki is gated
    by — the master switch, the comment switch, and the sharing — and only the
    identity of the thread differs.
    """
    row = (
        await session.exec(
            select(target.model).where(target.model.id == entity_id)  # type: ignore[attr-defined]
        )
    ).one_or_none()
    if row is None:
        return None
    parent = COMMENT_PARENTS[target.column]
    anchor = await _get_tool_context(
        session,
        TOOL_COMMENT_TARGETS[parent.governed_by],
        entity_id=getattr(row, cast(str, parent.tool_fk)),
        guild_id=guild_id,
    )
    if anchor is None:
        return None
    anchor.column = target.column
    anchor.entity_id = cast(int, row.id)
    anchor.title = getattr(row, target.title_field)
    anchor.extra = target
    anchor.extra_row = row
    return anchor


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
    if target.tool in permissions_service.READ_VISIBLE:
        # This tool has something between "shared with me" and "I can see it",
        # and answering it asks whether the caller could edit the row — which
        # reads its sharing and its initiative's roster. Loaded only for the
        # tools that ask, so the other six pay nothing.
        stmt = stmt.options(
            selectinload(target.model.grants),  # type: ignore[attr-defined]
            selectinload(target.model.initiative).selectinload(  # type: ignore[attr-defined]
                Initiative.memberships
            ),
        )
    row = (await session.exec(stmt)).one_or_none()
    if row is None:
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
    extra = EXTRA_COMMENT_TARGETS.get(column)
    if extra is not None:
        return await _get_extra_context(
            session, extra, entity_id=entity_id, guild_id=guild_id
        )
    return await _get_tool_context(
        session, _TARGETS_BY_COLUMN[column], entity_id=entity_id, guild_id=guild_id
    )


async def _shares_resource(
    session: AsyncSession,
    id_col: ColumnElement[int],
    *,
    resource_id: int,
) -> bool:
    """Whether this request can reach one resource by id.

    Selecting the id IS the question. The resource's own table carries the
    sharing gate, so a row the request may not reach does not come back, and
    the id is already known — loading the row with its grants to run the engine
    over them would ask what the lookup has just answered.

    Asked at read whatever the caller is doing, which is what the comment
    tables themselves ask: ``DAC_WRITE_COMMANDS`` puts ``comments`` in the
    responding set, so every command on a thread is gated by whether the
    parent is reachable, not by whether it is editable. You may answer a notice
    you cannot rewrite.
    """
    return (
        await session.exec(select(id_col).where(id_col == resource_id))
    ).first() is not None


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

    The comment switch is checked through whatever answers for the thread: a
    tool entity's own, or — for an extra — the tool it anchors to, which is how
    a wiki with comments off has none on its pages. The task is the exception,
    and gets the project's sharing without the project's switch: its thread
    belongs to the task, not to the project's tool surface.
    """
    if ctx.extra is not None and not ctx.extra.anchor_switch:
        # An extra whose thread is its own: admitted by the anchor's sharing,
        # asked none of its switches. The task is the one, and its context
        # carries the project that answers for it.
        anchor_model, anchor_row = Project, ctx.project
    else:
        target = TOOL_COMMENT_TARGETS[cast(Tool, ctx.tool)]
        initiative = getattr(ctx.resource, "initiative", None)
        if (
            target.feature_disabled is not None
            and initiative is not None
            and not getattr(initiative, target.tool.view_permission)
        ):
            raise CommentPermissionError(target.feature_disabled)
        if not getattr(ctx.resource, "comments_enabled", True):
            raise CommentPermissionError(CommentMessages.COMMENTS_DISABLED)
        anchor_model, anchor_row = target.model, ctx.resource
        # A parent that has not gone up yet has no thread to join: a scheduled
        # post is a draft, and reading or writing its comments would say it
        # exists. Asked before the sharing decision below, because the answer
        # for anyone who could edit it is the ordinary one.
        if permissions_service.hidden_from_reader(
            target.tool, ctx.resource, cast(int, user.id)
        ):
            raise CommentNotFoundError(target.not_found)

    if permissions_service.request_bypasses_dac(routed_guild_id(), access=access):
        return
    if await _shares_resource(
        session,
        anchor_model.id,  # type: ignore[attr-defined]
        resource_id=cast(int, anchor_row.id),
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
    extra = EXTRA_COMMENT_TARGETS.get(column)
    if extra is not None:
        return extra.not_found
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
        # The policies took the parent out before this ran. In the initiative
        # it is the reader's to know about, so sharing is what refused it.
        table = COMMENT_PARENTS[column].table
        if await reachability.reader_is_in_the_initiative(
            table, entity_id, cast(int, user.id), guild_id
        ):
            raise CommentPermissionError(CommentMessages.PERMISSION_DENIED)
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
        # The policies took it out before this ran. In the initiative it is
        # theirs to know about, so a later gate is what refused it.
        if await reachability.reader_is_in_the_initiative(
            "comments", comment_id, cast(int, user.id), guild_id
        ):
            raise CommentPermissionError(CommentMessages.PERMISSION_DENIED)
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


def comment_target_path(comment: Comment, ctx: _ParentContext) -> str:
    """Where a notification about ``comment`` should land.

    The comment has no page of its own — it lives on its parent's — so the
    address is the parent's, built with the same helpers the comment
    notifications use so both point at the same place.
    """
    from app.services import notifications

    if comment.task_id is not None:
        return notifications.reference_path("task", comment.task_id)
    if comment.document_id is not None:
        return notifications.reference_path(Tool.document, comment.document_id)
    address = ctx.address
    if address is None:  # pragma: no cover - every parent resolves to one
        return "/"
    return notifications.reference_path(*address)


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
    gallery_id: Optional[int] = None,
    wiki_id: Optional[int] = None,
    wiki_page_id: Optional[int] = None,
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
            "wiki_page_id": wiki_page_id,
            "document_id": document_id,
            "project_id": project_id,
            "queue_id": queue_id,
            "counter_group_id": counter_group_id,
            "calendar_id": calendar_id,
            "dashboard_id": dashboard_id,
            "post_id": post_id,
            "gallery_id": gallery_id,
            "wiki_id": wiki_id,
        }
    )
    ctx = await _resolved_parent(
        session,
        column=column,
        entity_id=entity_id,
        guild_id=guild_id,
        user=author,
        # Answering a thread is not editing what it hangs off — reaching the
        # parent is the gate, and its comment switch is the other half.
        access="read",
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
    await content_references.sync_for_comment(
        session, comment, author_id=cast(int, author.id)
    )

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
        .where(Task.id == task_id)
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
    # Which sidebar row this comment belongs under. A tool comment names its
    # own tool; a task comment belongs to the Projects list the task lives in.
    comment_tool = (
        ctx.tool.value
        if ctx.tool is not None
        else Tool.project.value
        if ctx.task is not None
        else None
    )

    # Parents beyond task/document link through the entity reference the
    # resolver understands; the original pair keeps its dedicated fields. An
    # extra names ITSELF here — a note on a page opens the page, not the wiki.
    extra_entity_type: str | None = None
    extra_entity_id: int | None = None
    if ctx.tool is not None and ctx.tool is not Tool.document:
        extra_entity_type = ctx.ref_type
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
                initiative_id=ctx.initiative_id,
                tool=comment_tool,
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
            initiative_id=ctx.initiative_id,
            tool=comment_tool,
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
                initiative_id=ctx.initiative_id,
                tool=comment_tool,
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
                    initiative_id=ctx.initiative_id,
                    tool=comment_tool,
                )
                notified_user_ids.add(assignee.id)

    # 5. Comment on a tool entity, or on an extra that tells its author →
    #    notify whoever wrote it (if not already notified). The row is the one
    #    the thread hangs off, so a note on a page reaches the page's author
    #    rather than whoever started the wiki.
    owner_row = ctx.extra_row if ctx.extra is not None else ctx.resource
    if owner_row is not None and (ctx.extra is None or ctx.extra.notifies_author):
        owner = await _notify_target(owner_row.created_by, actor_id=author.id)
        if owner and owner.id != author.id and owner.id not in notified_user_ids:
            await notifications.notify_comment_on_resource(
                session,
                owner=owner,
                commenter=author,
                comment_id=cast(int, comment.id),
                entity_type=cast(str, ctx.ref_type),
                entity_id=ctx.entity_id,
                entity_name=ctx.title,
                guild_id=guild_id,
                initiative_id=ctx.initiative_id,
                tool=comment_tool,
                # The notice is ABOUT the page; it OPENS the wiki, because that
                # is what has an address. Rolled up per thread all the same.
                target=ctx.address,
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
    gallery_id: Optional[int] = None,
    wiki_id: Optional[int] = None,
    wiki_page_id: Optional[int] = None,
) -> Sequence[Comment]:
    column, entity_id = _single_target(
        {
            "task_id": task_id,
            "wiki_page_id": wiki_page_id,
            "document_id": document_id,
            "project_id": project_id,
            "queue_id": queue_id,
            "counter_group_id": counter_group_id,
            "calendar_id": calendar_id,
            "dashboard_id": dashboard_id,
            "post_id": post_id,
            "gallery_id": gallery_id,
            "wiki_id": wiki_id,
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
    is_guild_admin = guild_role in GUILD_ADMIN_ROLES
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
    # A trashed comment is out of the conversation, so what it alone pointed at
    # is no longer something this thing references.
    await content_references.sync_for_comment(
        session, comment, author_id=cast(int, user.id)
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
    await content_references.sync_for_comment(
        session, comment, author_id=cast(int, user.id)
    )
    await session.refresh(comment, attribute_names=["author"])
    # The edit reply is what the client writes back into its cache, so it must
    # carry the reactions the comment still has — serializing without them
    # would blank the chips until the next refetch.
    await attach_reactions(session, comment)
    return comment
